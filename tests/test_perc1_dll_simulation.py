import math

import pytest

from load_models.perc1_dll import MODEL as PERC1_DLL
from load_models.perc1_dll.simulation import simulate_perc1_response
from presets.ridethrough import RIDE_THROUGH_PRESETS


def _lag(start, level, threshold, tau=0.02):
    """Time for the TVM/TFRQ-filtered value, stepped from `start` to `level`,
    to cross `threshold` - the delay PSS/E adds before a stage's timer starts
    (measured in the PSS/E validation library, which is not published)."""
    return tau * math.log((start - level) / (threshold - level))


def test_simulate_perc1_response_trips_via_earlier_stage_2_not_stage_1():
    """The time-domain simulation (voltage(t)/power(t) panels) must evaluate
    all 4 Option-3 stages, not just stage 1 - PSS/E testing confirmed the
    compiled DLL does, and this is exactly the discriminating behavior the
    PSS/E validation library (not published) shows in real PSS/E: a 0.6s/0.75pu sag is far short of stage 1's own 2.0s dwell
    (DMA), but stage 2's shorter 0.5s dwell (DMA1) completes within the
    window and trips first."""
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    params = dict(preset.it_bundle)
    assert params["DMA"] == 2.00 and params["DMA1"] == 0.50  # sanity: real ERCOT tiers

    sim = simulate_perc1_response(params, fault_duration_s=0.6, fault_voltage_pu=0.75)

    assert sim["trips"] is True
    assert sim["trip_type"] == "undervoltage"
    # trip_time = FAULT_START (0.5) + the filtered voltage's crossing of
    # 0.80 pu + stage 2's own dwell (0.5), NOT stage 1's 2.0s (which this
    # 0.6s fault never reaches).
    assert sim["markers"]["trip_time"] == pytest.approx(0.5 + _lag(1.0, 0.75, 0.80) + 0.5)


def test_simulate_perc1_response_rides_through_when_no_stage_completes():
    """The mirror case: a sag shallow/short enough that not even the
    fastest-completing stage's dwell elapses within the fault must ride
    through, not trip."""
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    params = dict(preset.it_bundle)

    sim = simulate_perc1_response(params, fault_duration_s=0.1, fault_voltage_pu=0.75)

    assert sim["trips"] is False
    assert sim["trip_type"] is None


def test_armed_required_delay_surfaces_why_a_sag_rides_through():
    """ERCOT NOGRR282's shallowest mandatory undervoltage tier (0.90pu)
    requires a full 2.00s hold - much longer than its deeper tiers (0.80pu/
    0.50s, 0.50pu/0.25s, 0.20pu/0.15s) - so a 0.6s sag to 0.85pu (armed only
    by the 0.90pu stage; too shallow to arm any deeper one) correctly rides
    through. armed_required_delay_s must surface *why* (2.00s required, only
    0.6s held) rather than silently looking identical to a depth that never
    arms anything at all."""
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    params = dict(preset.it_bundle)

    sim = simulate_perc1_response(params, fault_duration_s=0.6, fault_voltage_pu=0.85)
    assert sim["trips"] is False
    # 2.00s plus the time the filtered voltage takes to cross 0.90 pu, less
    # the time it stays below 0.90 pu after the sag ends.
    assert sim["armed_required_delay_s"] == pytest.approx(
        2.00 + _lag(1.0, 0.85, 0.90) - _lag(0.85, 1.0, 0.90), abs=1e-6)

    # Held long enough, the same depth now trips.
    sim_long = simulate_perc1_response(params, fault_duration_s=2.1, fault_voltage_pu=0.85)
    assert sim_long["trips"] is True
    assert sim_long["trip_type"] == "undervoltage"

    # A depth that doesn't reach ANY threshold at all has no requirement to
    # report - genuinely nothing is armed, not just "not yet armed long enough".
    sim_none = simulate_perc1_response(params, fault_duration_s=0.6, fault_voltage_pu=0.95)
    assert sim_none["trips"] is False
    assert sim_none["armed_required_delay_s"] is None


def test_overvoltage_trips_over_1_1pu_after_2s_and_immediately_over_1_2pu():
    """ERCOT NOGRR282's own envelope has two real overvoltage setpoints: the
    continuous ceiling (1.10pu) and the published mandatory tier (1.20pu,
    2.00s). Read literally, "up to 1.20 pu: must tolerate for at least
    2.00 s" describes the whole band ABOVE the continuous ceiling, not a
    threshold that only starts mattering at 1.20pu - so any swell over
    1.10pu can trip after 2.00s (it cannot ride through 1.15pu
    indefinitely), while a swell over 1.20pu can trip essentially
    immediately, regardless of how long it's held. Both setpoints are
    ERCOT's own published numbers - no intermediate voltage breakpoint is
    invented. This is the concrete case a user reported as 'overvoltage
    isn't working' (a swell above 1.20pu was incorrectly riding through for
    the full 2.00s no matter how far past 1.20pu it went; a swell held
    indefinitely at 1.15pu was incorrectly never tripping at all)."""
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    params = dict(preset.it_bundle)

    # Strictly above the published 1.20pu tier: trips almost instantly, even
    # on a very short-duration swell.
    sim_severe = simulate_perc1_response(params, fault_duration_s=0.05, fault_voltage_pu=1.25)
    assert sim_severe["trips"] is True
    assert sim_severe["trip_type"] == "overvoltage"

    # Between the continuous ceiling and the published tier (1.10-1.20pu):
    # rides through a short hold, but cannot ride through indefinitely -
    # trips once held for the published 2.00s.
    sim_brief = simulate_perc1_response(params, fault_duration_s=0.6, fault_voltage_pu=1.15)
    assert sim_brief["trips"] is False
    assert sim_brief["armed_required_delay_s"] == pytest.approx(
        2.00 + _lag(1.0, 1.15, 1.10) - _lag(1.15, 1.0, 1.10), abs=1e-6)

    sim_held = simulate_perc1_response(params, fault_duration_s=2.1, fault_voltage_pu=1.15)
    assert sim_held["trips"] is True
    assert sim_held["trip_type"] == "overvoltage"

    # Inside the continuous operating band entirely (at or below 1.10pu):
    # never armed, rides through no matter how long it's held.
    sim_continuous = simulate_perc1_response(params, fault_duration_s=3.0, fault_voltage_pu=1.05)
    assert sim_continuous["trips"] is False
    assert sim_continuous["armed_required_delay_s"] is None

    # Inside the continuous operating band entirely: never armed.
    sim_continuous = simulate_perc1_response(params, fault_duration_s=3.0, fault_voltage_pu=1.05)
    assert sim_continuous["trips"] is False
    assert sim_continuous["armed_required_delay_s"] is None


# --- Frequency events ------------------------------------------------------


def _prc029_params():
    return dict(RIDE_THROUGH_PRESETS["nerc_prc029"].it_bundle)


def test_frequency_event_trips_via_the_stage_whose_delay_completes():
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    # PRC-029-1: below 58.8 Hz must ride through 299 s, then may trip.
    sim = simulate_perc1_frequency_response(_prc029_params(), fault_duration_s=310.0, fault_frequency_hz=58.5)

    assert sim["trips"]
    assert sim["trip_type"] == "underfrequency"
    assert sim["markers"]["trip_time"] == pytest.approx(0.5 + _lag(60.0, 58.5, 58.8) + 299.0)
    # Reconnects TUFRN1 after the filtered frequency is back above FUFRN1
    # (58.8 Hz), then ramps over RUFRN1.
    reconnect = 0.5 + 310.0 + _lag(58.5, 60.0, 58.8) + 100.0
    assert sim["markers"]["reconnect_start"] == pytest.approx(reconnect)
    assert sim["markers"]["reconnect_end"] == pytest.approx(reconnect + 5.0)


def test_frequency_event_uses_only_the_first_stage():
    """The vendor model has one frequency trip point per direction; the
    stage-2-4 CONs are marked NOT USED, so even an extreme excursion only trips
    once stage 1's delay has run (PRC-029-1: 299 s)."""
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    params = _prc029_params()
    params.update({"FOFTP2": 60.5, "TOFTP2": 0.0})  # a NOT USED stage must not trip

    short = simulate_perc1_frequency_response(params, fault_duration_s=5.0, fault_frequency_hz=62.5)
    held = simulate_perc1_frequency_response(params, fault_duration_s=300.0, fault_frequency_hz=62.5)

    assert not short["trips"]
    assert held["trip_type"] == "overfrequency"
    assert held["markers"]["trip_time"] == pytest.approx(0.5 + _lag(60.0, 62.5, 61.2) + 299.0)


def test_frequency_event_inside_the_mandatory_band_reports_what_it_would_take():
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    sim = simulate_perc1_frequency_response(_prc029_params(), fault_duration_s=60.0, fault_frequency_hz=58.5)

    assert not sim["trips"]
    assert sim["armed_required_delay_s"] == pytest.approx(
        299.0 + _lag(60.0, 58.5, 58.8) - _lag(58.5, 60.0, 58.8), abs=1e-6)
    assert [f for _, f in sim["f_points"]][2:4] == [58.5, 58.5]


def test_vendor_default_frequency_trip_point():
    """Without a published table the block keeps the vendor's stage 1: trip
    below 58.0 Hz after 100 s. A frequency above it never arms."""
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    params = dict(PERC1_DLL.default_cons)
    mild = simulate_perc1_frequency_response(params, fault_duration_s=600.0, fault_frequency_hz=59.5)
    deep = simulate_perc1_frequency_response(params, fault_duration_s=120.0, fault_frequency_hz=57.5)

    assert not mild["trips"] and mild["armed_required_delay_s"] is None
    assert deep["trips"] and deep["markers"]["trip_time"] == pytest.approx(0.5 + _lag(60.0, 57.5, 58.0) + 100.0)


def test_undervoltage_never_arms_exactly_at_the_continuous_band_edge():
    """SPP's own text states its continuous operating range as '0.90 <= V <=
    1.10 pu, no trip', with the next tier down stated as '0.80 <= V < 0.90
    pu' - strictly below 0.90. collapsed_point()/multi_stage_undervoltage()
    put that shared boundary voltage into VDPA (0.90pu), so a fault sitting
    exactly ON that edge must never arm the stage, no matter how long it's
    held - only a fault that actually sags below 0.90pu may. A user reported
    the app disconnecting a fault it should have ridden through; the bug was
    is_under_armed()/is_over_armed() using <=/>= (inclusive of the edge
    itself) instead of the strict </> every preset's own envelope wording
    (and validation.py's expected_trip_for_scenario) already assumes."""
    preset = RIDE_THROUGH_PRESETS["spp_hill"]
    params = dict(preset.it_bundle)
    assert params["VDPA"] == 0.90 and params["DMA"] == 2.00  # sanity: SPP's own tier

    on_edge = simulate_perc1_response(params, fault_duration_s=5.0, fault_voltage_pu=0.90)
    assert on_edge["trips"] is False
    assert on_edge["armed_required_delay_s"] is None

    # A hair below the edge is genuinely inside the 2.00s tier and still trips.
    just_below = simulate_perc1_response(params, fault_duration_s=5.0, fault_voltage_pu=0.899)
    assert just_below["trips"] is True
    assert just_below["trip_type"] == "undervoltage"


def test_overvoltage_trip_reconnects_through_the_high_side_cons():
    """Per the vendor documentation, overvoltage trips reconnect via
    VRUPA/TRUPA/RAMPUA, not VRPA/TDRA/RAMPA (confirmed in PSS/E)."""
    params = dict(RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle)
    # VRPA below 1.0 so the sag's recovery to 1.0 pu is inside the window.
    params.update({"TDRA": 1.0, "RAMPA": 0.1, "TRUPA": 20.0, "RAMPUA": 3.0, "VRPA": 0.95})

    swell = simulate_perc1_response(params, fault_duration_s=0.2, fault_voltage_pu=1.25)
    sag = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.2)

    # Each timer starts when the filtered voltage enters the window: below
    # VRUPA (1.05) after the swell, above VRPA (0.95) after the sag.
    swell_start = swell["fault_end"] + _lag(1.25, 1.0, 1.05) + 20.0
    assert swell["trip_type"] == "overvoltage"
    assert swell["markers"]["reconnect_start"] == pytest.approx(swell_start)
    assert swell["markers"]["reconnect_end"] == pytest.approx(swell_start + 3.0)
    assert sag["trip_type"] == "undervoltage"
    assert sag["markers"]["reconnect_start"] == pytest.approx(sag["fault_end"] + _lag(0.2, 1.0, 0.95) + 1.0)


# --- Measured runtime behavior (behavior probes, validation findings 1-5) ---


def _p_at(sim, t):
    """Power at time `t` from the response's breakpoints (last point at or
    before `t`; the sampled trace is dense where P moves)."""
    return [p for x, p in sim["p_points"] if x <= t][-1]


def _riding_through(params):
    """Same block, but nothing trips, so the steady sag power shows."""
    return dict(params, FCEASE=0.0)


@pytest.mark.parametrize("npa, ipmaxa, expected", [
    (0, 1.25, 0.3 * 1.25 / 0.8),  # constant power, current-limited: 0.469, not 1.0
    (0, 1.50, 0.3 * 1.50 / 0.8),
    (1, 1.25, 0.3),               # constant current: P = V, the limit never binds
    (2, 1.25, 0.09),              # constant impedance: P = V^2
])
def test_sag_power_follows_the_zip_exponent_until_the_current_limit(npa, ipmaxa, expected):
    """P = min(V^NPA, V*IPMAXA/LFM) in a held sag (validation finding 4.1)."""
    params = _riding_through(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    params.update({"NPA": npa, "IPMAXA": ipmaxa})

    sim = simulate_perc1_response(params, fault_duration_s=1.0, fault_voltage_pu=0.3)

    assert sim["trips"] is False
    assert _p_at(sim, 1.4) == pytest.approx(expected, abs=1e-3)


def test_sag_onset_dips_and_recovery_overshoots_to_about_one_over_v():
    """Ip lags its target on TRA: P first steps down with V, recovers as Ip
    catches up, and overshoots to ~1/V when the voltage steps back
    (validation finding 4.3)."""
    params = _riding_through(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)

    sim = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.75)

    assert _p_at(sim, 0.5) == pytest.approx(0.75, abs=0.01)    # Ip still sized for 1.0 pu
    assert _p_at(sim, 0.95) == pytest.approx(1.0, abs=1e-3)    # caught up
    assert _p_at(sim, 1.0) == pytest.approx(1 / 0.75, abs=0.02)  # Ip still sized for the sag
    assert _p_at(sim, 1.4) == pytest.approx(1.0, abs=1e-3)


def test_ipmaxa_below_lfm_cannot_draw_its_own_load():
    """With IPMAXA/LFM < 1 the block holds IPMAXA/LFM from t = 0
    (validation finding 4.1)."""
    params = _riding_through(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    params.update({"IPMAXA": 0.7})

    sim = simulate_perc1_response(params, fault_duration_s=0.1, fault_voltage_pu=0.95)

    assert sim["initial_power_pu"] == pytest.approx(0.875)
    assert _p_at(sim, 0.4) == pytest.approx(0.875)


def test_vrpa_1_stays_tripped_when_the_voltage_recovers_to_exactly_1_pu():
    """Reconnection needs VRPA < VFILT < VRUPA strictly (validation finding     1.1). ERCOT's VRPA = 1.00, so a recovery to 1.00 pu never reconnects; to
    1.01 pu it does."""
    params = dict(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    assert params["VRPA"] == 1.0

    stuck = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.3)
    above = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.3, recovery_voltage_pu=1.01)

    assert stuck["trips"] and not stuck["reconnects"]
    assert "reconnect_start" not in stuck["markers"]
    assert "VRPA 1.00" in stuck["stays_tripped_reason"]
    assert stuck["p_points"][-1][1] == pytest.approx(0.0, abs=1e-6)
    assert above["reconnects"]
    assert above["markers"]["reconnect_start"] == pytest.approx(
        above["fault_end"] + _lag(0.3, 1.01, 1.0) + params["TDRA"])


def test_vrpa_below_a_stage_voltage_cycles_every_tdra_plus_dma():
    """VRPA = 0.85 under stage 1 (0.90 pu, 2 s): a recovery to 0.87 pu both
    reconnects and re-arms the stage, so the block trips and reconnects every
    TDRA + DMA (validation finding 1.4). Stage timers run during the ramp."""
    params = dict(RIDE_THROUGH_PRESETS["standard_itic"].it_bundle)
    params.update({"VDPA": 0.90, "DMA": 2.0, "VRPA": 0.85, "TDRA": 0.93, "RAMPA": 0.0})

    sim = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.3, recovery_voltage_pu=0.87)

    trips = [e["time"] for e in sim["trip_events"]]
    assert sim["cycles"] and len(trips) >= 3
    assert sim["stays_tripped_reason"] is None
    assert trips[2] - trips[1] == pytest.approx(0.93 + 2.0)


def test_trip_and_reconnect_communication_delays():
    """CMTDELAY delays every trip; CMTDELAYC every reconnect (validation
    finding 5)."""
    params = dict(RIDE_THROUGH_PRESETS["standard_itic"].it_bundle)
    base = simulate_perc1_response(params, fault_duration_s=0.5, fault_voltage_pu=0.3)
    delayed = simulate_perc1_response(dict(params, CMTDELAY=0.1, CMTDELAYC=0.2),
                                      fault_duration_s=0.5, fault_voltage_pu=0.3)

    assert delayed["markers"]["trip_time"] == pytest.approx(base["markers"]["trip_time"] + 0.1)
    assert delayed["markers"]["reconnect_start"] == pytest.approx(base["markers"]["reconnect_start"] + 0.2)


def test_frequency_droop_scales_power_while_online():
    """P = Pref * (1 + DROOPA * db(f - 60, DBA) / 60): -16.7%/Hz with
    DROOPA = 10, nothing inside a DBA deadband in Hz, and Q-free
    (validation finding 3)."""
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    params = _prc029_params()
    assert params["DROOPA"] == 10.0
    sim = simulate_perc1_frequency_response(params, fault_duration_s=30.0, fault_frequency_hz=59.0)
    banded = simulate_perc1_frequency_response(dict(params, DBA=0.5), fault_duration_s=30.0, fault_frequency_hz=59.0)
    over = simulate_perc1_frequency_response(params, fault_duration_s=30.0, fault_frequency_hz=61.0)

    assert not sim["trips"]
    assert _p_at(sim, 20.0) == pytest.approx(1 - 10 * 1.0 / 60, abs=1e-4)
    assert _p_at(banded, 20.0) == pytest.approx(1 - 10 * 0.5 / 60, abs=1e-4)
    assert _p_at(over, 20.0) == pytest.approx(1 + 10 * 1.0 / 60, abs=1e-4)
    assert sim["p_points"][-1][1] == pytest.approx(1.0, abs=1e-4)


def test_frequency_reconnect_needs_the_frequency_window():
    """After a frequency trip the reconnect timer runs only while
    FUFRN1 < f < FOFRN1 (validation finding 1.5)."""
    from load_models.perc1_dll.simulation import simulate_perc1_frequency_response

    params = _prc029_params()
    stuck = simulate_perc1_frequency_response(params, fault_duration_s=310.0, fault_frequency_hz=58.5,
                                              recovery_frequency_hz=58.7)

    assert stuck["trips"] and not stuck["reconnects"]
    assert "FUFRN1 58.80" in stuck["stays_tripped_reason"]
