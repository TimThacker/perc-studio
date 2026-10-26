"""The standard model's response chart: same layout and heading as the DLL chart, with the model's one
trip locus overlaid on the preset's ride-through envelope."""

from load_models import get_load_model
from presets.ridethrough import RIDE_THROUGH_PRESETS
from preview.standard import (
    build_standard_live_update_js,
    build_standard_response_figure,
    render_standard_response_page,
)

MODEL = get_load_model("perc1_standard")


def _cons(preset_id="ercot_nogrr282", **over):
    return {**MODEL.cons_for_preset(RIDE_THROUGH_PRESETS[preset_id], "it"), **over}


def _figure(preset_id="ercot_nogrr282", cons=None, **kw):
    preset = RIDE_THROUGH_PRESETS[preset_id]
    return build_standard_response_figure(
        cons or _cons(preset_id), "IT", preset.envelope, preset.label, preset.overvoltage_envelope,
        frequency_ride_through=preset.frequency_ride_through, **kw)


def _names(fig):
    return [t.name for t in fig.data if t.name]


def test_the_trip_locus_is_overlaid_on_the_presets_envelope():
    fig = _figure()
    names = _names(fig)
    assert "This model ceases here" in names and "ERCOT boundary" in names
    locus = next(t for t in fig.data if t.name == "This model ceases here")
    cons = _cons()
    assert max(locus.y) == cons["Vcease"] and min(locus.x) == cons["Tcease"]
    titles = [a.text for a in fig.layout.annotations]
    assert any("Voltage vs. ERCOT" in t and "OK" in t for t in titles)


def test_the_verdict_marker_turns_red_when_the_cease_point_is_inside_the_ride_through_region():
    fig = _figure(cons=_cons(Vcease=0.95, Tcease=0.1))
    title = next(a.text for a in fig.layout.annotations if a.text.startswith("Voltage vs."))
    assert "NOT OK" in title


def test_frequency_panel_shows_the_table_and_says_the_model_has_no_frequency_trip():
    fig = _figure("pjm_lcl", event_kind="frequency", fault_duration_s=60.0, fault_frequency_hz=58.0)
    assert "PJM frequency boundary" in _names(fig)
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "No frequency trip in this model" in texts and "not modelled" in texts


def test_heading_says_trips_or_rides_through():
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    trips = render_standard_response_page(_cons(), "IT", preset=preset, fault_duration_s=3.0, fault_voltage_pu=0.3)
    rides = render_standard_response_page(_cons(), "IT", preset=preset, fault_duration_s=0.083, fault_voltage_pu=0.3)
    swell = render_standard_response_page(_cons(), "IT", preset=preset, fault_duration_s=5.0, fault_voltage_pu=1.25)
    assert ">TRIPS<" in trips and "RIDES THROUGH" not in trips.split('id="event-status"')[1].split("</div>")[0]
    assert "RIDES THROUGH" in rides and "would cease only if held" in rides
    assert "no overvoltage trip" in swell
    assert 'id="panel1-title"' in trips and 'id="recovery-panel"' in trips


def test_live_update_script_targets_the_same_element_ids():
    js = build_standard_live_update_js(_cons(), "IT", preset=RIDE_THROUGH_PRESETS["pjm_lcl"], fault_duration_s=1.0,
                                       fault_voltage_pu=0.2)
    for needle in ("Plotly.react", "recovery-panel", "event-status", "panel1-title"):
        assert needle in js


def test_without_a_preset_the_envelope_panel_asks_for_one():
    fig = build_standard_response_figure(_cons(), "IT")
    assert any("Select a ride-through preset" in a.text for a in fig.layout.annotations)


def test_tdelay_edge_case_is_flagged_in_the_heading():
    page = render_standard_response_page(_cons(Tcease=0.1, Tdelay=0.2), "IT", fault_duration_s=0.15, fault_voltage_pu=0.4)
    assert "NaN" in page
