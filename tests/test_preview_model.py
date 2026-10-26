"""The live preview's data: verdict, figures, the online/ceased/reconnecting timeline, and the comparison with
the preset. The design's example: a 5-cycle sag to 0.30 pu on Standard (ITIC/CBEMA) trips at 0.53 s and
reconnects 61-91 s."""

import pytest

from editor.model_ui import DLL_MODEL_ID, STANDARD_MODEL_ID, get_ui_spec
from presets.ridethrough import RIDE_THROUGH_PRESETS
from preview.model import (
    CEASED,
    ONLINE,
    RECONNECTING,
    RIDE_THROUGH_REGION,
    TRIP_PERMITTED_REGION,
    Event,
    build_preview,
    ceased_label,
    state_timeline,
)

ITIC = RIDE_THROUGH_PRESETS["standard_itic"]
SAG = Event("voltage", 5 / 60, 0.30)


def dll_params(preset=ITIC, **overrides):
    return {**get_ui_spec(DLL_MODEL_ID).preset_params(preset, "it"), **overrides}


def test_the_design_example_trips_and_reconnects():
    result = build_preview(DLL_MODEL_ID, dll_params(), SAG, preset=ITIC, block_mw=50.0)
    assert result.verdict == "TRIPS" and result.trips
    assert result.title == "5-cycle sag to 0.30 pu"
    assert result.detail == "Undervoltage trip at 0.53 s · reconnects 61–91 s"
    assert (result.load_tripped, result.reconnects, result.ramp) == ("50.00 MW", "50.00 MW", "30 s")
    assert result.tile_text() == "Trips · back by 91 s"
    states = [s.state for s in result.timeline]
    assert states == [ONLINE, CEASED, RECONNECTING, ONLINE]
    ceased = result.timeline[1]
    assert ceased.t0 == pytest.approx(0.53, abs=0.01) and ceased.fraction == 1.0
    assert ceased_label(ceased) == "Ceased · 100 % (FCEASE 1.00)"


def test_the_design_example_against_the_standard():
    check = build_preview(DLL_MODEL_ID, dll_params(), SAG, preset=ITIC).standard
    assert check.available and check.pill == "Both stages OK" and check.pill_ok
    assert check.region == TRIP_PERMITTED_REGION
    assert check.sentence == "Event at 0.30 pu for 0.083 s falls in the region where tripping is permitted."


def test_a_block_label_prefixes_the_title():
    result = build_preview(DLL_MODEL_ID, dll_params(), SAG, preset=ITIC, block_label="IT / UPS block")
    assert result.title == "IT / UPS block · 5-cycle sag to 0.30 pu"


def test_a_partial_cease_shows_its_fraction():
    result = build_preview(DLL_MODEL_ID, dll_params(FCEASE=0.4), SAG, preset=ITIC, block_mw=50.0)
    ceased = next(s for s in result.timeline if s.state == CEASED)
    assert ceased.fraction == pytest.approx(0.4)
    assert ceased_label(ceased) == "Ceased · 40 % (FCEASE 0.40)"
    assert result.load_tripped == "20.00 MW"


def test_a_ride_through_is_online_all_along():
    result = build_preview(DLL_MODEL_ID, dll_params(), Event("voltage", 1 / 60, 0.9), preset=ITIC, block_mw=50.0)
    assert result.verdict == "RIDES THROUGH"
    assert [s.state for s in result.timeline] == [ONLINE]
    assert (result.load_tripped, result.reconnects, result.ramp) == ("0.00 MW", "–", "–")
    assert result.tile_text() == "Rides through"


def test_a_cycling_block_gives_several_rounds():
    # The reconnect window overlaps the trip stage (VRPA below VDPA): it cycles while the sag holds.
    params = dll_params(VRPA=0.2, TDRA=0.5, RAMPA=0.5)
    result = build_preview(DLL_MODEL_ID, params, Event("voltage", 600 / 60, 0.3), preset=ITIC)
    assert result.sim["cycles"]
    assert sum(1 for s in result.timeline if s.state == CEASED) >= 2
    assert result.tile_text() == "Trips · stays off"


def test_staying_tripped_is_ceased_to_the_end():
    sim = {"trips": True, "sim_end": 10.0, "trip_events": [{"time": 1.0}], "reconnect_events": []}
    timeline = state_timeline(sim, 1.0)
    assert [(s.state, s.t0, s.t1) for s in timeline] == [(ONLINE, 0.0, 1.0), (CEASED, 1.0, 10.0)]


def test_the_standard_models_single_cycle_uses_its_markers():
    params = get_ui_spec(STANDARD_MODEL_ID).preset_params(ITIC, "it")
    result = build_preview(STANDARD_MODEL_ID, params, SAG, preset=ITIC, block_mw=50.0)
    assert result.trips and result.detail.startswith("Undervoltage cease at")
    assert [s.state for s in result.timeline] == [ONLINE, CEASED, RECONNECTING, ONLINE]
    assert ceased_label(result.timeline[1], STANDARD_MODEL_ID).endswith("(fcease 1.00)")
    assert result.standard.stage_rows[1] == ("Overvoltage", None)  # not modelled
    assert result.standard.pill == "Cease point OK"


def test_a_frequency_event_with_no_table_says_so():
    ercot = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    result = build_preview(DLL_MODEL_ID, dll_params(ercot), Event("frequency", 240, frequency_hz=58.8), preset=ercot)
    assert not result.standard.available
    assert result.standard.pill == "No frequency table"
    assert "has no published frequency table" in result.standard.sentence


def test_a_frequency_event_against_a_table():
    pjm = RIDE_THROUGH_PRESETS["pjm_lcl"]
    assert pjm.frequency_ride_through is not None
    result = build_preview(DLL_MODEL_ID, dll_params(pjm), Event("frequency", 5, frequency_hz=59.5), preset=pjm)
    assert result.standard.available and result.standard.region == RIDE_THROUGH_REGION
    assert [label for label, _ok in result.standard.stage_rows] == ["Under-frequency", "Over-frequency"]


def test_without_a_preset_there_is_nothing_to_compare():
    result = build_preview(DLL_MODEL_ID, dll_params(), SAG, preset=None)
    assert not result.standard.available
    assert result.standard.sentence.startswith("Choose a ride-through preset")


def test_a_shortfall_is_called_out():
    """A deep, long sag inside the preset's ride-through region that the block trips on falls short."""
    pjm = RIDE_THROUGH_PRESETS["pjm_lcl"]
    params = dll_params(pjm, VDPA=0.95, DMA=0.01, VDPA1=0.95, DMA1=0.01, VDPA2=0.95, DMA2=0.01, VDPA3=0.95, DMA3=0.01)
    result = build_preview(DLL_MODEL_ID, params, Event("voltage", 6 / 60, 0.9), preset=pjm)
    assert result.trips and result.standard.region == RIDE_THROUGH_REGION
    assert "falls short" in result.standard.sentence
    assert result.standard.pill_ok is False and "Undervoltage" in result.standard.pill
