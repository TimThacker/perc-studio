"""The live preview's chart page: three cards under the verdict strip.

    [ Voltage at the load bus      ] [ Power output + state strip ]
    [ Voltage vs. standard: chart  |  result pill, sentence, legend ]

For a frequency event the first card shows the frequency at the bus with the block's
deadband, and the wide card compares the event with the preset's frequency table (or
says there is none). Every figure is built from one `preview.model.PreviewResult`.

Qt-free: the page is plain HTML that loads the plotly.js shipped with the `plotly`
package (never a CDN). `live_update_js` pushes a new result into a page that is already
loaded, through `Plotly.react` (keeps the viewer's zoom) and a few DOM updates.

The 2x2 figure in `preview.perc1_dll.build_perc1_response_figure` is left as it was: the HTML
report still uses it.
"""

from __future__ import annotations

import json
from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import tokens as t
from app.resources import resource_path
from editor.model_ui import PERC2_MODEL_ID, uses_standard_names
from load_models.base import NOMINAL_FREQUENCY_HZ
from load_models.perc1_dll.cons import OVERFREQUENCY_TRIP_CONS, UNDERFREQUENCY_TRIP_CONS
from load_models.perc1_dll.simulation import (
    OVERVOLTAGE_STAGE_CONS,
    UNDERVOLTAGE_STAGE_CONS,
)
from load_models.perc2_standard.cons import long_time_point
from presets.envelope import (
    envelope_bound,
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
    segments_to_points,
)
from preview.model import (
    CEASED,
    ONLINE,
    RECONNECTING,
    PreviewResult,
    ceased_label,
    fmt_seconds,
    perc2_frequency_points,
    perc2_voltage_points,
)

PLOT_IDS = ("plot-v", "plot-p", "plot-s")
STATE_COLORS = {ONLINE: t.STATE_ONLINE, CEASED: t.STATE_CEASED, RECONNECTING: t.STATE_RECONNECTING}
STATE_NAMES = {ONLINE: "Online", CEASED: "Ceased", RECONNECTING: "Reconnecting"}
_AXIS = {"gridcolor": t.HAIRLINE, "linecolor": t.CARD_BORDER, "zeroline": False,
         "tickfont": {"family": t.CSS_FONT_MONO, "size": 10, "color": t.TEXT_MUTED}, "title_standoff": 4}


def _base_layout(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        autosize=True, showlegend=False, plot_bgcolor=t.SURFACE, paper_bgcolor=t.SURFACE,
        margin={"l": 44, "r": 12, "t": 8, "b": 30},
        font={"family": t.CSS_FONT_SANS, "color": t.TEXT, "size": 11}, hovermode="closest",
    )
    fig.update_xaxes(**_AXIS)
    fig.update_yaxes(**_AXIS)
    return fig


def _dll(result: PreviewResult) -> bool:
    return not uses_standard_names(result.model_id)


def _perc2(result: PreviewResult) -> bool:
    return result.model_id == PERC2_MODEL_ID


def _event_marks(fig: go.Figure, result: PreviewResult, rows=None) -> None:
    """Dotted verticals at the trip and the reconnect window (`rows` for a subplot figure)."""
    m = result.sim.get("markers", {})
    if result.trips:
        for key, color in (("trip_time", t.TRIP), ("reconnect_start", t.RECONNECT), ("reconnect_end", t.RECONNECT)):
            if key in m:
                for r in rows or (None,):
                    where = {} if r is None else {"row": r, "col": 1}
                    fig.add_vline(x=m[key], line_dash="dot", line_color=color, line_width=1.2, **where)


# --- card 1: the disturbance ---------------------------------------------------------------------------


def disturbance_figure(result: PreviewResult) -> go.Figure:
    sim = result.sim
    fig = go.Figure()
    end = sim["sim_end"]
    fig.update_xaxes(range=[0, end], ticksuffix=" s")
    if result.event.kind == "frequency":
        points = sim["f_points"]
        low, high = frequency_band(result)
        levels = [f for _, f in points] + [low, high]
        lo = min(levels + [NOMINAL_FREQUENCY_HZ - 2.0]) - 0.5
        hi = max(levels + [NOMINAL_FREQUENCY_HZ + 2.0]) + 0.5
        if high > low:
            fig.add_hrect(y0=low, y1=high, fillcolor=t.DEADBAND, line_width=0, layer="below")
            for edge in (low, high):
                fig.add_hline(y=edge, line_dash="dash", line_color=t.PARTNER_BLUE, line_width=1.2)
        fig.add_trace(go.Scatter(x=[x for x, _ in points], y=[f for _, f in points], mode="lines",
                                 line={"color": t.PLOT_VOLTAGE, "width": 2.2}, name="Frequency",
                                 hovertemplate="%{y:.2f} Hz at %{x:.1f} s<extra></extra>"))
        fig.update_yaxes(range=[lo, hi], ticksuffix=" Hz")
    else:
        points = sim["v_points"]
        trip_levels, reconnect = voltage_thresholds(result)
        top = max([v for _, v in points] + [lvl for _n, lvl in trip_levels] + [1.0, reconnect[1]]) + 0.15
        if _perc2(result):
            _perc2_timer_bars(fig, result)
        else:
            for _name, level in trip_levels:
                fig.add_hline(y=level, line_dash="dash", line_color=t.TRIP, line_width=1.2)
        fig.add_hline(y=reconnect[1], line_dash="dash", line_color=t.RECONNECT, line_width=1.2)
        fig.add_trace(go.Scatter(x=[x for x, _ in points], y=[v for _, v in points], mode="lines",
                                 line={"color": t.PLOT_VOLTAGE, "width": 2.2}, name="Voltage",
                                 hovertemplate="%{y:.2f} pu at %{x:.3f} s<extra></extra>"))
        fig.update_yaxes(range=[0, top])
        fig.add_annotation(text=f"{result.event.voltage_pu:.2f} pu · {result.event.duration_s:.2f} s",
                           x=sim["fault_start"], y=result.event.voltage_pu, xanchor="left", yanchor="top",
                           xshift=4, showarrow=False, font={"size": 10, "color": t.TEXT_MUTED})
        m = sim.get("markers", {})
        if result.trips and "reconnect_start" in m:
            fig.add_annotation(text=f"reconnect {fmt_seconds(m['reconnect_start'])}", x=m["reconnect_start"],
                               y=0, yref="y", xanchor="left", yanchor="bottom", xshift=4, yshift=4,
                               showarrow=False, font={"size": 10, "color": t.TEXT_MUTED})
    _event_marks(fig, result)
    return _base_layout(fig)


def perc2_fired_points(result: PreviewResult) -> dict[tuple[float, float, str], float]:
    """{(voltage, delay, "under"|"over"): first cease time} for each PERC2 voltage cease point that ceased the load in
    this event, keyed like `perc2_voltage_points` (which merges repeated points) rather than by check name."""
    p = result.params
    fired: dict[tuple[float, float, str], float] = {}
    for event in result.sim.get("trip_events", []):
        name = event["check"]
        if name in ("VLM", "VHM"):
            key = (p["VLcease" if name == "VLM" else "VHcease"], max(p["Tcease"], 0.0), "under" if name == "VLM" else "over")
        elif name[:3] in ("VLC", "VHC") and name[3:].isdigit():
            prefix = name[1]
            key = (p[name], max(p[f"TV{prefix}C{long_time_point(int(name[3:]))}"], 0.0), "under" if prefix == "L" else "over")
        else:
            continue  # a frequency cease
        fired.setdefault(key, event["time"])
    return fired


def _perc2_timer_bars(fig: go.Figure, result: PreviewResult) -> None:
    """PERC2's voltage cease points as timer bars: each a red bar at its level, from the event start and as long as its
    delay, so the trace shows whose timer runs out first. The point that ceased the load is solid, the points this
    event's voltage arms are half strength and the rest faint; hovering a bar gives its details."""
    start, level = result.sim["fault_start"], result.event.voltage_pu
    fired = perc2_fired_points(result)
    for v, d, side, name, dname in perc2_voltage_points(result.params):
        when = fired.get((v, d, side))
        armed = level < v if side == "under" else level > v
        opacity = 1.0 if when is not None else 0.55 if armed else 0.3
        status = (f"Ceased the load at {fmt_seconds(when)}" if when is not None
                  else "Armed by this event" if armed else "Not reached by this event")
        hover = (f"<b>{name}</b> trip threshold<br>{'Below' if side == 'under' else 'Above'} {v:.2f} pu "
                 f"for {fmt_seconds(d)} ({dname})<br>{status}<extra></extra>")
        if d > 0:
            # Points along the whole bar, so hovering anywhere on it shows the details.
            xs = [start + d * i / 24 for i in range(25)]
            fig.add_trace(go.Scatter(x=xs, y=[v] * len(xs), mode="lines", opacity=opacity, showlegend=False,
                                     line={"color": t.TRIP, "width": 4}, hovertemplate=hover))
        else:  # no delay: a mark at the event start
            fig.add_trace(go.Scatter(x=[start], y=[v], mode="markers", opacity=opacity, showlegend=False,
                                     marker={"color": t.TRIP, "size": 6, "symbol": "square"}, hovertemplate=hover))


def voltage_thresholds(result: PreviewResult) -> tuple[list[tuple[str, float]], tuple[str, float]]:
    """([(name, level)] of the trip thresholds drawn, (name, level) of the reconnect threshold)."""
    p = result.params
    if _dll(result):
        return [("VDUA", p["VDUA"]), ("VDPA", p["VDPA"])], ("VRPA", p["VRPA"])
    if _perc2(result):
        levels: dict[float, str] = {}
        for v, _d, _side, name, _dname in perc2_voltage_points(p):
            levels.setdefault(v, name)
        return [(name, v) for v, name in levels.items()], ("VLrecon", max(p["VLrecon"], p["VLcease"]))
    return [("Vcease", p["Vcease"])], ("Vrecon", max(p["Vrecon"], p["Vcease"]))


def frequency_band(result: PreviewResult) -> tuple[float, float]:
    p = result.params
    if _dll(result):
        return p[UNDERFREQUENCY_TRIP_CONS[0]], p[OVERFREQUENCY_TRIP_CONS[0]]
    return NOMINAL_FREQUENCY_HZ * (1 + p["dbfl"]), NOMINAL_FREQUENCY_HZ * (1 + p["dbfh"])


def _swatch(color: str, dash: bool = False, bar: bool = False) -> str:
    if bar:
        style = f"background:{color};height:4px;border-radius:2px;"
    else:
        style = f"border-top:2px dashed {color};" if dash else f"background:{color};height:10px;"
    return f'<i class="sw" style="{style}"></i>'


def disturbance_header(result: PreviewResult) -> tuple[str, str]:
    """(card title, legend HTML) for card 1."""
    if result.event.kind == "frequency":
        low, high = frequency_band(result)
        if _dll(result):
            delay = max(result.params[UNDERFREQUENCY_TRIP_CONS[1]], result.params[OVERFREQUENCY_TRIP_CONS[1]])
            text = f"Deadband {low:.1f}–{high:.1f} Hz · trips after {fmt_seconds(delay)} outside the band"
        else:
            text = f"Droop deadband {low:.2f}–{high:.2f} Hz · no frequency trip in this model"
        return "Frequency at the load bus", f'<span>{_swatch(t.DEADBAND)}{escape(text)}</span>'
    trips, (rname, rlevel) = voltage_thresholds(result)
    if _perc2(result):
        return "Voltage at the load bus", (
            f'<span>{_swatch(t.TRIP, bar=True)}Trip thresholds</span>'
            f'<span>{_swatch(t.RECONNECT, dash=True)}Reconnect {rname} {rlevel:.2f}</span>')
    trip_text = " · ".join(f"{name} {level:.2f}" for name, level in trips)
    return "Voltage at the load bus", (
        f'<span>{_swatch(t.TRIP, dash=True)}Trip {escape(trip_text)}</span>'
        f'<span>{_swatch(t.RECONNECT, dash=True)}Reconnect {rname} {rlevel:.2f}</span>')


# --- card 2: power and the state strip --------------------------------------------------------------------


def power_figure(result: PreviewResult) -> go.Figure:
    sim = result.sim
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.86, 0.14], vertical_spacing=0.07)
    points = sim["p_points"]
    fig.add_trace(go.Scatter(x=[x for x, _ in points], y=[v for _, v in points], mode="lines",
                             line={"color": t.PLOT_POWER, "width": 2.2}, name="P",
                             hovertemplate="%{y:.2f} of block MW at %{x:.2f} s<extra></extra>"), row=1, col=1)
    top = max([v for _, v in points] + [1.0]) + 0.1
    fig.update_yaxes(range=[0, top], row=1, col=1)
    fig.update_yaxes(range=[0, 1], visible=False, fixedrange=True, row=2, col=1)
    fig.update_xaxes(showgrid=False, row=2, col=1)
    fig.update_xaxes(range=[0, sim["sim_end"]], showticklabels=False, row=1, col=1)
    fig.update_xaxes(range=[0, sim["sim_end"]], ticksuffix=" s", row=2, col=1)
    _event_marks(fig, result, rows=(1,))
    m = sim.get("markers", {})
    if result.trips:
        fig.add_annotation(text=f"trip {fmt_seconds(m['trip_time'])}", x=m["trip_time"], y=0, xanchor="left",
                           yanchor="bottom", xshift=4, yshift=6, showarrow=False,
                           font={"size": 10, "color": t.TEXT_MUTED}, row=1, col=1)
        if "reconnect_start" in m and m["reconnect_end"] > m["reconnect_start"]:
            mid = (m["reconnect_start"] + m["reconnect_end"]) / 2
            fig.add_annotation(text=f"{fmt_seconds(m['reconnect_end'] - m['reconnect_start'])} ramp", x=mid,
                               y=0.5 * top, showarrow=False, font={"size": 10, "color": t.TEXT_MUTED},
                               bgcolor="rgba(255,255,255,0.8)", row=1, col=1)
    span = max(sim["sim_end"], 1e-9)
    for seg in result.timeline:
        fig.add_shape(type="rect", x0=seg.t0, x1=seg.t1, y0=0, y1=1, fillcolor=STATE_COLORS[seg.state],
                      line_width=0, layer="below", row=2, col=1)
        if (seg.t1 - seg.t0) / span >= 0.08:
            label = ceased_label(seg, result.model_id) if seg.state == CEASED else STATE_NAMES[seg.state]
            if (seg.t1 - seg.t0) / span < 0.22 and seg.state == CEASED:
                label = f"Ceased · {seg.fraction * 100:.0f} %"
            fig.add_annotation(text=label, x=(seg.t0 + seg.t1) / 2, y=0.5, showarrow=False,
                               font={"size": 10, "color": t.TEXT}, row=2, col=1)
    fig = _base_layout(fig)
    fig.update_layout(margin={"l": 44, "r": 12, "t": 8, "b": 26})
    return fig


def power_header() -> tuple[str, str]:
    legend = (f'<span>{_swatch(t.PLOT_POWER, dash=False).replace("height:10px", "height:2px")}P</span>'
              + "".join(f'<span>{_swatch(STATE_COLORS[s])}{STATE_NAMES[s]}</span>'
                        for s in (ONLINE, CEASED, RECONNECTING)))
    return 'Power output <span class="sub">(fraction of block MW)</span>', legend


# --- card 3: against the standard -----------------------------------------------------------------------


def standard_figure(result: PreviewResult, preset) -> go.Figure:
    fig = go.Figure()
    if result.event.kind == "frequency":
        _frequency_standard(fig, result, preset)
    else:
        _voltage_standard(fig, result, preset)
    return _base_layout(fig)


def _note(fig: go.Figure, text: str) -> None:
    fig.add_annotation(text=text, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                       font={"size": 12, "color": t.TEXT_MUTED})
    fig.update_xaxes(range=[0, 1], visible=False)
    fig.update_yaxes(range=[0, 1], visible=False)


def _event_marker(fig: go.Figure, x: float, y: float, hover: str) -> None:
    fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers+text", text=["this event"], textposition="middle right",
                             textfont={"size": 11, "color": t.TEXT},
                             marker={"symbol": "x-thin", "size": 12, "color": t.TEXT, "line": {"width": 2.5, "color": t.TEXT}},
                             hovertemplate=f"{hover}<extra></extra>", name="This event"))


def _stage_marker(fig: go.Figure, x: float, y: float, ok: bool | None, symbol: str, hover: str) -> None:
    color = t.PARTNER_BLUE if ok is None else (t.BRAND if ok else t.TRIP)
    fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers", hovertemplate=f"{hover}<extra></extra>",
                             marker={"size": 10, "color": color, "symbol": symbol, "line": {"color": "white", "width": 1.5}}))


def _voltage_standard(fig: go.Figure, result: PreviewResult, preset) -> None:
    if preset is None:
        _note(fig, "Choose a ride-through preset to compare this block against.")
        return
    p = result.params
    under = envelope_segments_from_steps(preset.envelope)
    over = overvoltage_segments_from_steps(preset.overvoltage_envelope or [])
    if _dll(result):
        stages = ([(p[v], p[d], "under", v, d) for v, d in UNDERVOLTAGE_STAGE_CONS]
                  + [(p[v], p[d], "over", v, d) for v, d in OVERVOLTAGE_STAGE_CONS])
    elif _perc2(result):
        stages = perc2_voltage_points(p)
    else:
        stages = [(p["Vcease"], max(p["Tcease"], 0.0), "under", "Vcease", "Tcease")]
    breaks = [s.min_duration_s for s in [*preset.envelope, *(preset.overvoltage_envelope or [])]
              if s.min_duration_s is not None] + [d for _v, d, *_r in stages] + [result.event.duration_s]
    xmax = max(2.5, max(breaks) * 1.25)
    upper = segments_to_points([(a, min(b, xmax), v) for a, b, v in over if a < xmax])
    lower = segments_to_points([(a, min(b, xmax), v) for a, b, v in under if a < xmax])
    vmax = max(1.4, max(v for _, v in upper) + 0.2, max((v for v, *_r in stages), default=1.0) + 0.15)
    fig.add_shape(type="rect", x0=0, x1=xmax, y0=0, y1=vmax, fillcolor=t.TRIP_TINT, line_width=0, layer="below")
    xs = [x for x, _ in lower] + [x for x, _ in reversed(upper)]
    ys = [y for _, y in lower] + [y for _, y in reversed(upper)]
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor=t.NO_DAMAGE, mode="lines", line={"width": 0},
                             hoverinfo="skip", name="No damage expected"))
    for pts, hover in ((lower, "min"), (upper, "max")):
        fig.add_trace(go.Scatter(x=[x for x, _ in pts], y=[y for _, y in pts], mode="lines",
                                 line={"color": t.TEXT, "width": 1.6}, name=preset.label,
                                 hovertemplate=f"{escape(preset.label)}: {hover} %{{y:.2f}} pu at %{{x:.3f}} s<extra></extra>"))
    for v, d, direction, vn, dn in stages:
        segs = under if direction == "under" else over
        bound = envelope_bound(segs, d)
        ok = v <= bound if direction == "under" else v >= bound
        _stage_marker(fig, d, v, ok, "circle" if direction == "under" else "diamond",
                      f"{vn} {v:.2f} pu at {dn} {d:.3f} s: " + ("trip permitted here" if ok else "inside the ride-through region"))
    _event_marker(fig, result.event.duration_s, result.event.voltage_pu,
                  f"This event: {result.event.voltage_pu:.2f} pu for {result.event.duration_s:.3f} s")
    fig.update_xaxes(range=[0, xmax], ticksuffix=" s")
    fig.update_yaxes(range=[0, vmax])


def _frequency_standard(fig: go.Figure, result: PreviewResult, preset) -> None:
    table = preset.frequency_ride_through if preset is not None else None
    if preset is None:
        _note(fig, "Choose a ride-through preset to compare this block against.")
        return
    if table is None:
        _note(fig, f"{preset.label} has no published frequency table.")
        return
    low, high = frequency_band(result)
    durations = [b.min_duration_s for b in (*table.underfrequency, *table.overfrequency)] + [result.event.duration_s]
    xmax = max(450.0, max(durations) * 1.25)
    levels = [b.limit_hz for b in (*table.underfrequency, *table.overfrequency)] + [low, high, result.event.frequency_hz]
    y_lo = min([NOMINAL_FREQUENCY_HZ - 3.0] + [f - 0.8 for f in levels])
    y_hi = max([NOMINAL_FREQUENCY_HZ + 3.0] + [f + 0.8 for f in levels])
    floor = segments_to_points(table.segments("under", xmax))
    ceiling = segments_to_points(table.segments("over", xmax))
    fig.add_shape(type="rect", x0=0, x1=xmax, y0=y_lo, y1=y_hi, fillcolor=t.TRIP_TINT, line_width=0, layer="below")
    xs = [x for x, _ in floor] + [x for x, _ in reversed(ceiling)]
    ys = [y for _, y in floor] + [y for _, y in reversed(ceiling)]
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor=t.NO_DAMAGE, mode="lines", line={"width": 0},
                             hoverinfo="skip"))
    for pts in (floor, ceiling):
        fig.add_trace(go.Scatter(x=[x for x, _ in pts], y=[y for _, y in pts], mode="lines",
                                 line={"color": t.TEXT, "width": 1.6}, hoverinfo="skip"))
    if high > low:
        fig.add_hrect(y0=low, y1=high, fillcolor=t.DEADBAND, opacity=0.6, line_width=0)
    if _dll(result):
        p = result.params
        for (f_name, d_name), direction, symbol in ((UNDERFREQUENCY_TRIP_CONS, "under", "circle"),
                                                    (OVERFREQUENCY_TRIP_CONS, "over", "diamond")):
            f, d = p[f_name], p[d_name]
            bound = table.bound(direction, d)
            ok = f <= bound if direction == "under" else f >= bound
            _stage_marker(fig, d, f, ok, symbol, f"{f_name} {f:.2f} Hz at {d_name} {d:.0f} s")
    elif _perc2(result):
        for f, d, direction, f_name, d_name in perc2_frequency_points(result.params):
            bound = table.bound(direction, d)
            ok = f <= bound if direction == "under" else f >= bound
            _stage_marker(fig, d, f, ok, "circle" if direction == "under" else "diamond",
                          f"{f_name} {f:.2f} Hz at {d_name} {d:.0f} s (ceases for good)")
    _event_marker(fig, result.event.duration_s, result.event.frequency_hz,
                  f"This event: {result.event.frequency_hz:.2f} Hz for {result.event.duration_s:.0f} s")
    fig.update_xaxes(range=[0, xmax], ticksuffix=" s")
    fig.update_yaxes(range=[y_lo, y_hi], ticksuffix=" Hz")


def standard_info_html(result: PreviewResult) -> str:
    check = result.standard
    parts = []
    if check.pill:
        cls = "ok" if check.pill_ok else ("bad" if check.pill_ok is False else "neutral")
        parts.append(f'<div class="pill {cls}" id="std-pill">{escape(check.pill)}</div>')
    parts.append(f'<p class="sentence">{escape(check.sentence)}</p>')
    if check.available:
        ride = "Must ride through" if result.event.kind == "frequency" else "No damage expected"
        parts.append(f'<div class="legend-col"><span>{_swatch(t.NO_DAMAGE)}{ride}</span>'
                     f'<span>{_swatch(t.TRIP_TINT)}Trip permitted</span></div>')
    return "".join(parts)


def standard_title(result: PreviewResult) -> str:
    return "Frequency vs. standard" if result.event.kind == "frequency" else "Voltage vs. standard"


# --- the page -----------------------------------------------------------------------------------------


def figures(result: PreviewResult, preset) -> dict[str, go.Figure]:
    return {"plot-v": disturbance_figure(result), "plot-p": power_figure(result),
            "plot-s": standard_figure(result, preset)}


def _parts(result: PreviewResult) -> dict[str, str]:
    title_v, legend_v = disturbance_header(result)
    title_p, legend_p = power_header()
    return {"title-v": escape(title_v), "legend-v": legend_v, "title-p": title_p, "legend-p": legend_p,
            "title-s": escape(standard_title(result)), "info-s": standard_info_html(result)}


def _font_face() -> str:
    faces = []
    for family, weight, name in ((t.FONT_SANS, 400, "IBMPlexSans-Regular.ttf"), (t.FONT_SANS, 500, "IBMPlexSans-Medium.ttf"),
                                 (t.FONT_SANS, 600, "IBMPlexSans-SemiBold.ttf"), (t.FONT_MONO, 400, "IBMPlexMono-Regular.ttf")):
        path = resource_path("assets", "fonts", name)
        if path.is_file():
            faces.append(f"@font-face {{ font-family: '{family}'; font-weight: {weight}; src: url('{path.as_uri()}'); }}")
    return "\n".join(faces)


PAGE_CSS = f"""
html, body {{ margin: 0; padding: 0; height: 100%; background: {t.GROUND}; overflow: hidden;
              font-family: {t.CSS_FONT_SANS}; color: {t.TEXT}; font-size: 13px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: {t.GUTTER}px;
         height: 100vh; box-sizing: border-box; }}
.card {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CARD}px;
         display: flex; flex-direction: column; min-height: 0; min-width: 0; padding: 12px 14px 8px; box-sizing: border-box; }}
.card.wide {{ grid-column: 1 / span 2; }}
.head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; margin-bottom: 4px; }}
.title {{ font-weight: 600; font-size: 13px; }}
.title .sub {{ font-weight: 400; color: {t.TEXT_MUTED}; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px 12px; color: {t.TEXT_MUTED}; font-size: 11px; margin-left: auto; }}
.sw {{ display: inline-block; width: 14px; margin-right: 5px; vertical-align: middle; border-radius: 2px; }}
.plot {{ flex: 1 1 auto; min-height: 0; }}
.wide-body {{ display: flex; flex: 1 1 auto; min-height: 0; gap: 18px; }}
.wide-body .plot {{ flex: 1.6 1 0; }}
.info {{ flex: 1 1 0; display: flex; flex-direction: column; justify-content: center; gap: 10px; padding-right: 8px; }}
.pill {{ align-self: flex-start; border-radius: {t.RADIUS_TAG}px; padding: 3px 10px; font-weight: 600; font-size: 13px; }}
.pill.ok {{ background: {t.BRAND_TINT}; color: {t.BRAND_DARK}; }}
.pill.bad {{ background: {t.TRIP_TINT}; color: {t.TRIP_TEXT}; }}
.pill.neutral {{ background: {t.HAIRLINE}; color: {t.TEXT_MUTED}; }}
.sentence {{ margin: 0; line-height: 1.45; }}
.legend-col {{ display: flex; flex-direction: column; gap: 6px; color: {t.TEXT_MUTED}; font-size: 12px; }}
"""


def render_page(result: PreviewResult, preset, *, plotly_src: str = "plotly.min.js") -> str:
    figs = figures(result, preset)
    parts = _parts(result)
    data = {key: json.loads(fig.to_json()) for key, fig in figs.items()}
    config = {"responsive": True, "displaylogo": False, "displayModeBar": False}
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>{_font_face()}
{PAGE_CSS}</style>
<script src="{plotly_src}"></script>
</head><body>
<div class="grid">
  <div class="card"><div class="head"><span class="title" id="title-v">{parts['title-v']}</span>
    <span class="legend" id="legend-v">{parts['legend-v']}</span></div><div class="plot" id="plot-v"></div></div>
  <div class="card"><div class="head"><span class="title" id="title-p">{parts['title-p']}</span>
    <span class="legend" id="legend-p">{parts['legend-p']}</span></div><div class="plot" id="plot-p"></div></div>
  <div class="card wide"><div class="head"><span class="title" id="title-s">{parts['title-s']}</span></div>
    <div class="wide-body"><div class="plot" id="plot-s"></div><div class="info" id="info-s">{parts['info-s']}</div></div></div>
</div>
<script>
var CONFIG = {json.dumps(config)};
var FIGS = {json.dumps(data)};
Object.keys(FIGS).forEach(function (id) {{ Plotly.newPlot(id, FIGS[id].data, FIGS[id].layout, CONFIG); }});
new ResizeObserver(function () {{
  {json.dumps(list(PLOT_IDS))}.forEach(function (id) {{
    var el = document.getElementById(id); if (el && window.Plotly) {{ Plotly.Plots.resize(el); }}
  }});
}}).observe(document.querySelector(".grid"));
</script>
</body></html>"""


def live_update_js(result: PreviewResult, preset) -> str:
    """Push a new result into a loaded page: one `Plotly.react` per plot, then the text parts."""
    figs = figures(result, preset)
    lines = ["(function(){"]
    for key, fig in figs.items():
        lines.append(f"var f = {fig.to_json()}; Plotly.react({json.dumps(key)}, f.data, f.layout);")
    for element_id, html in _parts(result).items():
        lines.append(f"var e = document.getElementById({json.dumps(element_id)}); "
                     f"if (e) {{ e.innerHTML = {json.dumps(html)}; }}")
    lines.append("})();")
    return "\n".join(lines)
