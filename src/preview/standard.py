"""The response chart for the PERC1 standard model (PSS/E 36.7 PERCxx1U), laid out like the DLL
variant's so the two read the same way:

    [ disturbance over time ] [ voltage tolerance map   ]
    [ power over time       ] [ frequency tolerance map ]

with the same heading ("TRIPS" / "RIDES THROUGH") and recovery strip above and below it. The model
is smaller than the DLL's, and the chart shows exactly what it has:

- **Voltage tolerance:** the preset's whole two-sided ride-through envelope, with the model's one trip
  locus overlaid - the model ceases when the voltage stays below Vcease for Tcease, so the region
  below Vcease and right of Tcease is shaded and its corner is the verdict marker (green when that
  corner sits inside the region the standard allows a trip in). The model has no overvoltage trip, so
  the overvoltage side of the envelope is drawn but marked as not modelled.
- **Frequency tolerance:** the preset's frequency table and the droop deadband (dbfl..dbfh). The model
  has no frequency trip, so the verdict is "not modelled"; only droop responds.

The response comes from the analytic simulator `load_models.perc1_standard.simulation`. The page template (figure
layout, heading, recovery strip, live update) is `preview.frame.ResponsePage`; this module supplies this model's panels.
"""

from __future__ import annotations

from html import escape

import plotly.graph_objects as go

from editor.model_ui import STANDARD_MODEL_ID
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

# --- panels -------------------------------------------------------------------------

def _disturbance_panel(fig, sim, params, event_kind, row=1, col=1):
    fig.update_xaxes(range=[0, sim["sim_end"]], row=row, col=col)
    if event_kind == "frequency":
        f_points = sim["f_points"]
        low = NOMINAL_FREQUENCY_HZ * (1 + params["dbfl"])
        high = NOMINAL_FREQUENCY_HZ * (1 + params["dbfh"])
        lo = min([f for _, f in f_points] + [NOMINAL_FREQUENCY_HZ - 2.0]) - 0.5
        hi = max([f for _, f in f_points] + [NOMINAL_FREQUENCY_HZ + 2.0]) + 0.5
        fig.add_hrect(y0=lo, y1=hi, fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=row, col=col)
        if high > low:
            fig.add_hrect(y0=low, y1=high, fillcolor=PLOT_DEADBAND_COLOR, opacity=0.12, line_width=0, row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in f_points], y=[f for _, f in f_points], mode="lines",
                                 line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Frequency (Hz)",
                                 hovertemplate="%{y:.2f} Hz at %{x:.1f}s<extra></extra>"), row=row, col=col)
        chip(fig, f"No frequency trip in this model · droop deadband {band_text(low, high)}", 0.99, 0.93, row, col,
              color=PLOT_DEADBAND_COLOR)
        fig.update_yaxes(title_text="Frequency (Hz)", range=[lo, hi], row=row, col=col)
        return
    v_points = sim["v_points"]
    vcease, vrecon = params["Vcease"], max(params["Vrecon"], params["Vcease"])
    v_max = max(max(v for _, v in v_points), 1.0, vrecon + 0.3) + 0.05
    fig.add_hrect(y0=0, y1=vcease, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=row, col=col)
    fig.add_hrect(y0=vcease, y1=v_max, fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in v_points], y=[v for _, v in v_points], mode="lines",
                             line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Voltage (pu)",
                             hovertemplate="%{y:.2f} pu at %{x:.3f}s<extra></extra>"), row=row, col=col)
    fig.add_hline(y=vcease, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=row, col=col)
    fig.add_hline(y=vrecon, line_dash="dash", line_color=PLOT_RECONNECT_COLOR, row=row, col=col)
    chip(fig, f"Cease · Vcease {vcease:.2f}", 0.99, 0.25, row, col, color=PLOT_TRIP_COLOR)
    chip(fig, f"Reconnect · Vrecon {vrecon:.2f}", 0.99, 0.10, row, col, color=PLOT_RECONNECT_COLOR)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, v_max], row=row, col=col)


def _voltage_tolerance_panel(fig, params, envelope, overvoltage_envelope, preset_name, event, row=1, col=2):
    """The preset's envelope with the model's trip locus overlaid. Returns the verdict rows for the title."""
    vcease, tcease = params["Vcease"], max(params["Tcease"], 0.0)
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
    vmax = max(1.4, max(v for _, v in over_points) + 0.25)
    breakpoints = [s.min_duration_s for s in envelope if s.min_duration_s is not None]
    breakpoints += [s.min_duration_s for s in (overvoltage_envelope or []) if s.min_duration_s is not None]
    breakpoints += [tcease] + ([event[0]] if event else [])
    xmax = max(2.5, max(breakpoints) * 1.25)
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
    region_label(fig, "Overvoltage: not modelled", 0.02, 0.97, row, col, NOT_MODELLED_COLOR, "top")

    # The model's trip locus: it ceases once V stays below Vcease for Tcease - the shaded corner region.
    fig.add_trace(go.Scatter(x=[tcease, xmax, xmax, tcease, tcease], y=[0, 0, vcease, vcease, 0], mode="lines",
                             line={"color": PLOT_TRIP_COLOR, "width": 2, "dash": "dash"}, fill="toself",
                             fillcolor="rgba(201,98,42,0.28)", name="This model ceases here",
                             hovertemplate=f"Ceases when V &lt; {vcease:.2f} pu for {tcease:.3f}s<extra></extra>"),
                  row=row, col=col)
    bound = envelope_bound(under_segments, tcease)
    ok = vcease <= bound
    verdict = (f"tripping here is permitted ({preset_name}: {bound:.2f} pu by {tcease:.3f}s)." if ok else
               f"NOT acceptable - {preset_name} requires riding through down to {bound:.2f} pu at {tcease:.3f}s.")
    stage_marker(fig, tcease, vcease, ok, "circle", "This model's cease point",
                  f"<b>Cease: Vcease={vcease:.2f} pu @ Tcease={tcease:.3f}s</b><br>{verdict}", row, col)
    if event:
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} pu held {event[0]:.3f}s",
                          row, col, (0, vmax))
    fig.update_xaxes(type="linear", range=[0, xmax], title_text="Duration (s)", row=row, col=col)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, vmax], row=row, col=col)
    return [("●", "Undervoltage cease", ok)]


def _frequency_tolerance_panel(fig, params, table, preset_name, event, row=2, col=2):
    """The preset's frequency table and this model's droop deadband. There is no frequency trip to overlay."""
    low = NOMINAL_FREQUENCY_HZ * (1 + params["dbfl"])
    high = NOMINAL_FREQUENCY_HZ * (1 + params["dbfh"])
    durations, levels = [], [low, high]
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
                                 legendgroup=group,
                                 hovertemplate=f"{preset_name}: ride through down to %{{y:.2f}} Hz for "
                                               f"%{{x:.0f}}s<extra></extra>"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[f for _, f in ceiling], mode="lines",
                                 line={"color": "#3a4552", "width": 2.2}, fill="tonexty",
                                 fillcolor="rgba(26,122,60,0.14)", name=f"{preset_name} frequency boundary",
                                 legendgroup=group,
                                 hovertemplate=f"{preset_name}: ride through up to %{{y:.2f}} Hz for "
                                               f"%{{x:.0f}}s<extra></extra>"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[y_hi] * len(ceiling), mode="lines", line={"width": 0},
                                 fill="tonexty", fillcolor="rgba(192,57,43,0.18)", legendgroup=group,
                                 hoverinfo="skip"), row=row, col=col)
        region_label(fig, "Must ride through", 0.02, 0.50, row, col, PLOT_RECONNECT_COLOR, "middle")
        region_label(fig, "Trip permitted (under-frequency)", 0.02, 0.03, row, col, PLOT_TRIP_COLOR, "bottom")
        region_label(fig, "Trip permitted (over-frequency)", 0.02, 0.97, row, col, PLOT_TRIP_COLOR, "top")
    else:
        fig.add_hline(y=NOMINAL_FREQUENCY_HZ, line_color=PLOT_GRID_COLOR, line_width=1.5, row=row, col=col)
        chip(fig, f"{preset_name or 'No preset selected'}: no published frequency table", 0.02, 0.97, row, col,
              xanchor="left", yanchor="top", color=PLOT_AXIS_TEXT)
    if high > low:
        fig.add_hrect(y0=low, y1=high, fillcolor=PLOT_DEADBAND_COLOR, opacity=0.14, line_width=0, row=row, col=col)
    fig.add_annotation(text=f"<b>Droop deadband {band_text(low, high)}</b>", xref="x domain", yref="y", x=0.98,
                       y=NOMINAL_FREQUENCY_HZ, xanchor="right", yanchor="middle", showarrow=False, row=row, col=col,
                       font={"color": PLOT_DEADBAND_COLOR, "size": 11}, bgcolor="rgba(255,255,255,0.85)")
    chip(fig, "No frequency trip in this model", 0.98, 0.30, row, col, color=NOT_MODELLED_COLOR)
    if event:
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} Hz held {event[0]:.0f}s", row, col,
                          (y_lo, y_hi))
    fig.update_xaxes(type="linear", range=[0, xmax], title_text="Duration (s)", row=row, col=col)
    fig.update_yaxes(title_text="Frequency (Hz)", range=[y_lo, y_hi], row=row, col=col)


# --- heading, strip, page ------------------------------------------------------------

def event_status_html(sim: dict, params: dict) -> str:
    markers = sim["markers"]
    if sim["trips"]:
        verdict, color = "TRIPS", PLOT_TRIP_COLOR
        detail = (f"undervoltage cease at {format_seconds(markers['trip_time'])}; reconnects "
                  f"{format_seconds(markers['reconnect_start'])}-{format_seconds(markers['reconnect_end'])}")
    else:
        verdict, color = "RIDES THROUGH", PLOT_RECONNECT_COLOR
        if sim["event_kind"] == "frequency":
            detail = "this model has no frequency trip; only droop responds"
        elif sim["fault_voltage_pu"] > 1.0:
            detail = "this model has no overvoltage trip"
        elif sim.get("armed_required_delay_s") is not None and sim["fault_voltage_pu"] < params["Vcease"]:
            detail = f"would cease only if held {format_seconds(sim['armed_required_delay_s'])}"
        else:
            detail = "this level is above Vcease"
    if sim.get("psse_nan_hazard"):
        detail += " · PSS/E 36.7.1 would return NaN for this event (see the notes)"
    return f'<span style="color:{color};font-weight:700;">{verdict}</span> <span style="color:{PLOT_AXIS_TEXT};">{escape(detail)}</span>'


def recovery_panel_html(params, block_label, sim, block_mw=None, event_kind="voltage") -> str:
    fcease, frecon = params["fcease"], params["frecon"]
    quantity = "frequency" if event_kind == "frequency" else "voltage"

    def mw_label(fraction):
        return f"{fraction * 100:.0f}%" if block_mw is None else f"{fraction * block_mw:.2f} MW ({fraction * 100:.0f}%)"

    if not sim["trips"]:
        return (f'<div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;background:#e5f5ea;'
                f'border:1px solid #a6dfb8;border-radius:6px;padding:5px 10px;color:{PLOT_RECONNECT_COLOR};font-size:12px;'
                f'font-weight:bold;">{escape(block_label)}: rides through - no trip at the simulated {quantity} event.</div>')
    m, sim_end = sim["markers"], sim["sim_end"]

    def pct(t):
        return max(0.0, min(100.0, 100.0 * t / sim_end))

    online, tripped = pct(m["trip_time"]), pct(m["reconnect_start"]) - pct(m["trip_time"])
    ramping, recovered = pct(m["reconnect_end"]) - pct(m["reconnect_start"]), 100.0 - pct(m["reconnect_end"])
    bar = "".join([
        f'<div style="width:{online:.2f}%;background:{PLOT_RECONNECT_COLOR};"></div>',
        f'<div style="width:{tripped:.2f}%;background:{PLOT_TRIP_COLOR};"></div>',
        f'<div style="width:{ramping:.2f}%;background:{PLOT_RAMP_COLOR};"></div>',
        f'<div style="width:{recovered:.2f}%;background:{PLOT_RECONNECT_COLOR};opacity:0.55;"></div>'])
    stat = 'style="white-space:nowrap;"'
    return (f'<div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:12px;">'
            f'<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:3px;">{bar}</div>'
            f'<div style="display:flex;gap:4px 14px;flex-wrap:wrap;color:{PLOT_AXIS_TEXT};">'
            f'<span {stat}>Load ceased <b style="color:{PLOT_TRIP_COLOR}">{mw_label(fcease)}</b></span>'
            f'<span {stat}>Reconnects <b style="color:{PLOT_RECONNECT_COLOR}">{mw_label(frecon * fcease)}</b></span>'
            f'<span {stat}>Ramp time <b style="color:{PLOT_RAMP_COLOR}">{format_seconds(m["reconnect_end"] - m["reconnect_start"])}</b>, '
            f'{format_seconds(m["reconnect_start"] - sim["fault_end"])} after {quantity} recovers</span></div></div>')


def simulate_standard(params: dict, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, event_kind="voltage",
                      fault_frequency_hz=FREQUENCY_EVENT_HZ) -> dict:
    return simulate_model(STANDARD_MODEL_ID, params, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)


def _annotate(fig, voltage_verdict, _frequency_verdicts, preset_name, envelope_label, frequency_ride_through):
    if voltage_verdict:
        title = f"Voltage vs. {preset_name}"
        rows = "  ".join(f'<span style="color:{PLOT_RECONNECT_COLOR if ok else PLOT_TRIP_COLOR}">{glyph} '
                         f'{"OK" if ok else "NOT OK"}</span>' for glyph, _label, ok in voltage_verdict)
        set_subplot_title(fig, 1, f'{title}  {rows}  <span style="color:{NOT_MODELLED_COLOR}">◆ not modelled</span>',
                           f"<b>{envelope_label}</b><br>The model has one undervoltage cease point; overvoltage is not modelled.")
    if frequency_ride_through is not None:
        set_subplot_title(fig, 3, f'Frequency vs. {preset_name}  <span style="color:{NOT_MODELLED_COLOR}">not modelled</span>',
                           "The model has no frequency trip; only droop responds to frequency.")


PAGE = ResponsePage(
    model_id=STANDARD_MODEL_ID, frequency_title="Frequency deadband", disturbance_panel=_disturbance_panel,
    voltage_panel=_voltage_tolerance_panel, frequency_panel=_frequency_tolerance_panel, annotate=_annotate,
    status_html=event_status_html, recovery_html=recovery_panel_html)

build_standard_response_figure = PAGE.figure
render_standard_response_page = PAGE.render
build_standard_live_update_js = PAGE.live_update
