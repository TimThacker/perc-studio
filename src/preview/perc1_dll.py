"""The PERC1 DLL response figure and page (also the base of the PERC2 DLL page): the 2x2 tolerance charts, the
recovery strip, the report page and the in-place live update."""

from __future__ import annotations

import json

import plotly.graph_objects as go

from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from load_models.perc1_dll.cons import (
    OVERFREQUENCY_TRIP_CONS,
    UNDERFREQUENCY_TRIP_CONS,
)
from load_models.perc1_dll.simulation import (
    OVERVOLTAGE_STAGE_CONS,
    UNDERVOLTAGE_STAGE_CONS,
    simulate_perc1_event,
)
from presets.envelope import (
    envelope_bound,
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
    segments_to_points,
)
from preview.style import (
    PLOT_AXIS_TEXT,
    PLOT_DEADBAND_COLOR,
    PLOT_GRID_COLOR,
    PLOT_POWER_COLOR,
    PLOT_RAMP_COLOR,
    PLOT_RECONNECT_COLOR,
    PLOT_TITLE_TEXT,
    PLOT_TRIP_COLOR,
    PLOT_VOLTAGE_COLOR,
    add_event_marker,
    chip,
    format_seconds,
    panel1_title_text,
    region_label,
    set_subplot_title,
    short_label,
    stage_marker,
)


def event_status(sim):
    """(verdict, color, detail) for the simulated event - shown as a status line
    beside the heading rather than inside a half-width panel, where a sentence
    this long would clip."""
    limited = ""
    if sim.get("initial_power_pu", 1.0) < 1.0 - 1e-9:
        limited = (f"; IPMAXA < LFM, so the block holds only {sim['initial_power_pu']:.2f} pu "
                   f"of its load before the event")
    if sim["trips"]:
        m = sim["markers"]
        detail = f"{sim['trip_type']} trip at {format_seconds(m['trip_time'])}; "
        if sim.get("stays_tripped_reason"):
            detail += f"stays tripped: {sim['stays_tripped_reason']}"
        elif sim.get("cycles"):
            detail += (f"cycles - trips {len(sim['trip_events'])} times, because the reconnect window "
                       f"overlaps a trip stage (VRPA below a stage voltage)")
        else:
            detail += f"reconnects {format_seconds(m['reconnect_start'])}-{format_seconds(m['reconnect_end'])}"
        return ("TRIPS", PLOT_TRIP_COLOR, detail + limited)
    required = sim.get("armed_required_delay_s")
    if required is not None:
        return ("RIDES THROUGH", PLOT_RECONNECT_COLOR,
                f"would trip only if held {format_seconds(required)}" + limited)
    return ("RIDES THROUGH", PLOT_RECONNECT_COLOR, "this level doesn't reach any trip stage" + limited)


def event_status_html(sim):
    verdict, color, detail = event_status(sim)
    return f'<b style="color:{color}">{verdict}</b> <span style="color:{PLOT_AXIS_TEXT}">- {detail}</span>'


def _frequency_trip_point(params, direction):
    """(CON names, frequency, delay) of the block's one trip point in that
    direction - the vendor model has a single frequency stage."""
    trip_name, delay_name = UNDERFREQUENCY_TRIP_CONS if direction == "under" else OVERFREQUENCY_TRIP_CONS
    return trip_name, delay_name, params[trip_name], params[delay_name]


def _point_out_short_event(fig, sim, level, nominal, text, row, col):
    """The timeline spans the whole trip-and-reconnect sequence, which can be
    hundreds of times longer than the event itself (a 5 s frequency event
    followed by a 100 s reconnect delay) - the event then draws as a sliver
    that's easy to miss. Label it with an arrow when it's under 3% of the axis."""
    if sim["fault_duration_s"] >= 0.03 * sim["sim_end"]:
        return
    # The label sits halfway back toward nominal (data coordinates), so it stays
    # inside the plot whether the event is a dip or a spike.
    fig.add_annotation(
        text=text, x=sim["fault_start"], y=level, xref="x", yref="y",
        axref="x", ayref="y", ax=sim["fault_start"] + 0.06 * sim["sim_end"], ay=(level + nominal) / 2,
        showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=PLOT_TITLE_TEXT, xanchor="left",
        font={"color": PLOT_TITLE_TEXT, "size": 10}, bgcolor="rgba(255,255,255,0.88)",
        row=row, col=col,
    )


def _add_disturbance_panel(fig, sim, params, event_kind, row=1, col=1):
    """Top-left: the simulated disturbance over time - bus voltage for a voltage
    event, system frequency for a frequency event (never both on one axis)."""
    # Pinned to the simulated window: autorange padded it below 0 s whenever a
    # marker or label sat near the edge.
    fig.update_xaxes(range=[0, sim["sim_end"]], row=row, col=col)
    if event_kind == "frequency":
        f_points = sim["f_points"]
        uf = _frequency_trip_point(params, "under")
        of = _frequency_trip_point(params, "over")
        levels = [f for _, f in f_points] + [uf[2], of[2]]
        f_lo = min(levels + [NOMINAL_FREQUENCY_HZ - 2.0]) - 0.5
        f_hi = max(levels + [NOMINAL_FREQUENCY_HZ + 2.0]) + 0.5
        uf_f, of_f = uf[2], of[2]
        fig.add_hrect(y0=f_lo, y1=uf_f, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=row, col=col)
        fig.add_hrect(y0=uf_f, y1=of_f, fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=row, col=col)
        fig.add_hrect(y0=of_f, y1=f_hi, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=row, col=col)
        fig.add_trace(
            go.Scatter(x=[t for t, _ in f_points], y=[f for _, f in f_points], mode="lines",
                       line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Frequency (Hz)",
                       hovertemplate="%{y:.2f} Hz at %{x:.1f}s<extra></extra>"),
            row=row, col=col,
        )
        for (_trip_name, _delay_name, freq, delay), label, y in ((of, "Deadband high", 0.88),
                                                                  (uf, "Deadband low", 0.12)):
            fig.add_hline(y=freq, line_dash="dash", line_color=PLOT_DEADBAND_COLOR, row=row, col=col)
            chip(fig, f"{label} {freq:.2f} Hz · trips after {format_seconds(delay)}", 0.99, y,
                  row, col, color=PLOT_DEADBAND_COLOR)
        fig.update_yaxes(title_text="Frequency (Hz)", range=[f_lo, f_hi], row=row, col=col)
        _point_out_short_event(fig, sim, sim["fault_frequency_hz"], NOMINAL_FREQUENCY_HZ,
                               f"{sim['fault_frequency_hz']:.2f} Hz for {format_seconds(sim['fault_duration_s'])}",
                               row, col)
        return

    v_points = sim["v_points"]
    vdpa, vrpa, vdua = params["VDPA"], params["VRPA"], params["VDUA"]
    # Three zones mirroring the voltage tolerance map's two-sided region; the
    # "+0.3 above VRPA" margin keeps the reference lines clear of the panel top.
    v_max = max(max(v for _, v in v_points), vdua, 1.0, vrpa + 0.3, vdua + 0.2) + 0.05
    fig.add_hrect(y0=0, y1=vdpa, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=row, col=col)
    fig.add_hrect(y0=vdpa, y1=vdua, fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=row, col=col)
    fig.add_hrect(y0=vdua, y1=v_max, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=row, col=col)
    fig.add_trace(
        go.Scatter(x=[t for t, _ in v_points], y=[v for _, v in v_points], mode="lines",
                   line={"color": PLOT_VOLTAGE_COLOR, "width": 2.2}, name="Voltage (pu)",
                   hovertemplate="%{y:.2f} pu at %{x:.3f}s<extra></extra>"),
        row=row, col=col,
    )
    fig.add_hline(y=vdpa, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=row, col=col)
    fig.add_hline(y=vrpa, line_dash="dash", line_color=PLOT_RECONNECT_COLOR, row=row, col=col)
    fig.add_hline(y=vdua, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=row, col=col)
    chip(fig, f"High-V trip · VDUA {vdua:.2f}", 0.99, 0.40, row, col, color=PLOT_TRIP_COLOR)
    chip(fig, f"Low-V trip · Vcease/VDPA {vdpa:.2f}", 0.99, 0.25, row, col, color=PLOT_TRIP_COLOR)
    chip(fig, f"Reconnect · Vrecon/VRPA {vrpa:.2f}", 0.99, 0.10, row, col, color=PLOT_RECONNECT_COLOR)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, v_max], row=row, col=col)
    _point_out_short_event(fig, sim, sim["fault_voltage_pu"], 1.0,
                           f"{sim['fault_voltage_pu']:.2f} pu for {format_seconds(sim['fault_duration_s'])}", row, col)


def _add_power_panel(fig, sim, row=2, col=1):
    """Bottom-left: block power over the same timeline as the disturbance
    above it (x-axes linked), with trip/reconnect markers on both."""
    p_points = sim["p_points"]
    fig.add_trace(
        go.Scatter(x=[t for t, _ in p_points], y=[v for _, v in p_points], mode="lines",
                   line={"color": PLOT_POWER_COLOR, "width": 2.2}, name="Power output (frac. of block MW)",
                   hovertemplate="%{y:.2f} of block MW at %{x:.2f}s<extra></extra>"),
        row=row, col=col,
    )
    fig.update_yaxes(title_text="Power (frac. MW)", range=[0, max(v for _, v in p_points) + 0.08], row=row, col=col)
    fig.update_xaxes(title_text="Time (s)", row=row, col=col)
    fig.update_xaxes(matches="x", row=row, col=col)

    if sim["trips"]:
        marker_colors = (("trip_time", PLOT_TRIP_COLOR), ("reconnect_start", PLOT_RECONNECT_COLOR),
                         ("reconnect_end", PLOT_RECONNECT_COLOR))
        for tval, color in ((sim["markers"][k], c) for k, c in marker_colors if k in sim["markers"]):
            for r in (1, 2):
                fig.add_vline(x=tval, line_dash="dot", line_color=color, row=r, col=col)
        return
    required = sim.get("armed_required_delay_s")
    # Where it WOULD trip if held that long - drawn only when that's beyond the
    # event itself.
    if required is not None:
        would_trip_at = sim["fault_start"] + required
        if would_trip_at > sim["fault_end"]:
            for r in (1, 2):
                fig.add_vline(x=would_trip_at, line_dash="dash", line_color=PLOT_RAMP_COLOR, row=r, col=col)
            fig.add_annotation(
                text=f"would trip at {format_seconds(would_trip_at)}", xref="x", yref="y domain", x=would_trip_at,
                y=0.45, xanchor="right", showarrow=False, row=row, col=col,
                font={"color": PLOT_RAMP_COLOR, "size": 10}, bgcolor="rgba(255,255,255,0.88)",
                bordercolor="#c7d2de", borderwidth=1, borderpad=3,
            )


def _verdict_title(heading, rows, full_label):
    """A tolerance panel's title with its compliance verdict appended, and a
    hover text spelling it out. `rows` is [(glyph, label, ok)]; the glyph
    matches that direction's stage-marker symbol, so the title doubles as the
    markers' key. Kept in the title rather than a chip inside the plot, where
    at narrow widths it covered stage markers and the simulated event."""
    parts, hover = [heading], [f"<b>{full_label}</b>"]
    for glyph, label, ok in rows:
        color = PLOT_RECONNECT_COLOR if ok else PLOT_TRIP_COLOR
        parts.append(f'<span style="color:{color}">{glyph} {"OK" if ok else "NOT OK"}</span>')
        hover.append(f"{glyph} {label} stages: {'OK' if ok else 'NOT acceptable'}")
    hover.append("Hover a stage marker for its own verdict.")
    return "  ".join(parts), "<br>".join(hover)


def _add_voltage_tolerance_panel(fig, params, envelope, overvoltage_envelope, preset_name, event, row=1, col=2):
    """Top-right: every voltage trip stage against the preset's own two-sided
    voltage envelope (never ITIC/CBEMA - see docs/user/presets/README.md). All 4
    stages per direction are plotted: the compiled DLL evaluates every one
    (docs/developer/PERC1_MODEL.md, "Option 3 is always live")."""
    if not envelope:
        fig.add_annotation(
            text="Select a ride-through preset to compare this block against.",
            xref="x domain", yref="y domain", x=0.5, y=0.5, xanchor="center", yanchor="middle",
            showarrow=False, row=row, col=col, font={"color": PLOT_AXIS_TEXT, "size": 11},
        )
        fig.update_xaxes(range=[0, 1], title_text="Duration (s)", showticklabels=False, row=row, col=col)
        fig.update_yaxes(range=[0, 1], title_text="Voltage (pu)", showticklabels=False, row=row, col=col)
        return

    under_segments = envelope_segments_from_steps(envelope)
    over_segments = overvoltage_segments_from_steps(overvoltage_envelope or [])
    under_points = segments_to_points(under_segments)
    over_points = segments_to_points(over_segments)
    all_over_voltages = [params[v] for v, _ in OVERVOLTAGE_STAGE_CONS]
    vmax = max(1.4, max(v for _, v in over_points) + 0.25, max(all_over_voltages) + 0.25)
    group = "voltage-envelope"
    fig.add_trace(go.Scatter(x=[t for t, _ in under_points], y=[v for _, v in under_points], mode="lines",
                             line={"width": 0}, fill="tozeroy", fillcolor="rgba(192,57,43,0.18)",
                             legendgroup=group, hoverinfo="skip"), row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in under_points], y=[v for _, v in under_points], mode="lines",
                             line={"color": "#3a4552", "width": 2.2}, name=f"{preset_name} boundary",
                             legendgroup=group,
                             hovertemplate=f"{preset_name}: min %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>"),
                  row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in over_points], y=[v for _, v in over_points], mode="lines",
                             line={"color": "#3a4552", "width": 2.2}, fill="tonexty",
                             fillcolor="rgba(26,122,60,0.14)", name=f"{preset_name} boundary", legendgroup=group,
                             hovertemplate=f"{preset_name}: max %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>"),
                  row=row, col=col)
    fig.add_trace(go.Scatter(x=[t for t, _ in over_points], y=[vmax] * len(over_points), mode="lines",
                             line={"width": 0}, fill="tonexty", fillcolor="rgba(192,57,43,0.18)",
                             legendgroup=group, hoverinfo="skip"), row=row, col=col)
    region_label(fig, "No damage expected", 0.02, 0.60, row, col, PLOT_RECONNECT_COLOR, "middle")
    region_label(fig, "Trip permitted (undervoltage)", 0.02, 0.03, row, col, PLOT_TRIP_COLOR, "bottom")
    region_label(fig, "Trip permitted (overvoltage)", 0.02, 0.97, row, col, PLOT_TRIP_COLOR, "top")

    def stages(stage_cons, segments, direction, symbol):
        results = []
        for i, (v_name, d_name) in enumerate(stage_cons):
            stage_v, stage_d = params[v_name], params[d_name]
            bound = envelope_bound(segments, stage_d)
            ok = stage_v <= bound if direction == "under" else stage_v >= bound
            results.append(ok)
            verdict = (f"tripping here is permitted ({preset_name}: {bound:.2f} pu by {stage_d:.3f}s)." if ok else
                       f"NOT acceptable - {preset_name} requires riding through "
                       f"{'down' if direction == 'under' else 'up'} to {bound:.2f} pu at {stage_d:.3f}s.")
            stage_marker(fig, stage_d, stage_v, ok, symbol,
                          f"This block's {direction}voltage trip stage {i + 1}",
                          f"<b>{direction.capitalize()}voltage stage {i + 1}: {v_name}={stage_v:.2f} pu @ "
                          f"{d_name}={stage_d:.3f}s</b><br>{verdict}", row, col)
        return all(results)

    under_ok = stages(UNDERVOLTAGE_STAGE_CONS, under_segments, "under", "circle")
    over_ok = stages(OVERVOLTAGE_STAGE_CONS, over_segments, "over", "diamond")

    breakpoints = [params[d] for _, d in UNDERVOLTAGE_STAGE_CONS + OVERVOLTAGE_STAGE_CONS]
    breakpoints += [s.min_duration_s for s in envelope if s.min_duration_s is not None]
    breakpoints += [s.min_duration_s for s in (overvoltage_envelope or []) if s.min_duration_s is not None]
    if event:
        breakpoints.append(event[0])
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} pu held {event[0]:.3f}s",
                          row, col, (0, vmax))
    # Linear, auto-scaled to this preset's own breakpoints - a log axis spent
    # most of its width on the flat 10-100 s tail.
    fig.update_xaxes(type="linear", range=[0, max(2.5, max(breakpoints) * 1.25)], title_text="Duration (s)",
                     row=row, col=col)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, vmax], row=row, col=col)
    return [("●", "Undervoltage", under_ok), ("◆", "Overvoltage", over_ok)]


def _add_frequency_tolerance_panel(fig, params, table, preset_name, event, row=2, col=2):
    """Bottom-right: the frequency counterpart of the voltage tolerance map.
    With a published table (FrequencyRideThrough) it shades where tripping is
    permitted and checks every real stage against it; without one it still
    shows this block's own frequency trip stages, so the vendor-typical
    defaults are visible rather than silent."""
    under = _frequency_trip_point(params, "under")
    over = _frequency_trip_point(params, "over")
    durations = [under[3], over[3]]
    levels = [under[2], over[2]]
    if table:
        durations += [b.min_duration_s for b in table.underfrequency + table.overfrequency]
        levels += [b.limit_hz for b in table.underfrequency + table.overfrequency]
    if event:
        durations.append(event[0])
        levels.append(event[1])
    xmax = max(450.0, max(durations, default=0.0) * 1.25)
    # A full 1 Hz of headroom beyond every plotted level keeps the corner region
    # labels and the compliance chip clear of the boundary lines and markers.
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
                                 hovertemplate=f"{preset_name}: ride through down to %{{y:.2f}} Hz "
                                               f"for %{{x:.0f}}s<extra></extra>"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[f for _, f in ceiling], mode="lines",
                                 line={"color": "#3a4552", "width": 2.2}, fill="tonexty",
                                 fillcolor="rgba(26,122,60,0.14)", name=f"{preset_name} frequency boundary",
                                 legendgroup=group,
                                 hovertemplate=f"{preset_name}: ride through up to %{{y:.2f}} Hz "
                                               f"for %{{x:.0f}}s<extra></extra>"), row=row, col=col)
        fig.add_trace(go.Scatter(x=[t for t, _ in ceiling], y=[y_hi] * len(ceiling), mode="lines",
                                 line={"width": 0}, fill="tonexty", fillcolor="rgba(192,57,43,0.18)",
                                 legendgroup=group, hoverinfo="skip"), row=row, col=col)
        region_label(fig, "Must ride through", 0.02, 0.50, row, col, PLOT_RECONNECT_COLOR, "middle")
        region_label(fig, "Trip permitted (under-frequency)", 0.02, 0.03, row, col, PLOT_TRIP_COLOR, "bottom")
        region_label(fig, "Trip permitted (over-frequency)", 0.02, 0.97, row, col, PLOT_TRIP_COLOR, "top")
    else:
        fig.add_hline(y=NOMINAL_FREQUENCY_HZ, line_color=PLOT_GRID_COLOR, line_width=1.5, row=row, col=col)
        source = preset_name or "No preset selected"
        chip(fig, f"{source}: no published frequency table", 0.02, 0.97, row, col,
              xanchor="left", yanchor="top", color=PLOT_AXIS_TEXT)

    # The block's deadband: PERC1 has one trip point per direction, so it rides
    # through indefinitely between them and trips once outside the band for the
    # delay - the dashed corners mark where that trip region starts.
    low, high = under[2], over[2]
    fig.add_hrect(y0=low, y1=high, fillcolor=PLOT_DEADBAND_COLOR, opacity=0.08, line_width=0,
                  layer="below", exclude_empty_subplots=False, row=row, col=col)
    for (_trip, _delay, f, d), edge in ((under, y_lo), (over, y_hi)):
        fig.add_trace(go.Scatter(
            x=[d, d, xmax], y=[edge, f, f], mode="lines", hoverinfo="skip", name="Deadband trip region",
            line={"color": PLOT_DEADBAND_COLOR, "width": 1.8, "dash": "dash"},
        ), row=row, col=col)
    fig.add_annotation(
        text=f"<b>Deadband {low:.2f}-{high:.2f} Hz</b>", xref="x domain", yref="y", x=0.98, y=(low + high) / 2,
        xanchor="right", yanchor="middle", showarrow=False, row=row, col=col,
        font={"color": PLOT_DEADBAND_COLOR, "size": 11}, bgcolor="rgba(255,255,255,0.85)",
    )

    def plot_stages(point, direction, symbol):
        results = []
        for trip_name, delay_name, f, d in (point,):
            if table:
                bound = table.bound(direction, d)
                ok = f <= bound if direction == "under" else f >= bound
                verdict = (f"tripping here is permitted ({preset_name}: {bound:.2f} Hz at {d:.0f}s)." if ok else
                           f"NOT acceptable - {preset_name} requires riding through "
                           f"{'down' if direction == 'under' else 'up'} to {bound:.2f} Hz at {d:.0f}s.")
            else:
                ok, verdict = True, "No published frequency table to check against."
            results.append(ok)
            stage_marker(fig, d, f, ok, symbol, f"This block's {direction}-frequency trip point",
                          f"<b>{direction.capitalize()}-frequency trip: {trip_name}={f:.2f} Hz @ "
                          f"{delay_name}={d:.2f}s</b><br>{verdict}", row, col, neutral=table is None)
        return all(results)

    under_ok = plot_stages(under, "under", "circle")
    over_ok = plot_stages(over, "over", "diamond")
    if event:
        add_event_marker(fig, event[0], event[1], f"Simulated event: {event[1]:.2f} Hz held {event[0]:.0f}s",
                          row, col, (y_lo, y_hi))
    fig.update_xaxes(type="linear", range=[0, xmax], title_text="Duration (s)", row=row, col=col)
    fig.update_yaxes(title_text="Frequency (Hz)", range=[y_lo, y_hi], row=row, col=col)
    return [("●", "Under-frequency", under_ok), ("◆", "Over-frequency", over_ok)] if table else None


def build_perc1_response_figure(params, block_label, envelope=None, envelope_label=None,
                                 overvoltage_envelope=None, height=None,
                                 fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *,
                                 frequency_ride_through=None, event_kind="voltage",
                                 fault_frequency_hz=FREQUENCY_EVENT_HZ, simulate_event=simulate_perc1_event):
    """The live/report chart: a 2x2 grid so both ride-through tolerance maps fit
    without stacking four full-width panels.

        [ disturbance over time ] [ voltage tolerance map   ]
        [ power over time       ] [ frequency tolerance map ]

    The left column is the simulated event's timeline (x-axes linked); it shows
    voltage or frequency depending on `event_kind` - one measure per axis, never
    both. The right column compares every trip stage against the selected
    preset's own voltage envelope and frequency table, and marks where the
    simulated event lands. `height=None` autosizes to the live view;
    the saved report passes an explicit height. The event's verdict is not
    drawn in the figure - see event_status()/render_perc1_response_page().

    `simulate_event` (same signature as `simulate_perc1_event`) runs the event: the PERC2 DLL v2.3 page passes its
    own, so the response comes from that model's simulator while `params` (ramps in seconds) draw the stages."""
    from plotly.subplots import make_subplots

    sim = simulate_event(params, event_kind, fault_duration_s, fault_voltage_pu, fault_frequency_hz)
    preset_name = short_label(envelope_label) if envelope_label else None
    fig = make_subplots(
        rows=2, cols=2, horizontal_spacing=0.13, vertical_spacing=0.2,
        subplot_titles=(
            "System frequency" if event_kind == "frequency" else "Voltage at the load bus",
            "Voltage tolerance",
            "Power output (fraction of block MW)",
            "Frequency deadband",
        ),
    )
    fig.update_annotations(font={"size": 12, "color": PLOT_TITLE_TEXT})

    _add_disturbance_panel(fig, sim, params, event_kind)
    _add_power_panel(fig, sim)
    voltage_event = (fault_duration_s, fault_voltage_pu) if event_kind == "voltage" else None
    frequency_event = (fault_duration_s, fault_frequency_hz) if event_kind == "frequency" else None
    voltage_verdict = _add_voltage_tolerance_panel(
        fig, params, envelope, overvoltage_envelope, preset_name, voltage_event)
    frequency_verdict = _add_frequency_tolerance_panel(
        fig, params, frequency_ride_through, preset_name, frequency_event)
    if voltage_verdict:
        set_subplot_title(fig, 1, *_verdict_title(f"Voltage vs. {preset_name}", voltage_verdict, envelope_label))
    if frequency_verdict:
        set_subplot_title(fig, 3, *_verdict_title(f"Frequency vs. {preset_name}", frequency_verdict,
                                                   envelope_label))

    fig.update_layout(
        autosize=True,
        height=height,
        margin={"l": 58, "r": 14, "t": 26, "b": 44},
        showlegend=False,
        font={"family": "-apple-system, Segoe UI, Arial, sans-serif", "color": PLOT_TITLE_TEXT, "size": 11},
        plot_bgcolor="#ffffff",
        title=None,
    )
    fig.update_xaxes(gridcolor=PLOT_GRID_COLOR, title_standoff=4)
    fig.update_yaxes(gridcolor=PLOT_GRID_COLOR, title_standoff=4)
    return fig


def build_perc1_response_figure_from_result(result, params, block_label, envelope=None, envelope_label=None,
                                             overvoltage_envelope=None, height=None):
    """Same 3-panel layout as build_perc1_response_figure, but fed from a
    real/mock psse_runner.SimulationResult's dense time_s/voltage_pu/
    active_power_pu arrays instead of simulate_perc1_response's analytic
    piecewise output. `params` is the block's own CON dict (VDPA/VRPA/VDUA/
    TDUA/DMA) - a SimulationResult alone doesn't carry the CON values that
    produced it, and panel 1's boundary lines / panel 3's trip-point marker
    both need them.

    Deliberately a standalone function rather than a refactor of
    build_perc1_response_figure's internals: that function is live in
    ui/main_window.py's QWebEngineView hot path, which does not use this result-driven
    path - duplicating panels 1-2's (much smaller) trace logic here avoids
    any risk to the live chart. Panel 3 reuses the exact same
    envelope-drawing helpers (envelope_segments_from_steps etc.) and the
    same construction as build_perc1_response_figure's own panel 3 - see
    that function for the detailed rationale behind each choice there."""
    from plotly.subplots import make_subplots

    vdpa, vrpa, vdua = params["VDPA"], params["VRPA"], params["VDUA"]

    fig = make_subplots(
        rows=3, cols=1,
        subplot_titles=(
            "",
            "Power output (fraction of block MW online)",
            "Trip threshold vs. ride-through envelope",
        ),
        vertical_spacing=0.12,
        row_heights=[0.28, 0.28, 0.44],
    )

    # --- Panel 1: voltage(t) ---
    v_max = max(max(result.voltage_pu, default=1.0), vdua, 1.0, vrpa + 0.3, vdua + 0.2) + 0.05
    fig.add_hrect(y0=0, y1=vdpa, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=1, col=1)
    fig.add_hrect(y0=vdpa, y1=vdua, fillcolor="#e5f5ea", opacity=0.7, line_width=0, row=1, col=1)
    fig.add_hrect(y0=vdua, y1=v_max, fillcolor="#fbeae8", opacity=0.7, line_width=0, row=1, col=1)
    fig.add_trace(
        go.Scatter(
            x=result.time_s, y=result.voltage_pu, mode="lines",
            line={"color": PLOT_VOLTAGE_COLOR, "width": 2.4}, name="Voltage (pu)",
        ),
        row=1, col=1,
    )
    fig.add_hline(y=vdpa, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=1, col=1)
    fig.add_hline(y=vrpa, line_dash="dash", line_color=PLOT_RECONNECT_COLOR, row=1, col=1)
    fig.add_hline(y=vdua, line_dash="dash", line_color=PLOT_TRIP_COLOR, row=1, col=1)
    fig.update_yaxes(title_text="Voltage (pu)", range=[0, v_max], row=1, col=1)

    # --- Panel 2: power(t) ---
    p_max = max(result.active_power_pu, default=1.0) + 0.05
    fig.add_trace(
        go.Scatter(
            x=result.time_s, y=result.active_power_pu, mode="lines",
            line={"color": PLOT_POWER_COLOR, "width": 2.4}, name="Power output (frac. of block MW)",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(title_text="Power (frac. MW)", range=[0, p_max], row=2, col=1)
    fig.update_xaxes(title_text="Time (s) - simulated event timeline", row=2, col=1)

    if result.tripped:
        for tval, color in [
            (result.trip_time_s, PLOT_TRIP_COLOR),
            (result.reconnect_time_s, PLOT_RECONNECT_COLOR),
        ]:
            if tval is None:
                continue
            for row in (1, 2):
                fig.add_vline(x=tval, line_dash="dot", line_color=color, row=row, col=1)
        trip_time_text = f"{result.trip_time_s:.2f}s" if result.trip_time_s is not None else "unknown time"
        caption = f"{result.trip_type} trip at {trip_time_text} (runner: {result.runner_id})"
    else:
        caption = f"rides through, no trip (runner: {result.runner_id})"

    verdict = "TRIPS" if result.tripped else "RIDES THROUGH"
    verdict_color = PLOT_TRIP_COLOR if result.tripped else PLOT_RECONNECT_COLOR
    fig.add_annotation(
        text=f"<b>{verdict}</b> — {caption}", xref="x domain", yref="y domain",
        x=0.02, y=0.95, xanchor="left", yanchor="top",
        showarrow=False, row=2, col=1, font={"color": verdict_color, "size": 12},
        bgcolor="rgba(255,255,255,0.85)", bordercolor="#c7d2de", borderwidth=1, borderpad=4,
    )

    # --- Panel 3: trip threshold vs. ride-through envelope ---
    if not envelope:
        fig.add_annotation(
            text="Select a ride-through preset to compare this block against.",
            xref="x domain", yref="y domain", x=0.5, y=0.5,
            xanchor="center", yanchor="middle", showarrow=False, row=3, col=1,
            font={"color": PLOT_AXIS_TEXT, "size": 13},
        )
        fig.update_xaxes(range=[0, 1], title_text="Duration (seconds)", row=3, col=1, showticklabels=False)
        fig.update_yaxes(range=[0, 1], title_text="Voltage (pu)", row=3, col=1, showticklabels=False)
    else:
        preset_name = envelope_label or "selected standard"
        under_segments = envelope_segments_from_steps(envelope)
        over_segments = overvoltage_segments_from_steps(overvoltage_envelope or [])
        under_points = segments_to_points(under_segments)
        over_points = segments_to_points(over_segments)
        lower_x = [t for t, _ in under_points]
        lower_y = [v for _, v in under_points]
        upper_x = [t for t, _ in over_points]
        upper_y = [v for _, v in over_points]
        all_over_voltages = [params[v] for v in ("VDUA", "VDUA1", "VDUA2", "VDUA3")]
        panel3_vmax = max(1.3, max(upper_y) + 0.15, max(all_over_voltages) + 0.15)
        boundary_group = "preset-boundary"

        fig.add_trace(
            go.Scatter(
                x=lower_x, y=lower_y, mode="lines", line={"width": 0},
                fill="tozeroy", fillcolor="rgba(192,57,43,0.18)",
                legendgroup=boundary_group, showlegend=False, hoverinfo="skip",
            ),
            row=3, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=lower_x, y=lower_y, mode="lines",
                line={"color": "#3a4552", "width": 2.4},
                name=f"{preset_name} boundary", legendgroup=boundary_group,
                hovertemplate=f"{preset_name}: min %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>",
            ),
            row=3, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=upper_x, y=upper_y, mode="lines",
                line={"color": "#3a4552", "width": 2.4},
                fill="tonexty", fillcolor="rgba(26,122,60,0.14)",
                name=f"{preset_name} boundary", legendgroup=boundary_group,
                showlegend=False,
                hovertemplate=f"{preset_name}: max %{{y:.2f}} pu for %{{x:.3f}}s<extra></extra>",
            ),
            row=3, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=upper_x, y=[panel3_vmax] * len(upper_x), mode="lines", line={"width": 0},
                fill="tonexty", fillcolor="rgba(192,57,43,0.18)",
                legendgroup=boundary_group, showlegend=False, hoverinfo="skip",
            ),
            row=3, col=1,
        )

        fig.add_annotation(
            text="No damage expected", xref="x domain", yref="y domain", x=0.02, y=0.60,
            xanchor="left", yanchor="middle", showarrow=False, row=3, col=1,
            font={"color": PLOT_RECONNECT_COLOR, "size": 11},
        )
        fig.add_annotation(
            text="Trip permitted (undervoltage)", xref="x domain", yref="y domain", x=0.02, y=0.03,
            xanchor="left", yanchor="bottom", showarrow=False, row=3, col=1,
            font={"color": PLOT_TRIP_COLOR, "size": 11},
        )
        fig.add_annotation(
            text="Trip permitted (overvoltage)", xref="x domain", yref="y domain", x=0.02, y=0.97,
            xanchor="left", yanchor="top", showarrow=False, row=3, col=1,
            font={"color": PLOT_TRIP_COLOR, "size": 11},
        )

        # All 4 stages per direction, not just stage 1 - see
        # build_perc1_response_figure's own panel 3 for the detailed
        # rationale (PSS/E testing confirmed the compiled DLL always
        # evaluates all 4 stages).
        under_stage_names = ["VDPA", "VDPA1", "VDPA2", "VDPA3"]
        under_stage_durations = ["DMA", "DMA1", "DMA2", "DMA3"]
        over_stage_names = ["VDUA", "VDUA1", "VDUA2", "VDUA3"]
        over_stage_durations = ["TDUA", "TDUA1", "TDUA2", "TDUA3"]
        under_points_group = "under-trip-points"
        over_points_group = "over-trip-points"

        for i, (v_name, d_name) in enumerate(zip(under_stage_names, under_stage_durations)):
            stage_v, stage_d = params[v_name], params[d_name]
            stage_bound = envelope_bound(under_segments, stage_d)
            stage_color = PLOT_RECONNECT_COLOR if stage_v <= stage_bound else PLOT_TRIP_COLOR
            fig.add_trace(
                go.Scatter(
                    x=[stage_d], y=[stage_v], mode="markers",
                    marker={"size": 13, "color": stage_color, "line": {"color": "white", "width": 1.5}},
                    name="This block's undervoltage trip stages", legendgroup=under_points_group,
                    showlegend=(i == 0),
                    hovertemplate=(
                        f"<b>Undervoltage stage {i + 1}: {v_name}={stage_v:.2f} pu @ "
                        f"{d_name}={stage_d:.3f}s</b><extra></extra>"
                    ),
                ),
                row=3, col=1,
            )

        for i, (v_name, d_name) in enumerate(zip(over_stage_names, over_stage_durations)):
            stage_v, stage_d = params[v_name], params[d_name]
            stage_bound = envelope_bound(over_segments, stage_d)
            stage_color = PLOT_RECONNECT_COLOR if stage_v >= stage_bound else PLOT_TRIP_COLOR
            fig.add_trace(
                go.Scatter(
                    x=[stage_d], y=[stage_v], mode="markers",
                    marker={"size": 13, "color": stage_color, "line": {"color": "white", "width": 1.5},
                            "symbol": "diamond"},
                    name="This block's overvoltage trip stages", legendgroup=over_points_group,
                    showlegend=(i == 0),
                    hovertemplate=(
                        f"<b>Overvoltage stage {i + 1}: {v_name}={stage_v:.2f} pu @ "
                        f"{d_name}={stage_d:.3f}s</b><extra></extra>"
                    ),
                ),
                row=3, col=1,
            )

        finite_breakpoints = [params[d] for d in under_stage_durations] + [params[d] for d in over_stage_durations]
        finite_breakpoints += [s.min_duration_s for s in envelope if s.min_duration_s is not None]
        if overvoltage_envelope:
            finite_breakpoints += [s.min_duration_s for s in overvoltage_envelope if s.min_duration_s is not None]
        panel3_xmax = max(2.5, max(finite_breakpoints) * 1.5)
        fig.update_xaxes(type="linear", range=[0, panel3_xmax], title_text="Duration (seconds)", row=3, col=1)
        fig.update_yaxes(title_text="Voltage (pu)", range=[0, panel3_vmax], row=3, col=1)

    fig.update_layout(
        autosize=True,
        height=height,
        margin={"l": 60, "r": 30, "t": 70, "b": 60},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        font={"family": "-apple-system, Segoe UI, Arial, sans-serif", "color": PLOT_TITLE_TEXT},
        plot_bgcolor="#ffffff",
        title=None,
    )
    fig.update_xaxes(gridcolor=PLOT_GRID_COLOR)
    fig.update_yaxes(gridcolor=PLOT_GRID_COLOR)
    return fig


def build_recovery_panel_html(params, block_label, block_mw=None, fault_duration_s=FAULT_DURATION,
                               fault_voltage_pu=V_FAULT, *, event_kind="voltage",
                               fault_frequency_hz=FREQUENCY_EVENT_HZ, simulate_event=simulate_perc1_event):
    """A compact live summary of how much load trips, how much reconnects, and
    how long the ramp takes - a thin timeline bar plus one line of figures,
    kept short so the 2x2 chart above it keeps its height. Driven by the same
    simulation the chart uses, so the two never disagree."""
    sim = simulate_event(params, event_kind, fault_duration_s, fault_voltage_pu, fault_frequency_hz)
    fcease, frecon = params["FCEASE"], params["FRECON"]
    quantity = "frequency" if event_kind == "frequency" else "voltage"

    def mw_label(fraction):
        if block_mw is None:
            return f"{fraction * 100:.0f}%"
        return f"{fraction * block_mw:.2f} MW ({fraction * 100:.0f}%)"

    if not sim["trips"]:
        return f"""
        <div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;
             background:#e5f5ea;border:1px solid #a6dfb8;border-radius:6px;padding:5px 10px;
             color:{PLOT_RECONNECT_COLOR};font-size:12px;font-weight:bold;">
          {block_label}: rides through - no trip at the simulated {quantity} event.
        </div>
        """

    trip_time = sim["markers"]["trip_time"]
    sim_end = sim["sim_end"]

    def pct(t):
        return max(0.0, min(100.0, 100.0 * t / sim_end))

    if "reconnect_start" not in sim["markers"]:
        online_w = pct(trip_time)
        segments_html = "".join([
            f'<div title="Online 0-{trip_time:.2f}s" style="width:{online_w:.2f}%;background:{PLOT_RECONNECT_COLOR};"></div>',
            f'<div title="Tripped {trip_time:.2f}s+" style="width:{100.0 - online_w:.2f}%;background:{PLOT_TRIP_COLOR};"></div>',
        ])
        return f"""
    <div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:12px;">
      <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:3px;">{segments_html}</div>
      <div style="display:flex;gap:4px 14px;flex-wrap:wrap;color:{PLOT_AXIS_TEXT};">
        <span style="white-space:nowrap;">Load tripped <b style="color:{PLOT_TRIP_COLOR}">{mw_label(fcease)}</b></span>
        <span><b style="color:{PLOT_TRIP_COLOR}">Does not reconnect</b>: {sim["stays_tripped_reason"]}</span>
      </div>
    </div>
    """

    reconnect_start = sim["markers"]["reconnect_start"]
    reconnect_end = sim["markers"]["reconnect_end"]

    online_w = pct(trip_time)
    tripped_w = pct(reconnect_start) - online_w
    ramping_w = pct(reconnect_end) - pct(reconnect_start)
    recovered_w = 100.0 - pct(reconnect_end)
    segments_html = "".join([
        f'<div title="Online 0-{trip_time:.2f}s" style="width:{online_w:.2f}%;background:{PLOT_RECONNECT_COLOR};"></div>',
        f'<div title="Tripped {trip_time:.2f}-{reconnect_start:.2f}s" style="width:{tripped_w:.2f}%;background:{PLOT_TRIP_COLOR};"></div>',
        f'<div title="Ramping {reconnect_start:.2f}-{reconnect_end:.2f}s" style="width:{ramping_w:.2f}%;background:{PLOT_RAMP_COLOR};"></div>',
        f'<div title="Recovered {reconnect_end:.2f}s+" style="width:{recovered_w:.2f}%;background:{PLOT_RECONNECT_COLOR};opacity:0.55;"></div>',
    ])
    ramp_s = reconnect_end - reconnect_start
    delay_s = reconnect_start - sim["fault_end"]
    stat = 'style="white-space:nowrap;"'
    return f"""
    <div class="recovery-panel" style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:12px;">
      <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:3px;">{segments_html}</div>
      <div style="display:flex;gap:4px 14px;flex-wrap:wrap;color:{PLOT_AXIS_TEXT};">
        <span {stat}>Load tripped <b style="color:{PLOT_TRIP_COLOR}">{mw_label(fcease)}</b></span>
        <span {stat}>Reconnects <b style="color:{PLOT_RECONNECT_COLOR}">{mw_label(frecon * fcease)}</b></span>
        <span {stat}>Ramp time <b style="color:{PLOT_RAMP_COLOR}">{format_seconds(ramp_s)}</b>,
          {format_seconds(delay_s)} after {quantity} recovers</span>
      </div>
    </div>
    """


def _page_parts(params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz,
                simulate_event=simulate_perc1_event):
    sim = simulate_event(params, event_kind, fault_duration_s, fault_voltage_pu, fault_frequency_hz)
    return (
        panel1_title_text(block_label, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz),
        event_status_html(sim),
        build_recovery_panel_html(params, block_label, block_mw, fault_duration_s, fault_voltage_pu,
                                  event_kind=event_kind, fault_frequency_hz=fault_frequency_hz,
                                  simulate_event=simulate_event),
    )


def render_perc1_response_page(params, block_label, envelope=None, envelope_label=None,
                                overvoltage_envelope=None, block_mw=None, include_plotlyjs=True,
                                div_id="plot", fill_viewport=False, fault_duration_s=FAULT_DURATION,
                                fault_voltage_pu=V_FAULT, *, frequency_ride_through=None, event_kind="voltage",
                                fault_frequency_hz=FREQUENCY_EVENT_HZ, simulate_event=simulate_perc1_event,
                                notes=""):
    """Assemble one self-contained (or CDN-linked) HTML fragment: a heading row
    (event name + verdict), the 2x2 Plotly figure, and the recovery summary.

    `fill_viewport=True` is the live QWebEngineView's one-shot initial load: the
    chart flexes to fill whatever height the heading and recovery strip leave,
    and `config={"responsive": True}` re-fits it on resize, so the page itself
    never scrolls. `fill_viewport=False` is the saved report, where the chart is
    one fragment on a scrolling page and gets a fixed height. `simulate_event` is as for
    `build_perc1_response_figure`; `notes` is HTML shown below the recovery strip."""
    fig = build_perc1_response_figure(
        params, block_label, envelope, envelope_label, overvoltage_envelope,
        height=None if fill_viewport else 720, fault_duration_s=fault_duration_s,
        fault_voltage_pu=fault_voltage_pu, frequency_ride_through=frequency_ride_through,
        event_kind=event_kind, fault_frequency_hz=fault_frequency_hz, simulate_event=simulate_event,
    )
    config = {"responsive": True, "displaylogo": False} if fill_viewport else {"displaylogo": False}
    figure_html = fig.to_html(include_plotlyjs=include_plotlyjs, full_html=False, div_id=div_id, config=config)
    title_text, status_html, recovery_html = _page_parts(
        params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz,
        simulate_event)
    heading = f"""
      <div class="response-heading" style="display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 12px;
           padding:0 10px;font-family:-apple-system, Segoe UI, Arial, sans-serif;">
        <h4 id="panel1-title" style="margin:2px 0 0;font-size:14px;color:{PLOT_TITLE_TEXT};">{title_text}</h4>
        <div id="event-status" style="font-size:12px;">{status_html}</div>
      </div>"""

    if not fill_viewport:
        return f"""
        <div class="perc1-response">
          {heading}
          {figure_html}
          <div id="recovery-panel">{recovery_html}</div>
          {notes}
        </div>
        """

    return f"""
    <style>
      html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden;
                    font-family: -apple-system, Segoe UI, Arial, sans-serif; }}
      .perc1-response {{ display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }}
      .response-heading {{ flex: 0 0 auto; }}
      .plot-container {{ flex: 1 1 auto; min-height: 0; }}
      /* to_html() wraps the plot in an unstyled div, so the plot's own
         height:100% would resolve against nothing and the chart would overflow
         onto the recovery strip below it. */
      .plot-container > div {{ height: 100%; }}
      #recovery-panel {{ flex: 0 0 auto; padding: 2px 10px 6px; }}
    </style>
    <div class="perc1-response">
      {heading}
      <div class="plot-container">{figure_html}</div>
      <div id="recovery-panel">{recovery_html}</div>
      {notes}
    </div>
    <script>
      // Plotly's "responsive" option only re-fits on window resizes, and
      // Plotly.react() keeps the size measured at first draw - but this
      // container also changes height on its own (the recovery strip below it
      // is one line when the block rides through, two when it trips). Re-fit
      // whenever the container itself changes size.
      new ResizeObserver(function () {{
        var plot = document.getElementById({json.dumps(div_id)});
        if (plot && window.Plotly) {{ Plotly.Plots.resize(plot); }}
      }}).observe(document.querySelector(".plot-container"));
    </script>
    """


def build_live_update_js(params, block_label, envelope=None, envelope_label=None,
                          overvoltage_envelope=None, block_mw=None, div_id="plot",
                          fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *,
                          frequency_ride_through=None, event_kind="voltage",
                          fault_frequency_hz=FREQUENCY_EVENT_HZ, simulate_event=simulate_perc1_event):
    """A `runJavaScript` payload that pushes new data into an *already-loaded*
    live page via `Plotly.react(...)` (diff-based redraw) plus plain DOM updates
    for the heading, status line and recovery strip - preserving the viewer's
    zoom/pan state instead of reloading the page."""
    fig = build_perc1_response_figure(params, block_label, envelope, envelope_label, overvoltage_envelope,
                                       fault_duration_s=fault_duration_s, fault_voltage_pu=fault_voltage_pu,
                                       frequency_ride_through=frequency_ride_through, event_kind=event_kind,
                                       fault_frequency_hz=fault_frequency_hz, simulate_event=simulate_event)
    title_text, status_html, recovery_html = _page_parts(
        params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz,
        simulate_event)
    return (
        "(function(){"
        f"var fig = {fig.to_json()};"
        f"Plotly.react({json.dumps(div_id)}, fig.data, fig.layout);"
        f"var panel = document.getElementById('recovery-panel');"
        f"if (panel) {{ panel.innerHTML = {json.dumps(recovery_html)}; }}"
        f"var status = document.getElementById('event-status');"
        f"if (status) {{ status.innerHTML = {json.dumps(status_html)}; }}"
        f"var titleEl = document.getElementById('panel1-title');"
        f"if (titleEl) {{ titleEl.textContent = {json.dumps(title_text)}; }}"
        "})();"
    )
