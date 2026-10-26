"""The response page every standard-style PERC model shares: the 2x2 figure (disturbance and power over time, voltage
and frequency tolerance maps), the heading and recovery strip around it, and the in-place live update.

A model supplies a `ResponsePage`: its simulator, its panels and the pieces of text that differ. Everything else
(figure layout, page assembly, element ids, live update) lives here once, so the PERC1 standard and PERC2 standard
pages cannot drift apart. `preview/standard.py` and `preview/perc2.py` are the two instances.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from editor.model_ui import get_ui_spec
from load_models import get_load_model
from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_HZ,
    V_FAULT,
)
from preview.style import (
    PLOT_GRID_COLOR,
    PLOT_POWER_COLOR,
    PLOT_RAMP_COLOR,
    PLOT_RECONNECT_COLOR,
    PLOT_TITLE_TEXT,
    PLOT_TRIP_COLOR,
    panel1_title_text,
    short_label,
)

LEVEL_STYLE = {
    "error": ("#c0392b", "Error"),
    "warning": ("#8a6d00", "Warning"),
    "info": ("#33475a", "Note"),
}
NOT_MODELLED_COLOR = "#7a8794"


def band_text(low: float, high: float) -> str:
    return f"{low:.2f}-{high:.2f} Hz" if high > low else "none"


def power_panel(fig, sim, row=2, col=1):
    p_points = sim["p_points"]
    fig.add_trace(go.Scatter(x=[t for t, _ in p_points], y=[v for _, v in p_points], mode="lines",
                             line={"color": PLOT_POWER_COLOR, "width": 2.2}, name="Power output (frac. of block MW)",
                             hovertemplate="%{y:.2f} of block MW at %{x:.2f}s<extra></extra>"), row=row, col=col)
    frac = sim.get("frac_on_points")
    if frac and sim["trips"]:
        fig.add_trace(go.Scatter(x=[t for t, _ in frac], y=[v for _, v in frac], mode="lines",
                                 line={"color": PLOT_RAMP_COLOR, "width": 1.4, "dash": "dot"}, name="FracOn",
                                 hovertemplate="FracOn %{y:.2f} at %{x:.2f}s<extra></extra>"), row=row, col=col)
    fig.update_yaxes(title_text="Power (frac. MW)", range=[0, max(v for _, v in p_points) + 0.08], row=row, col=col)
    fig.update_xaxes(title_text="Time (s)", row=row, col=col)
    fig.update_xaxes(matches="x", row=row, col=col)
    if sim["trips"]:
        for key, color in (("trip_time", PLOT_TRIP_COLOR), ("reconnect_start", PLOT_RECONNECT_COLOR),
                           ("reconnect_end", PLOT_RECONNECT_COLOR)):
            if key in sim["markers"]:
                for r in (1, 2):
                    fig.add_vline(x=sim["markers"][key], line_dash="dot", line_color=color, row=r, col=col)


def response_page_html(fig, title_text, status_html, recovery_html, notes, *, include_plotlyjs=True, div_id="plot",
                       fill_viewport=False) -> str:
    """The page around a response figure: heading, figure, recovery strip and notes, with the element ids the live
    update scripts write to. Shared by the PERC1 standard and PERC2 standard pages."""
    config = {"responsive": True, "displaylogo": False} if fill_viewport else {"displaylogo": False}
    figure_html = fig.to_html(include_plotlyjs=include_plotlyjs, full_html=False, div_id=div_id, config=config)
    heading = f"""
      <div class="response-heading" style="display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 12px;
           padding:0 10px;font-family:-apple-system, Segoe UI, Arial, sans-serif;">
        <h4 id="panel1-title" style="margin:2px 0 0;font-size:14px;color:{PLOT_TITLE_TEXT};">{escape(title_text)}</h4>
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
      .plot-container > div {{ height: 100%; }}
      #recovery-panel {{ flex: 0 0 auto; padding: 2px 10px 6px; }}
    </style>
    <div class="perc1-response">
      {heading}
      <div class="plot-container">{figure_html}</div>
      <div id="recovery-panel">{recovery_html}</div>
    </div>
    <script>
      new ResizeObserver(function () {{
        var plot = document.getElementById({json.dumps(div_id)});
        if (plot && window.Plotly) {{ Plotly.Plots.resize(plot); }}
      }}).observe(document.querySelector(".plot-container"));
    </script>
    """


def live_update_js(fig, title_text, status_html, recovery_html, div_id="plot") -> str:
    """Push a new figure and heading into an already-loaded response page (keeps the viewer's zoom)."""
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


def simulate_model(model_id: str, params: dict, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                   event_kind="voltage", fault_frequency_hz=FREQUENCY_EVENT_HZ) -> dict:
    model = get_load_model(model_id)
    if event_kind == "frequency":
        return model.simulate_frequency(params, fault_duration_s, fault_frequency_hz)
    return model.simulate(params, fault_duration_s, fault_voltage_pu)


@dataclass(frozen=True)
class ResponsePage:
    """What one model contributes to the shared page. The panel hooks draw into `fig` and return whatever the
    `annotate` hook needs to title the tolerance maps (the per-point verdicts)."""

    model_id: str
    frequency_title: str  # the title of the frequency panel ("Frequency deadband" / "Frequency tolerance")
    disturbance_panel: Callable  # (fig, sim, params, event_kind)
    voltage_panel: Callable  # (fig, params, envelope, overvoltage_envelope, preset_name, event) -> verdicts
    frequency_panel: Callable  # (fig, params, table, preset_name, event) -> verdicts
    annotate: Callable  # (fig, voltage_verdicts, frequency_verdicts, preset_name, envelope_label, frequency_ride_through)
    status_html: Callable  # (sim, params)
    recovery_html: Callable  # (params, block_label, sim, block_mw, event_kind)
    extra_marks: Callable | None = None  # (fig, sim): marks beyond the first cycle

    def simulate(self, params, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, event_kind="voltage",
                 fault_frequency_hz=FREQUENCY_EVENT_HZ) -> dict:
        return simulate_model(self.model_id, params, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)

    def figure(self, params, block_label, envelope=None, envelope_label=None, overvoltage_envelope=None, height=None,
               fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *, frequency_ride_through=None,
               event_kind="voltage", fault_frequency_hz=FREQUENCY_EVENT_HZ) -> go.Figure:
        sim = self.simulate(params, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)
        preset_name = short_label(envelope_label) if envelope_label else None
        fig = make_subplots(
            rows=2, cols=2, horizontal_spacing=0.13, vertical_spacing=0.2,
            subplot_titles=("System frequency" if event_kind == "frequency" else "Voltage at the load bus",
                            "Voltage tolerance", "Power output (fraction of block MW)", self.frequency_title))
        fig.update_annotations(font={"size": 12, "color": PLOT_TITLE_TEXT})
        self.disturbance_panel(fig, sim, params, event_kind)
        power_panel(fig, sim)
        if self.extra_marks:
            self.extra_marks(fig, sim)
        voltage_event = (fault_duration_s, fault_voltage_pu) if event_kind == "voltage" else None
        frequency_event = (fault_duration_s, fault_frequency_hz) if event_kind == "frequency" else None
        voltage_verdicts = self.voltage_panel(fig, params, envelope, overvoltage_envelope, preset_name, voltage_event)
        frequency_verdicts = self.frequency_panel(fig, params, frequency_ride_through, preset_name, frequency_event)
        self.annotate(fig, voltage_verdicts, frequency_verdicts, preset_name, envelope_label, frequency_ride_through)
        fig.update_layout(autosize=True, height=height, margin={"l": 58, "r": 14, "t": 26, "b": 44}, showlegend=False,
                          font={"family": "-apple-system, Segoe UI, Arial, sans-serif", "color": PLOT_TITLE_TEXT,
                                "size": 11},
                          plot_bgcolor="#ffffff", title=None)
        fig.update_xaxes(gridcolor=PLOT_GRID_COLOR, title_standoff=4)
        fig.update_yaxes(gridcolor=PLOT_GRID_COLOR, title_standoff=4)
        return fig

    def notes_html(self, params, preset) -> str:
        notes = get_ui_spec(self.model_id).notes(params, preset)
        if not notes:
            return ""
        items = "".join(f'<li style="color:{LEVEL_STYLE[level][0]};"><b>{LEVEL_STYLE[level][1]}:</b> {escape(text)}</li>'
                        for level, text in notes)
        return f'<ul style="margin:6px 0 0 16px;padding:0;font-size:12px;">{items}</ul>'

    def page_parts(self, params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind,
                   fault_frequency_hz):
        sim = self.simulate(params, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)
        return (panel1_title_text(block_label, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz),
                self.status_html(sim, params), self.recovery_html(params, block_label, sim, block_mw, event_kind))

    def render(self, params, block_label, preset=None, block_mw=None, include_plotlyjs=True, div_id="plot",
               fill_viewport=False, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *,
               event_kind="voltage", fault_frequency_hz=FREQUENCY_EVENT_HZ) -> str:
        """The same fragment contract and element ids as `preview.perc1_dll.render_perc1_response_page`, so
        `live_update` can update it in place."""
        fig = self._preset_figure(params, block_label, preset, None if fill_viewport else 720, fault_duration_s,
                                  fault_voltage_pu, event_kind, fault_frequency_hz)
        title_text, status_html, recovery_html = self.page_parts(
            params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)
        return response_page_html(fig, title_text, status_html, recovery_html, self.notes_html(params, preset),
                                  include_plotlyjs=include_plotlyjs, div_id=div_id, fill_viewport=fill_viewport)

    def live_update(self, params, block_label, preset=None, block_mw=None, div_id="plot",
                    fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *, event_kind="voltage",
                    fault_frequency_hz=FREQUENCY_EVENT_HZ) -> str:
        """Push new data into an already-loaded page (keeps the viewer's zoom), like `build_live_update_js`."""
        fig = self._preset_figure(params, block_label, preset, None, fault_duration_s, fault_voltage_pu, event_kind,
                                  fault_frequency_hz)
        title_text, status_html, recovery_html = self.page_parts(
            params, block_label, block_mw, fault_duration_s, fault_voltage_pu, event_kind, fault_frequency_hz)
        return live_update_js(fig, title_text, status_html, recovery_html, div_id)

    def _preset_figure(self, params, block_label, preset, height, fault_duration_s, fault_voltage_pu, event_kind,
                       fault_frequency_hz):
        return self.figure(
            params, block_label, preset.envelope if preset else None, preset.label if preset else None,
            preset.overvoltage_envelope if preset else None, height=height, fault_duration_s=fault_duration_s,
            fault_voltage_pu=fault_voltage_pu, frequency_ride_through=preset.frequency_ride_through if preset else None,
            event_kind=event_kind, fault_frequency_hz=fault_frequency_hz)
