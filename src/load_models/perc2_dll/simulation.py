"""PERC2 DLL v2.3 response to a single constant-depth voltage or frequency event.

v2.3 runs the PERC1 DLL's logic (in PSS/E, the PERC1 DLL behavior checks pass on
both builds), so this is the PERC1 DLL simulator (`perc1_dll/simulation.py`: its filters, power loop and response
shape) with what v2.3 changed or adds, as PSS/E 35.6.4 and 36.7.1 measured it:

- **Ramps.** RAMPA and RAMPUA last their CON times LFM (LFM below 0.001 counts as 0.8); RUFRN1, ROFRN1, RAMPAMC and
  RAMPUAMC last their CON in seconds.
- **Momentary cessation** (ICON(M+1) = 1, FCEASE > 0). The filtered voltage strictly below VLBLK or above VUBLK ceases
  the load at once (no CMTDELAY): FracOn steps to 1 - FCEASE. It comes back after the filtered voltage has been
  strictly inside (VLRCMC, VURCMC) for TBLK + TDELY without a break, ramping over RAMPAMC (after a low-voltage
  cessation) or RAMPUAMC (high) to (1 - FCEASE) + FRECON x FCEASE - the same partial return as a trip. The stage
  timers keep running during a cessation: a stage that trips turns it into an ordinary trip, which reconnects on the
  stage path (VRPA < V < VRUPA, TDRA/TRUPA + CMTDELAYC, RAMPA/RAMPUA). A new cessation during the ramp ceases again.
"""

from __future__ import annotations

import math

from ..base import (
    FAULT_DURATION,
    FAULT_START,
    FREQUENCY_EVENT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from ..common import flag_on
from ..perc1_dll.simulation import (
    _MAX_TRIPS,
    _MIN_TAU,
    _TIME_EPS,
    OVERVOLTAGE_STAGE_CONS,
    UNDERVOLTAGE_STAGE_CONS,
    _Filtered,
    _first_trip_hold,
    _power_trace,
    simulate_perc1_frequency_response,
    simulate_perc1_response,
)
from .cons import RAMP_CONS, effective_lfm, ramp_seconds

MC_KINDS = {"mc_under": "low-voltage momentary cessation", "mc_over": "high-voltage momentary cessation"}


def perc1_equivalent(cons) -> dict:
    """The PERC1 DLL CONs that behave like `cons` on v2.3 with momentary cessation off: RAMPA and RAMPUA in seconds,
    LFM as the DLL uses it (0.8 below 0.001), negative delays as 0."""
    p = dict(cons)
    p["LFM"] = effective_lfm(cons)
    for n in ("TDRA", "TRUPA", "TUFRN1", "TOFRN1", "CMTDELAY", "CMTDELAYC", "TBLK", "TDELY"):
        p[n] = max(float(cons[n]), 0.0)  # the DLL treats a negative delay as 0 (validation finding 8)
    for n in RAMP_CONS:
        p[n] = ramp_seconds(cons, n)
    return p


def mc_active(cons) -> bool:
    return flag_on(cons, "MCFLAG") and float(cons["FCEASE"]) > 0


def _run_logic(sig, stages, windows, reconnect, fcease, frecon, trip_delay, reconnect_delay, horizon,
               first_trip_only=False):
    """The cease/reconnect state machine on the filtered voltage `sig`.

    stages: [(kind, threshold, delay)], kind "under"/"over" (stage trips, delayed by trip_delay) or "mc_under"/
    "mc_over" (momentary cessation, delay 0, not delayed). windows/reconnect: per kind, the open interval the reconnect
    timer needs and (delay, ramp). reconnect_delay (CMTDELAYC) applies to the stage kinds only."""
    levels = sorted({v for _k, v, _d in stages} | {x for w in windows.values() for x in w})
    final_on = 1.0 - fcease * (1.0 - frecon)

    t = 0.0
    mode = "on"  # on | ceased | ramping
    fracon = 1.0
    stage_started = [None] * len(stages)
    reconnect_started = None
    kind = None
    ramp = None  # (start, end, from, to)
    fracon_points = [(0.0, 1.0)]
    trips, reconnects = [], []

    def extra(k):
        return 0.0 if k.startswith("mc") else reconnect_delay

    while t < horizon:
        t_change = sig.next_change(t, levels)
        probe = sig.at(t + min(t_change - t, sig.tau) / 2.0)
        for i, (k, v, _d) in enumerate(stages):
            # A trip stops every timer. During a cessation the stage timers run on (and the MC checks are moot).
            live = mode != "ceased" or (kind.startswith("mc") and not k.startswith("mc"))
            armed = live and (probe < v if k.endswith("under") else probe > v)
            if not armed:
                stage_started[i] = None
            elif stage_started[i] is None:
                stage_started[i] = t
        if mode == "ceased":
            low, high = windows[kind]
            if low < probe < high:
                if reconnect_started is None:
                    reconnect_started = t
            else:
                reconnect_started = None

        candidates = [t_change, horizon]
        trip_at = [(start + d + (0.0 if k.startswith("mc") else trip_delay), i)
                   for i, ((k, _v, d), start) in enumerate(zip(stages, stage_started)) if start is not None]
        if trip_at:
            candidates.append(min(trip_at)[0])
        if reconnect_started is not None:
            candidates.append(reconnect_started + reconnect[kind][0] + extra(kind))
        if ramp is not None:
            candidates.append(ramp[1])
        t_next = max(min(candidates), t)

        if trip_at and min(trip_at)[0] <= t_next + _TIME_EPS:
            when, i = min(trip_at)
            if ramp is not None:  # ceased mid-ramp: FracOn is where the ramp had got to
                fracon = ramp[2] + (ramp[3] - ramp[2]) * (when - ramp[0]) / max(ramp[1] - ramp[0], _TIME_EPS)
                ramp = None
            new_kind = stages[i][0]
            if mode != "ceased":
                fracon_points += [(when, fracon), (when, 1.0 - fcease)]
                fracon = 1.0 - fcease
            trips.append({"time": when, "kind": new_kind, "stage": i, "escalated": mode == "ceased"})
            mode, kind = "ceased", new_kind
            stage_started = [None] * len(stages)
            reconnect_started = None
            t = when
            if first_trip_only or len(trips) >= _MAX_TRIPS:
                break
            continue
        if reconnect_started is not None and reconnect_started + reconnect[kind][0] + extra(kind) <= t_next + _TIME_EPS:
            start = reconnect_started + reconnect[kind][0] + extra(kind)
            end = start + max(reconnect[kind][1], 0.0)
            ramp = (start, end, fracon, final_on)
            reconnects.append({"start": start, "end": end, "kind": kind})
            fracon_points.append((start, fracon))
            mode, reconnect_started = "ramping", None
            t = start
            continue
        if ramp is not None and ramp[1] <= t_next + _TIME_EPS:
            fracon = ramp[3]
            fracon_points.append((ramp[1], fracon))
            t, ramp, mode = ramp[1], None, "on"
            continue

        if t_change == math.inf and not any(s is not None for s in stage_started) \
                and reconnect_started is None and ramp is None:
            break
        t = t_next

    return {"fracon_points": fracon_points, "trips": trips, "reconnects": reconnects,
            "tripped_at_end": mode == "ceased", "cycling": len(trips) >= _MAX_TRIPS, "final_kind": kind}


def _voltage_response(c, fault_duration_s, level, recovery_level):
    """A voltage event with momentary cessation on (the PERC1 DLL simulator's `_response`, with the v2.3 logic)."""
    fcease, frecon = float(c["FCEASE"]), float(c["FRECON"])
    fault_end = FAULT_START + fault_duration_s
    trip_delay, reconnect_delay = float(c["CMTDELAY"]), float(c["CMTDELAYC"])
    stages = ([("under", c[v], c[d]) for v, d in UNDERVOLTAGE_STAGE_CONS]
              + [("over", c[v], c[d]) for v, d in OVERVOLTAGE_STAGE_CONS]
              + [("mc_under", c["VLBLK"], 0.0), ("mc_over", c["VUBLK"], 0.0)])
    stage_window = (c["VRPA"], c["VRUPA"])
    mc_window = (c["VLRCMC"], c["VURCMC"])
    windows = {"under": stage_window, "over": stage_window, "mc_under": mc_window, "mc_over": mc_window}
    mc_delay = max(c["TBLK"], 0.0) + max(c["TDELY"], 0.0)
    reconnect = {"under": (c["TDRA"], c["RAMPA"]), "over": (c["TRUPA"], c["RAMPUA"]),
                 "mc_under": (mc_delay, c["RAMPAMC"]), "mc_over": (mc_delay, c["RAMPUAMC"])}
    tau = c["TVM"]
    longest_trip = max(d for _k, _v, d in stages) + trip_delay
    longest_reconnect = max(d + r for d, r in reconnect.values()) + reconnect_delay
    settle = 20.0 * max(tau, _MIN_TAU)

    def logic(duration, first_trip_only=False):
        end = FAULT_START + duration
        sig = _Filtered([(0.0, 1.0), (FAULT_START, level), (end, recovery_level)], tau)
        horizon = end + settle + (_MAX_TRIPS + 1) * (longest_trip + longest_reconnect) + 1.0
        return _run_logic(sig, stages, windows, reconnect, fcease, frecon, trip_delay, reconnect_delay, horizon,
                          first_trip_only), sig

    result, _sig = logic(fault_duration_s)
    trips, reconnects = result["trips"], result["reconnects"]
    armed_requirement = None
    if not trips and fcease > 0:
        armed_requirement = _first_trip_hold(lambda d: logic(d, first_trip_only=True)[0], longest_trip + settle + 1.0)

    stays = result["tripped_at_end"] and not result["cycling"]
    if trips:
        last = max([trips[-1]["time"]] + [r["end"] for r in reconnects])
        if stays:
            delay, ramp = reconnect[result["final_kind"]]
            last = max(last, fault_end + delay + ramp + (0.0 if result["final_kind"].startswith("mc") else
                                                          reconnect_delay))
        sim_end = last + max(0.5, last * 0.1)
    else:
        sim_end = fault_end + 1.0
    sim_end = max(sim_end, fault_end + settle)

    volt = _Filtered([(0.0, 1.0), (FAULT_START, level), (fault_end, recovery_level)], tau)
    freq = _Filtered([(0.0, NOMINAL_FREQUENCY_HZ)], c["TFRQ"])
    key_times = [FAULT_START, fault_end] + [tr["time"] for tr in trips] + \
        [x for r in reconnects for x in (r["start"], r["end"])]
    p_points, pref = _power_trace(c, volt, freq, result["fracon_points"], key_times, sim_end)

    names = {"under": "undervoltage", "over": "overvoltage", **MC_KINDS}
    markers = {}
    if trips:
        markers["trip_time"] = trips[0]["time"]
        if reconnects:
            markers["reconnect_start"] = reconnects[0]["start"]
            markers["reconnect_end"] = reconnects[0]["end"]
    reason = None
    if stays:
        k = result["final_kind"]
        low, high = windows[k]
        pair = ("VLRCMC", "VURCMC") if k.startswith("mc") else ("VRPA", "VRUPA")
        reason = (f"recovers to {recovery_level:.2f} pu, not strictly inside the reconnect window "
                  f"{pair[0]} {low:.2f} - {pair[1]} {high:.2f} pu")
    nominal_points = [(0.0, 1.0), (FAULT_START, 1.0), (FAULT_START, level), (fault_end, level),
                      (fault_end, recovery_level), (sim_end, recovery_level)]
    return {
        "event_kind": "voltage",
        "p_points": p_points,
        "v_points": nominal_points,
        "fault_voltage_pu": level,
        "trips": bool(trips),
        "trip_type": names[trips[0]["kind"]] if trips else None,
        "fault_start": FAULT_START,
        "fault_end": fault_end,
        "fault_duration_s": fault_duration_s,
        "sim_end": sim_end,
        "markers": markers,
        "armed_required_delay_s": armed_requirement,
        "trip_events": trips,
        "reconnect_events": reconnects,
        "reconnects": bool(reconnects) and not stays,
        "stays_tripped_reason": reason,
        "cycles": sum(1 for tr in trips if not tr["escalated"]) > 1,
        "initial_power_pu": pref,
        # A cessation that a stage trip took over: it reconnects on the stage path, not TBLK/RAMPAMC.
        "escalated": any(tr["escalated"] for tr in trips),
    }


def simulate_perc2_dll_response(cons, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                                recovery_voltage_pu=1.0):
    """Voltage steps to `fault_voltage_pu` at FAULT_START, holds for `fault_duration_s`, returns to
    `recovery_voltage_pu`."""
    p = perc1_equivalent(cons)
    if not mc_active(cons):
        return simulate_perc1_response(p, fault_duration_s, fault_voltage_pu, recovery_voltage_pu)
    return _voltage_response({k: (float(v) if not isinstance(v, str) else v) for k, v in p.items()},
                             fault_duration_s, fault_voltage_pu, recovery_voltage_pu)


def simulate_perc2_dll_frequency_response(cons, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                          fault_frequency_hz=FREQUENCY_EVENT_HZ,
                                          recovery_frequency_hz=NOMINAL_FREQUENCY_HZ):
    """A held frequency (the voltage stays at 1.0 pu, so momentary cessation never acts). The DLL measures frequency
    against 60 Hz whatever ICON(M) says."""
    return simulate_perc1_frequency_response(perc1_equivalent(cons), fault_duration_s, fault_frequency_hz,
                                             recovery_frequency_hz)
