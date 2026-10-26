"""The response chart for the PERC2 standard model (PSS/E 36.7 PERCxx2U), laid out like the PERC1 standard
model's (`preview.standard`) so the three PERC pages read the same way:

    [ disturbance over time ] [ voltage tolerance map   ]
    [ power over time       ] [ frequency tolerance map ]

PERC2 has more to show than PERC1 standard:

- **Voltage tolerance:** every active cease point - the momentary checks (VLcease/VHcease after Tcease) and the
  long-table points of both directions (point 3 timed by TVLC1/TVHC1, as PSS/E 36.7.1 does) - is overlaid on the preset's two-sided
  envelope as its own shaded corner, with a verdict marker (green where the standard permits a cease there).
- **Frequency tolerance:** the preset's frequency table with the FLC1/FHC1 points overlaid, and a note that a
  frequency cease never reconnects.
- **Power:** a load that cycles (ceases, reconnects inside a sag, ceases again) shows every cycle.

The response comes from the analytic simulator `load_models.perc2_standard.simulation`. The page template (figure
layout, heading, recovery strip, live update) is `preview.frame.ResponsePage`; this module supplies this model's panels.
"""

from __future__ import annotations

from html import escape

import plotly.graph_objects as go

from editor.model_ui import PERC2_MODEL_ID
from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from presets.envelope import (
    envelope_bound,
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
    segments_to_points,
)
from preview.frame import NOT_MODELLED_COLOR, ResponsePage, band_text, simulate_model
from preview.model import perc2_frequency_points, perc2_voltage_points
from preview.style import (
    PLOT_AXIS_TEXT,
    PLOT_DEADBAND_COLOR,
    PLOT_GRID_COLOR,
    PLOT_RAMP_COLOR,
    PLOT_RECONNECT_COLOR,
    PLOT_TRIP_COLOR,
    PLOT_VOLTAGE_COLOR,
    add_event_marker,
    chip,
    format_seconds,
    region_label,
    set_subplot_title,
    stage_marker,
)


def _cease_text(points) -> str:
    return " · ".join(f"{name} {level:.2f}" for level, _d, _side, name, _dn in points) or "none active"


# --- panels -------------------------------------------------------------------------

def _disturbance_panel(fig, sim, params, event_kind, row=1, col=1):
    fig.update_xaxes(range=[0, sim["sim_end"]], row=row, col=col)
    if event_kind == "frequency":
        f_points = sim["f_points"]
        low = NOMINAL_FREQUENCY_HZ * (1 + params["dbfl"])
        high = NOMINAL_FREQUENCY_HZ * (1 + params["dbfh"])
        ceases = perc2_frequency_points(params)
        levels = [f for _, f in f_points] + [f for f, *_r in ceases]
        lo = min(levels + [NOMINAL_FREQUENCY_HZ - 2.0]) - 0.5
        hi = max(levels + [NOMINAL_FREQUENCY_HZ + 2.0]) + 0.5
        if high > low:
            fig.add_hrect(y0=low, y1=high, fillcolor=PLOT_DEADBAND_COLOR, opacity=0.12, line_width=0, row=row, col=col)
        for f, *_r in ceases:
            fig.add_hline(y=f, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in f_points], y=[f for _, f in f_points], mode="lines",
                                 line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Frequency (Hz)",
                                 hovertemplate="%{y:.2f} Hz at %{x:.1f}s<extra></extra>"), row=row, col=col)
        chip(fig, f"Ceases for good: {_cease_text(ceases)} · droop deadband {band_text(low, high)}", 0.99, 0.93, row,
              col, color=PLOT_TRIP_COLOR if ceases else PLOT_DEADBAND_COLOR)
        fig.update_yaxes(title_text="Frequency (Hz)", range=[lo, hi], row=row, col=col)
        return
    v_points = sim["v_points"]
    points = perc2_voltage_points(params)
    vlrecon = max(params["VLrecon"], params["VLcease"])
    vhrecon = min(params["VHrecon"], params["VHcease"])
    v_max = max([v for _, v in v_points] + [v for v, *_r in points] + [1.0, min(vhrecon, 1.6)]) + 0.15
    fig.add_hrect(y0=vlrecon, y1=min(vhrecon, v_max), fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=row,
                  col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in v_points], y=[v for _, v in v_points], mode="lines",
                             line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Voltage (pu)",
                             hovertemplate="%{y:.2f} pu at %{x:.3f}s<extra></extra>"), row=row, col=col)
    for level in sorted({v for v, *_r in points}):
        fig.add_hline(y=level, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=row, col=col)
    for level in (vlrecon, vhrecon):
        if level < v_max:
            fig.add_hline(y=level, line_dash="dot", line_color=PLOT_RECONNECT_COLOR, row=row, col=col)
    chip(fig, f"Cease · {_cease_text(points)}", 0.99, 0.25, row, col, color=PLOT_TRIP_COLOR)
    chip(fig, f"Reconnect window {vlrecon:.2f}-{vhrecon:.2f} pu", 0.99, 0.10, row, col, color=PLOT_RECONNECT_COLOR)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, v_max], row=row, col=col)


def _extra_cycle_marks(fig, sim, col=1):
    """Every cease and ramp after the first (a load that cycles), as dotted lines on both left panels."""
    for event in sim.get("trip_events", [])[1:]:
        for r in (1, 2):
            fig.add_vline(x=event["time"], line_dash="dot", line_color=PLOT_TRIP_COLOR, row=r, col=col)
    for event in sim.get("reconnect_events", [])[1:]:
        for r in (1, 2):
            fig.add_vline(x=event["start"], line_dash="dot", line_color=PLOT_RECONNECT_COLOR, row=r, col=col)


def _voltage_tolerance_panel(fig, params, envelope, overvoltage_envelope, preset_name, event, row=1, col=2):
    """The preset's envelope with every active cease point overlaid. Returns the verdict rows for the title."""
    points = perc2_voltage_points(params)
    if not envelope:
        fig.add_annotation(text="Select a ride-through preset to compare this block against.", xref="x domain",
                           yref="y domain", x=0.5, y=0.5, xanchor="center", yanchor="middle", showarrow=False,
                           row=row, col=col, font={"color": PLOT_AXIS_TEXT, "size": 11})
        fig.update_xaxes(range=[0, 1], title_text="Duration (s)", showticklabels=False, row=row, col=col)
        fig.update_yaxes(range=[0, 1], title_text="Voltage (pu)", showticklabels=False, row=row, col=col)
        return None
    under_segments = envelope_segments_from_steps(envelope)
    over_segments = overvoltage_segments_from_steps(overvoltage_envelope or [])
    under_points = segments_to_points(under_segments)
    over_points = segments_to_points(over_segments)
    vmax = max(1.4, max(v for _, v in over_points) + 0.25, max((v + 0.1 for v, *_r in points), default=0.0))
    breakpoints = [s.min_duration_s for s in envelope if s.min_duration_s is not None]
    breakpoints += [s.min_duration_s for s in (overvoltage_envelope or []) if s.min_duration_s is not None]
    breakpoints += [d for _v, d, *_r in points] + ([event[0]] if event else [])
    xmax = max(2.5, max(breakpoints, default=0.0) * 1.25)
    group = "voltage-envelope"
    fig.add_trace(go.Scatter(x=[t for t, _ in under_points], y=[v for _, v in under_points], mode="lines",
                             line={"width": 0}, fill="tozeroy", fillcolor="rgba(192,57,43,0.18)", legendgroup=group,
                             hoverinfo="skip"), row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in under_points], y=[v for _, v in under_points], mode="lines",
                             line={"color": "#3a4552", "width": 2.2}, name=f"{preset_name} boundary", legendgroup=group,
                             hovertemplate=f"{preset_name}: min %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>"),
                  row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in over_points], y=[v for _, v in over_points], mode="lines",
                             line={"color": "#3a4552", "width": 2.2}, fill="tonexty", fillcolor="rgba(26,122,60,0.14)",
                             name=f"{preset_name} boundary", legendgroup=group,
                             hovertemplate=f"{preset_name}: max %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>"),
                  row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in over_points], y=[vmax] * len(over_points), mode="lines",
                             line={"width": 0}, fill="tonexty", fillcolor="rgba(192,57,43,0.18)", legendgroup=group,
                             hoverinfo="skip"), row=row, col=col)
    region_label(fig, "No damage expected", 0.02, 0.60, row, col, PLOT_RECONNECT_COLOR, "middle")
    region_label(fig, "Trip permitted (undervoltage)", 0.02, 0.03, row, col, PLOT_TRIP_COLOR, "bottom")
    region_label(fig, "Trip permitted (overvoltage)", 0.02, 0.97, row, col, PLOT_TRIP_COLOR, "top")

    verdicts = []
    for v, d, side, vname, dname in points:
        # The model ceases once V stays beyond the point for its time: a shaded corner region per point.
        y_edge = 0.0 if side == "under" else vmax
        fig.add_trace(go.Scatter(x=[d, xmax, xmax, d, d], y=[y_edge, y_edge, v, v, y_edge], mode="lines",
                                 line={"color": PLOT_TRIP_COLOR, "width": 1.5, "dash": "dash"}, fill="toself",
                                 fillcolor="rgba(201,98,42,0.16)", name="This model ceases here",
                                 hovertemplate=(f"Ceases when V {'&lt;' if side == 'under' else '&gt;'} {v:.2f} pu "
                                                f"for {d:.3f}s ({vname}/{dname})<extra></extra>")),
                      row=row, col=col)
        segments = under_segments if side == "under" else over_segments
        bound = envelope_bound(segments, d)
        ok = v <= bound if side == "under" else v >= bound
        verdict = (f"ceasing here is permitted ({preset_name}: {bound:.2f} pu at {d:.3f}s)." if ok else
                   f"NOT acceptable - {preset_name} requires riding through to {bound:.2f} pu at {d:.3f}s.")
        glyph = "●" if side == "under" else "◆"
        stage_marker(fig, d, v, ok, "circle" if side == "under" else "diamond", f"{vname}/{dname}",
                      f"<b>{vname}={v:.2f} pu @ {dname}={d:.3f}s</b><br>{verdict}", row, col)
        verdicts.append((glyph, f"{vname}", ok))
    if event:
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} pu held {event[0]:.3f}s",
                          row, col, (0, vmax))
    fig.update_xaxes(type="linear", range=[0, xmax], title_text="Duration (s)", row=row, col=col)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, vmax], row=row, col=col)
    return verdicts


def _frequency_tolerance_panel(fig, params, table, preset_name, event, row=2, col=2):
    """The preset's frequency table with the FLC1/FHC1 cease points. Returns the verdict rows for the title."""
    points = perc2_frequency_points(params)
    low = NOMINAL_FREQUENCY_HZ * (1 + params["dbfl"])
    high = NOMINAL_FREQUENCY_HZ * (1 + params["dbfh"])
    durations, levels = [d for _f, d, *_r in points], [low, high] + [f for f, *_r in points]
    if table:
        durations += [b.min_duration_s for b in table.underfrequency + table.overfrequency]
        levels += [b.limit_hz for b in table.underfrequency + table.overfrequency]
    if event:
        durations.append(event[0])
        levels.append(event[1])
    xmax = max(450.0, max(durations, default=0.0) * 1.25)
    y_lo = min([NOMINAL_FREQUENCY_HZ - 4.0] + [f - 1.0 for f in levels])
    y_hi = max([NOMINAL_FREQUENCY_HZ + 4.0] + [f + 1.0 for f in levels])
    if table:
        floor = segments_to_points(table.segments("under", xmax))
        ceiling = segments_to_points(table.segments("over", xmax))
        group = "frequency-envelope"
        fig.add_trace(go.Scatter(x=[t for t, _ in floor], y=[f for _, f in floor], mode="lines", line={"width": 0},
                                 fill="tozeroy", fillcolor="rgba(192,57,43,0.18)", legendgroup=group,
                                 hoverinfo="skip"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in floor], y=[f for _, f in floor], mode="lines",
                                 line={"color": "#3a4552", "width": 2.2}, name=f"{preset_name} frequency boundary",
                                 legendgroup=group, hoverinfo="skip"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[f for _, f in ceiling], mode="lines",
                                 line={"color": "#3a4552", "width": 2.2}, fill="tonexty",
                                 fillcolor="rgba(26,122,60,0.14)", name=f"{preset_name} frequency boundary",
                                 legendgroup=group, hoverinfo="skip"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[y_hi] * len(ceiling), mode="lines", line={"width": 0},
                                 fill="tonexty", fillcolor="rgba(192,57,43,0.18)", legendgroup=group,
                                 hoverinfo="skip"), row=row, col=col)
        region_label(fig, "Must ride through", 0.02, 0.50, row, col, PLOT_RECONNECT_COLOR, "middle")
    else:
        fig.add_hline(y=NOMINAL_FREQUENCY_HZ, line_color=PLOT_GRID_COLOR, line_width=1.5, row=row, col=col)
        chip(fig, f"{preset_name or 'No preset selected'}: no published frequency table", 0.02, 0.97, row, col,
              xanchor="left", yanchor="top", color=PLOT_AXIS_TEXT)
    if high > low:
        fig.add_hrect(y0=low, y1=high, fillcolor=PLOT_DEADBAND_COLOR, opacity=0.14, line_width=0, row=row, col=col)
    verdicts = []
    for f, d, side, fname, dname in points:
        ok = None
        if table:
            bound = table.bound(side, d)
            ok = f <= bound if side == "under" else f >= bound
        stage_marker(fig, d, f, bool(ok), "circle" if side == "under" else "diamond", f"{fname}/{dname}",
                      f"<b>{fname}={f:.2f} Hz @ {dname}={d:.0f}s</b><br>ceases for good (never reconnects)", row, col,
                      neutral=ok is None)
        verdicts.append(("●" if side == "under" else "◆", fname, ok))
    chip(fig, "A frequency cease never reconnects" if points else "Frequency cease checks off", 0.98, 0.30, row, col,
          color=PLOT_TRIP_COLOR if points else NOT_MODELLED_COLOR)
    if event:
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} Hz held {event[0]:.0f}s", row, col,
                          (y_lo, y_hi))
    fig.update_xaxes(type="linear", range=[0, xmax], title_text="Duration (s)", row=row, col=col)
    fig.update_yaxes(title_text="Frequency (Hz)", range=[y_lo, y_hi], row=row, col=col)
    return verdicts


def _verdict_spans(verdicts) -> str:
    return "  ".join(f'<span style="color:{PLOT_RECONNECT_COLOR if ok else PLOT_TRIP_COLOR}">{glyph} {escape(name)} '
                     f'{"OK" if ok else "NOT OK"}</span>' for glyph, name, ok in verdicts if ok is not None)


# --- heading, strip, page ------------------------------------------------------------

def event_status_html(sim: dict, params: dict) -> str:
    markers = sim["markers"]
    if sim["trips"]:
        verdict, color = "TRIPS", PLOT_TRIP_COLOR
        detail = f"{sim.get('trip_type') or 'cease'} ({sim.get('cease_check')}) at {format_seconds(markers['trip_time'])}"
        if sim.get("stays_tripped_reason"):
            detail += f"; stays off: {sim['stays_tripped_reason']}"
        elif sim.get("cycles"):
            detail += (f"; cycles: ceases {len(sim['trip_events'])} times (the reconnect window overlaps a cease "
                       "point)")
        elif "reconnect_start" in markers:
            detail += (f"; reconnects {format_seconds(markers['reconnect_start'])}-"
                       f"{format_seconds(markers.get('reconnect_end', sim['sim_end']))}")
    else:
        verdict, color = "RIDES THROUGH", PLOT_RECONNECT_COLOR
        if sim["event_kind"] == "frequency" and not perc2_frequency_points(params):
            detail = "both frequency cease checks are off; only droop responds"
        else:
            detail = "this event does not reach any active cease point"
    return (f'<span style="color:{color};font-weight:700;">{verdict}</span> '
            f'<span style="color:{PLOT_AXIS_TEXT};">{escape(detail)}</span>')


def recovery_panel_html(params, block_label, sim, block_mw=None, event_kind="voltage") -> str:
    fcease, frecon = params["fcease"], params["frecon"]
    quantity = "frequency" if event_kind == "frequency" else "voltage"

    def mw_label(fraction):
        return f"{fraction * 100:.0f}%" if block_mw is None else f"{fraction * block_mw:.2f} MW ({fraction * 100:.0f}%)"

    if not sim["trips"]:
        return (f'<div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;background:#e5f5ea;'
                f'border:1px solid #a6dfb8;border-radius:6px;padding:5px 10px;color:{PLOT_RECONNECT_COLOR};font-size:12px;'
                f'font-weight:bold;">{escape(block_label)}: rides through - no cease at the simulated {quantity} event.</div>')
    sim_end = sim["sim_end"]

    def pct(t):
        return max(0.0, min(100.0, 100.0 * t / sim_end))

    # The bar: online, then for every cycle ceased (red) and ramping (amber), then back online (faded).
    pieces, t = [], 0.0
    reconnects = sim.get("reconnect_events", [])
    for i, trip in enumerate(sim.get("trip_events", [])):
        pieces.append((pct(trip["time"]) - pct(t), PLOT_RECONNECT_COLOR, 1.0 if i == 0 else 0.55))
        if i < len(reconnects):
            pieces.append((pct(reconnects[i]["start"]) - pct(trip["time"]), PLOT_TRIP_COLOR, 1.0))
            pieces.append((pct(reconnects[i]["end"]) - pct(reconnects[i]["start"]), PLOT_RAMP_COLOR, 1.0))
            t = reconnects[i]["end"]
        else:
            pieces.append((100.0 - pct(trip["time"]), PLOT_TRIP_COLOR, 1.0))
            t = sim_end
    if t < sim_end:
        pieces.append((100.0 - pct(t), PLOT_RECONNECT_COLOR, 0.55))
    bar = "".join(f'<div style="width:{max(w, 0.0):.2f}%;background:{c};opacity:{o};"></div>' for w, c, o in pieces)
    stat = 'style="white-space:nowrap;"'
    m = sim["markers"]
    if sim.get("stays_tripped_reason") or "reconnect_start" not in m:
        back = f'<span {stat}>Stays off: <b style="color:{PLOT_TRIP_COLOR}">{escape(sim.get("stays_tripped_reason") or "no reconnect in the run")}</b></span>'
    else:
        back = (f'<span {stat}>Reconnects <b style="color:{PLOT_RECONNECT_COLOR}">{mw_label(frecon * fcease)}</b></span>'
                f'<span {stat}>Ramp time <b style="color:{PLOT_RAMP_COLOR}">'
                f'{format_seconds(m.get("reconnect_end", sim_end) - m["reconnect_start"])}</b>, '
                f'{format_seconds(m["reconnect_start"] - sim["fault_end"])} after {quantity} recovers</span>')
    cycles = (f'<span {stat}>Ceases <b style="color:{PLOT_TRIP_COLOR}">{len(sim["trip_events"])} times</b></span>'
              if sim.get("cycles") else "")
    return (f'<div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:12px;">'
            f'<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:3px;">{bar}</div>'
            f'<div style="display:flex;gap:4px 14px;flex-wrap:wrap;color:{PLOT_AXIS_TEXT};">'
            f'<span {stat}>Load ceased <b style="color:{PLOT_TRIP_COLOR}">{mw_label(fcease)}</b></span>{back}{cycles}'
            f'</div></div>')


def simulate_perc2(params: dict, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, event_kind="voltage",
                   fault_frequency_hz=FREQUENCY_EVENT_HZ) -> dict:
    return simulate_model(PERC2_MODEL_ID, params, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)


def _annotate(fig, voltage_verdicts, frequency_verdicts, preset_name, envelope_label, frequency_ride_through):
    if voltage_verdicts is not None:
        set_subplot_title(fig, 1, f"Voltage vs. {preset_name}  {_verdict_spans(voltage_verdicts)}",
                           f"<b>{envelope_label}</b><br>Every active momentary and long cease point "
                           "(PSS/E 36.7.1 times long point 3 with point 1's time).")
    if frequency_ride_through is not None:
        set_subplot_title(fig, 3, f"Frequency vs. {preset_name}  {_verdict_spans(frequency_verdicts)}",
                           "FLC1/FHC1: a frequency cease never reconnects.")


PAGE = ResponsePage(
    model_id=PERC2_MODEL_ID, frequency_title="Frequency tolerance", disturbance_panel=_disturbance_panel,
    voltage_panel=_voltage_tolerance_panel, frequency_panel=_frequency_tolerance_panel, annotate=_annotate,
    status_html=event_status_html, recovery_html=recovery_panel_html, extra_marks=_extra_cycle_marks)

build_perc2_response_figure = PAGE.figure
render_perc2_response_page = PAGE.render
build_perc2_live_update_js = PAGE.live_update
