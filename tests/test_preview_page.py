"""The live chart page: three cards, the state strip, and an in-place update that touches every plot."""

import json

import pytest

from app import tokens as t
from editor.model_ui import (
    DLL_MODEL_ID,
    PERC2_DLL_MODEL_ID,
    STANDARD_MODEL_ID,
    get_ui_spec,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS
from preview.model import Event, build_preview
from preview.page import (
    PLOT_IDS,
    disturbance_figure,
    disturbance_header,
    live_update_js,
    power_figure,
    render_page,
    standard_figure,
    voltage_cease_points,
)

ITIC = RIDE_THROUGH_PRESETS["standard_itic"]


SAG = Event("voltage", 5 / 60, 0.30)


def result(model_id=DLL_MODEL_ID, event=SAG, preset=ITIC):
    params = get_ui_spec(model_id).preset_params(preset or ITIC, "it")
    return build_preview(model_id, params, event, preset=preset, block_mw=50.0)


@pytest.mark.parametrize("model_id", [DLL_MODEL_ID, STANDARD_MODEL_ID])
@pytest.mark.parametrize("event", [Event("voltage", 5 / 60, 0.30), Event("frequency", 60, frequency_hz=58.5)])
def test_the_page_has_three_plots_and_loads_local_plotly(model_id, event):
    html = render_page(result(model_id, event), ITIC, plotly_src="plotly.min.js")
    for plot_id in PLOT_IDS:
        assert f'id="{plot_id}"' in html
    assert '<script src="plotly.min.js"></script>' in html
    assert "cdn" not in html.lower()


def test_live_update_reacts_every_plot_and_the_text():
    js = live_update_js(result(), ITIC)
    for plot_id in PLOT_IDS:
        assert f'Plotly.react("{plot_id}"' in js
    for element in ("legend-v", "title-s", "info-s"):
        assert f'"{element}"' in js
    assert "Both stages OK" in js


def test_the_voltage_card_names_its_thresholds():
    title, legend = disturbance_header(result())
    assert title == "Voltage at the load bus"
    assert "Trip thresholds" in legend and "VDPA" not in legend
    assert "Reconnect VRPA 0.90" in legend


ERCOT = RIDE_THROUGH_PRESETS["ercot_nogrr282"]


@pytest.mark.parametrize("model_id", [DLL_MODEL_ID, PERC2_DLL_MODEL_ID])
def test_the_dll_voltage_card_draws_every_stage_as_a_timer_bar(model_id):
    """All 4 stages per direction, repeats merged, each a bar as long as its delay plus CMTDELAY; the stage that
    tripped the load says so in its hover, and only the reconnect line is full width."""
    params = {**get_ui_spec(model_id).preset_params(ERCOT, "it"), "CMTDELAY": 0.05}
    res = build_preview(model_id, params, Event("voltage", 200 / 60, 0.5), preset=ERCOT)
    points = voltage_cease_points(res)
    assert [p.name for p in points] == ["VDPA", "VDPA1", "VDPA2", "VDPA3", "VDUA", "VDUA1"]
    assert [p.name for p in points if p.fired_at is not None] == ["VDPA1"]  # 0.5 pu is not below VDPA2's 0.50

    fig = disturbance_figure(res)
    bars = [tr for tr in fig.data if tr.name != "Voltage"]
    assert len(bars) == len(points)
    start = res.sim["fault_start"]
    for bar, p in zip(bars, points, strict=True):
        assert set(bar.y) == {p.voltage} and bar.x[0] == start
        assert bar.x[-1] == pytest.approx(start + params[p.name.replace("VDPA", "DMA").replace("VDUA", "TDUA")] + 0.05)
    hlines = [s for s in fig.layout.shapes if s.y0 == s.y1 and s.xref != "x"]
    assert [round(s.y0, 2) for s in hlines] == [round(params["VRPA"], 2)]
    hovers = [bar.hovertemplate for bar in bars]
    assert sum("Tripped the load at" in h for h in hovers) == 1
    assert any("<b>VDPA1</b>" in h and "Below 0.80 pu for 0.50 s (DMA1) + 0.05 s (CMTDELAY)" in h for h in hovers)


def test_perc2_dll_momentary_cessation_has_its_own_marks():
    params = {**get_ui_spec(PERC2_DLL_MODEL_ID).preset_params(ITIC, "it"), "MCFLAG": 1}
    res = build_preview(PERC2_DLL_MODEL_ID, params, Event("voltage", 200 / 60, 0.3), preset=ITIC)
    vlblk = next(p for p in voltage_cease_points(res) if p.name == "VLBLK")
    assert vlblk.length == 0 and vlblk.fired_at == pytest.approx(res.sim["trip_events"][0]["time"])
    assert any("<b>VLBLK</b>" in (tr.hovertemplate or "") and "Ceased the load at" in tr.hovertemplate
               for tr in disturbance_figure(res).data)
    off = build_preview(PERC2_DLL_MODEL_ID, {**params, "MCFLAG": 0}, Event("voltage", 200 / 60, 0.3), preset=ITIC)
    assert "VLBLK" not in [p.name for p in voltage_cease_points(off)]


def test_the_frequency_card_shows_the_deadband():
    title, legend = disturbance_header(result(event=Event("frequency", 60, frequency_hz=58.5)))
    assert title == "Frequency at the load bus"
    assert "Deadband 58.0–62.0 Hz · trips after 100 s outside the band" in legend


def test_the_state_strip_is_drawn_under_the_power_trace():
    fig = power_figure(result())
    fills = [s.fillcolor for s in fig.layout.shapes if s.type == "rect"]
    assert fills == [t.STATE_ONLINE, t.STATE_CEASED, t.STATE_RECONNECTING, t.STATE_ONLINE]
    labels = [a.text for a in fig.layout.annotations]
    assert "Ceased · 100 % (FCEASE 1.00)" in labels and "Reconnecting" in labels


def test_the_standard_card_without_a_preset_or_table_is_a_note():
    fig = standard_figure(result(preset=None), None)
    assert [a.text for a in fig.layout.annotations] == ["Choose a ride-through preset to compare this block against."]
    ercot = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    fig = standard_figure(result(event=Event("frequency", 60, frequency_hz=58.5), preset=ercot), ercot)
    assert "has no published frequency table" in fig.layout.annotations[0].text


def test_the_standard_card_marks_the_event():
    fig = standard_figure(result(), ITIC)
    names = [trace.name for trace in fig.data]
    assert "This event" in names and "No damage expected" in names
    event = next(trace for trace in fig.data if trace.name == "This event")
    assert (event.x[0], event.y[0]) == pytest.approx((5 / 60, 0.30))
    json.loads(fig.to_json())  # serialisable for the page
