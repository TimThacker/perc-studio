"""PERC2 in the live preview (`preview_model`, `preview_page`) and on the report page (`perc2_preview`): every active
cease point is checked against the preset, a frequency cease never comes back, and a load that cycles shows every
cycle."""

import pytest

from load_models import get_load_model
from presets.ridethrough import RIDE_THROUGH_PRESETS
from preview.model import (
    Event,
    build_preview,
    frequency_stage_rows,
    perc2_frequency_points,
    perc2_voltage_points,
    voltage_stage_rows,
)
from preview.page import (
    disturbance_figure,
    disturbance_header,
    perc2_fired_points,
    power_figure,
    voltage_thresholds,
)
from preview.perc2 import (
    build_perc2_live_update_js,
    build_perc2_response_figure,
    render_perc2_response_page,
)

MODEL = get_load_model("perc2_standard")
ERCOT = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
PJM = RIDE_THROUGH_PRESETS["pjm_lcl"]


def _cons(preset=ERCOT, **over):
    return {**MODEL.cons_for_preset(preset, "it"), **over}


def test_active_points_skip_point_3_disabled_flags_and_repeats():
    cons = _cons()
    names = [p[3] for p in perc2_voltage_points(cons)]
    assert "VLC3" not in names and "VHC3" not in names
    assert {"VLcease", "VLC1", "VLC2", "VLC4", "VHC1", "VHC2"} <= set(names)
    assert len(perc2_voltage_points(cons)) == len({(p[0], p[1], p[2]) for p in perc2_voltage_points(cons)})
    assert perc2_voltage_points(_cons(VLLflag=0, VLHflag=0, VLMflag=0, VHMflag=0)) == []
    assert [p[3] for p in perc2_frequency_points(_cons(FHflag=0))] == ["FLC1"]


def test_the_preset_mapping_meets_its_own_envelope():
    for preset in (ERCOT, PJM, RIDE_THROUGH_PRESETS["nerc_prc029"]):
        rows = voltage_stage_rows("perc2_standard", _cons(preset), preset)
        assert rows == [("Undervoltage", True), ("Overvoltage", True)], preset.id
    rows = voltage_stage_rows("perc2_standard", _cons(VLC1=0.95, TVLC1=0.5), ERCOT)
    assert rows[0] == ("Undervoltage", False)  # ceasing at 0.95 pu after 0.5 s is inside ERCOT's ride-through region
    assert [ok for _label, ok in frequency_stage_rows("perc2_standard", _cons(PJM), PJM.frequency_ride_through)] == [True, True]


def test_voltage_preview_ceases_and_reconnects():
    result = build_preview("perc2_standard", _cons(), Event("voltage", 3.0, 0.5), preset=ERCOT, block_mw=100.0)
    assert result.trips and "cease" in result.detail.lower() and "reconnects" in result.detail
    assert result.standard.pill == "Both stages OK"
    names = [name for name, _level in voltage_thresholds(result)[0]]
    assert "VLC1" in names
    power_figure(result)


def test_frequency_preview_says_the_cease_is_permanent():
    result = build_preview("perc2_standard", _cons(), Event("frequency", 120.0, frequency_hz=57.5), preset=PJM)
    assert result.trips and "never reconnects" in result.detail
    assert result.tile_text() == "Trips · stays off"
    off = build_preview("perc2_standard", _cons(FLflag=0, FHflag=0), Event("frequency", 120.0, frequency_hz=57.5))
    assert not off.trips and "only droop" in off.detail


def test_a_sag_inside_the_reconnect_window_cycles():
    cons = _cons(VLrecon=0.7)  # below VLC1 0.9 / VLC2 0.8
    result = build_preview("perc2_standard", cons, Event("voltage", 8.0, 0.85))
    assert result.sim["cycles"] and "cycles" in result.detail
    ceased = [s for s in result.timeline if s.state == "ceased"]
    assert len(ceased) == len(result.sim["trip_events"]) >= 2


def test_report_figure_overlays_every_active_point():
    cons = _cons()
    fig = build_perc2_response_figure(cons, "IT", ERCOT.envelope, ERCOT.label, ERCOT.overvoltage_envelope)
    loci = [t for t in fig.data if t.name == "This model ceases here"]
    assert len(loci) == len(perc2_voltage_points(cons))
    title = next(a.text for a in fig.layout.annotations if a.text.startswith("Voltage vs."))
    assert "NOT OK" not in title and "VLC1 OK" in title


def test_report_frequency_panel_shows_the_permanent_cease():
    fig = build_perc2_response_figure(_cons(PJM), "IT", PJM.envelope, PJM.label, PJM.overvoltage_envelope,
                                      frequency_ride_through=PJM.frequency_ride_through, event_kind="frequency",
                                      fault_duration_s=400.0, fault_frequency_hz=58.5)
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "A frequency cease never reconnects" in texts and "Frequency vs." in texts


@pytest.mark.parametrize("duration, voltage, word", [(3.0, 0.5, ">TRIPS<"), (0.05, 0.5, "RIDES THROUGH"),
                                                     (3.0, 1.25, ">TRIPS<")])
def test_report_page_heading(duration, voltage, word):
    page = render_perc2_response_page(_cons(), "IT", preset=ERCOT, fault_duration_s=duration, fault_voltage_pu=voltage)
    status = page.split('id="event-status"')[1].split("</div>")[0]
    assert word in status
    assert 'id="recovery-panel"' in page


def test_report_page_for_a_cycling_load_and_the_live_update():
    cons = _cons(VLrecon=0.7)
    page = render_perc2_response_page(cons, "IT", preset=ERCOT, fault_duration_s=8.0, fault_voltage_pu=0.85)
    assert "cycles" in page and "times" in page
    js = build_perc2_live_update_js(cons, "IT", preset=ERCOT, fault_duration_s=8.0, fault_voltage_pu=0.85)
    assert js.startswith("(function(){") and "Plotly.react" in js


def test_a_live_point_3_is_timed_by_point_1_as_in_psse():
    points = perc2_voltage_points(_cons(VLC3=0.6, TVLC3=9.0))
    point3 = next(p for p in points if p[3] == "VLC3")
    assert point3[4] == "TVLC1" and point3[1] == _cons()["TVLC1"]


def test_the_voltage_card_draws_each_cease_point_as_a_timer_bar():
    """A red bar per cease point, from the event start and as long as its delay, in place of full-width trip lines;
    no labels on the plot (the details are in each bar's hover), and the reconnect line stays."""
    result = build_preview("perc2_standard", _cons(), Event("voltage", 200 / 60, 0.5), preset=ERCOT)
    fired = perc2_fired_points(result)
    assert list(fired) == [(0.8, 0.5, "under")]  # VLC2: 0.5 pu is not below VLC4's 0.50
    assert fired[(0.8, 0.5, "under")] == pytest.approx(1.008, abs=0.01)

    fig = disturbance_figure(result)
    points = perc2_voltage_points(result.params)
    bars = [tr for tr in fig.data if tr.name != "Voltage"]
    assert len(bars) == len(points)
    start = result.sim["fault_start"]
    for bar, (v, d, *_rest) in zip(bars, points, strict=True):
        assert set(bar.y) == {v} and bar.x[0] == start and bar.x[-1] == pytest.approx(start + d)
    hlines = [s for s in fig.layout.shapes if s.y0 == s.y1 and s.xref != "x"]
    assert [round(s.y0, 2) for s in hlines] == [0.95]  # only the reconnect line is full width
    assert not any("VLC" in (a.text or "") for a in fig.layout.annotations)  # no labels on the bars
    hovers = [bar.hovertemplate for bar in bars]
    assert sum("Ceased the load at" in h for h in hovers) == 1
    assert any("<b>VLC2</b>" in h and "Below 0.80 pu" in h and "Ceased the load at" in h for h in hovers)

    _title, legend = disturbance_header(result)
    assert "Trip thresholds" in legend and "Reconnect VLrecon 0.95" in legend and "VHC2" not in legend


def test_a_ride_through_names_no_cease():
    result = build_preview("perc2_standard", _cons(), Event("voltage", 5 / 60, 0.3), preset=ERCOT)
    assert not result.trips and perc2_fired_points(result) == {}
    assert not any("Ceased the load" in (tr.hovertemplate or "") for tr in disturbance_figure(result).data)
