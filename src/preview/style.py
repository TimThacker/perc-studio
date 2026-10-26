"""The plot style and the small chart helpers every response page shares: the palette, the heading above the
chart, chips, markers and subplot titles."""

from __future__ import annotations

import plotly.graph_objects as go

from app.config import (
    TVA_NAVY,
)
from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)

# Plot palette. Voltage and power are given distinct hues (not two shades of the
# same blue) so the two series are distinguishable without relying on the legend
# alone; trip/reconnect semantics keep the conventional red/green.
# Plot palette. Voltage and power are given distinct hues (not two shades of the
# same blue) so the two series are distinguishable without relying on the legend
# alone; trip/reconnect semantics keep the conventional red/green.
PLOT_VOLTAGE_COLOR = TVA_NAVY


PLOT_POWER_COLOR = "#c9622a"


PLOT_TRIP_COLOR = "#c0392b"


PLOT_RECONNECT_COLOR = "#1a7a3c"


# Amber for the recovery panel's transitional "ramping" state. Its contrast and
# colour-vision-deficiency separation from the trip/reconnect red/green pair
# have not been checked yet.
PLOT_RAMP_COLOR = "#c98a1e"


PLOT_DEADBAND_COLOR = "#1558b0"


PLOT_GRID_COLOR = "#e3e8ee"


PLOT_AXIS_TEXT = "#5b6b7c"


PLOT_TITLE_TEXT = "#22323f"


def short_label(label):
    """A preset label short enough for a half-width panel title: drop any
    parenthetical ("PJM (LCL proposal)" -> "PJM", "NERC PRC-029-1 (IBR
    reference - not a load standard)" -> "NERC PRC-029-1"). The full label is
    in the preset dropdown right beside the chart."""
    return label.split(" (")[0] if label else label


def format_seconds(seconds):
    return f"{seconds:.2f} s" if seconds < 10 else f"{seconds:.0f} s"


def panel1_title_text(block_label, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                      event_kind="voltage", fault_frequency_hz=FREQUENCY_EVENT_HZ):
    """The heading above the chart, naming the block and the simulated event.
    Rendered as plain HTML OUTSIDE the Plotly figure (see
    render_perc1_response_page/build_live_update_js): Plotly.react() does not
    reliably re-measure text in the figure's top margin on a live update, so
    text kept there intermittently overlapped the panels."""
    if event_kind == "frequency":
        if fault_frequency_hz < NOMINAL_FREQUENCY_HZ:
            kind = "under-frequency"
        elif fault_frequency_hz > NOMINAL_FREQUENCY_HZ:
            kind = "over-frequency"
        else:
            kind = "nominal-frequency"
        return (f"{block_label}: {kind} event, {fault_frequency_hz:.2f} Hz held "
                f"{format_seconds(fault_duration_s)}")
    event_word = "swell" if fault_voltage_pu > 1.0 else "sag"
    return (f"{block_label}: {fault_duration_s * 60.0:.1f}-cycle {event_word} "
            f"to {fault_voltage_pu:.2f} pu")


def chip(fig, text, x, y, row, col, *, color=PLOT_TITLE_TEXT, xanchor="right", yanchor="middle", align="left"):
    """A small fixed-position label with a light background, anchored to the
    panel (domain coordinates) rather than to data, so it never lands on a
    trace that moves with the sliders."""
    fig.add_annotation(
        text=text, xref="x domain", yref="y domain", x=x, y=y, xanchor=xanchor, yanchor=yanchor,
        showarrow=False, row=row, col=col, align=align, font={"color": color, "size": 10},
        bgcolor="rgba(255,255,255,0.88)", bordercolor="#c7d2de", borderwidth=1, borderpad=3,
    )


def region_label(fig, text, x, y, row, col, color, yanchor):
    fig.add_annotation(
        text=text, xref="x domain", yref="y domain", x=x, y=y, xanchor="left", yanchor=yanchor,
        showarrow=False, row=row, col=col, font={"color": color, "size": 10},
    )


def add_event_marker(fig, x, y, hover, row, col, y_range):
    """Where the simulated event lands on a tolerance map - ties the time-domain
    column to the tolerance column. Direct-labeled, so it needs no legend; the
    label drops below the marker near the top of the map, where the "Trip
    permitted" region label sits."""
    lo, hi = y_range
    position = "bottom right" if y > lo + 0.7 * (hi - lo) else "top right"
    fig.add_trace(
        go.Scatter(
            x=[x], y=[y], mode="markers+text", text=["this event"], textposition=position,
            textfont={"size": 10, "color": PLOT_TITLE_TEXT},
            marker={"symbol": "x", "size": 12, "color": PLOT_TITLE_TEXT, "line": {"color": "white", "width": 1.5}},
            name="Simulated event", hovertemplate=f"{hover}<extra></extra>",
        ),
        row=row, col=col,
    )


def stage_marker(fig, x, y, compliant, symbol, name, hover, row, col, neutral=False):
    color = PLOT_VOLTAGE_COLOR if neutral else (PLOT_RECONNECT_COLOR if compliant else PLOT_TRIP_COLOR)
    fig.add_trace(
        go.Scatter(x=[x], y=[y], mode="markers", name=name,
                   marker={"size": 11, "color": color, "symbol": symbol, "line": {"color": "white", "width": 1.5}},
                   hovertemplate=f"{hover}<extra></extra>"),
        row=row, col=col,
    )


def set_subplot_title(fig, index, text, hovertext=None):
    """make_subplots() adds the four titles as the first annotations, in
    row-major order: 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right."""
    fig.layout.annotations[index].text = text
    if hovertext:
        fig.layout.annotations[index].hovertext = hovertext
