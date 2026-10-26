"""The PERC2 DLL v2.3 response page for the report: the PERC1 DLL's page, run through the v2.3 simulator.

v2.3 is the PERC1 DLL with six CONs appended, so the page is `preview.perc1_dll.render_perc1_response_page` unchanged. It
gets `perc1_equivalent(cons)` (RAMPA and RAMPUA in seconds, CON x LFM) to draw the stages, and the model's own
simulate hooks (`load_models.perc2_dll`) for the response, so the ramp rule and momentary cessation come from one
place. The editor's notes (what `validate_cons` flags, and that momentary cessation is on) go below the recovery strip.
"""

from __future__ import annotations

from html import escape

from editor.model_ui import PERC2_DLL_MODEL_ID, get_ui_spec
from load_models import get_load_model
from load_models.base import FAULT_DURATION, FREQUENCY_EVENT_HZ, V_FAULT
from load_models.perc2_dll.simulation import perc1_equivalent
from preview.frame import LEVEL_STYLE
from preview.perc1_dll import build_live_update_js, render_perc1_response_page

MODEL_LABEL = "PERC2 DLL v2.3"


def simulate_perc2_dll_event(cons, event_kind, fault_duration_s, fault_voltage_pu=V_FAULT,
                             fault_frequency_hz=FREQUENCY_EVENT_HZ):
    """`simulate_perc1_event`'s contract, through the PERC2 DLL model's `simulate` / `simulate_frequency`."""
    model = get_load_model(PERC2_DLL_MODEL_ID)
    if event_kind == "frequency":
        return model.simulate_frequency(cons, fault_duration_s, fault_frequency_hz)
    return model.simulate(cons, fault_duration_s, fault_voltage_pu)


def _simulator(cons):
    """The page's `simulate_event`: it is handed the seconds-converted CONs, but runs the v2.3 CONs themselves (the
    model converts the ramps on its own)."""
    def run(_params, event_kind, fault_duration_s, fault_voltage_pu=V_FAULT, fault_frequency_hz=FREQUENCY_EVENT_HZ):
        return simulate_perc2_dll_event(cons, event_kind, fault_duration_s, fault_voltage_pu, fault_frequency_hz)
    return run


def notes_html(cons, preset) -> str:
    notes = get_ui_spec(PERC2_DLL_MODEL_ID).notes(cons, preset)
    if not notes:
        return ""
    items = "".join(f'<li style="color:{LEVEL_STYLE[level][0]};"><b>{LEVEL_STYLE[level][1]}:</b> {escape(text)}</li>'
                    for level, text in notes)
    return f'<ul class="perc2-dll-notes" style="margin:6px 0 0 16px;padding:0;font-size:12px;">{items}</ul>'


def _label(block_label):
    return f"{block_label} · {MODEL_LABEL}" if block_label else MODEL_LABEL


def _preset_kwargs(preset) -> dict:
    return {"envelope": preset.envelope if preset else None, "envelope_label": preset.label if preset else None,
            "overvoltage_envelope": preset.overvoltage_envelope if preset else None,
            "frequency_ride_through": preset.frequency_ride_through if preset else None}


def render_perc2_dll_response_page(cons, block_label, preset=None, block_mw=None, include_plotlyjs=True,
                                   div_id="plot", fill_viewport=False, fault_duration_s=FAULT_DURATION,
                                   fault_voltage_pu=V_FAULT, *, event_kind="voltage",
                                   fault_frequency_hz=FREQUENCY_EVENT_HZ) -> str:
    """The same fragment contract and element ids as `preview.perc1_dll.render_perc1_response_page`."""
    return render_perc1_response_page(
        perc1_equivalent(cons), _label(block_label), block_mw=block_mw, include_plotlyjs=include_plotlyjs,
        div_id=div_id, fill_viewport=fill_viewport, fault_duration_s=fault_duration_s,
        fault_voltage_pu=fault_voltage_pu, event_kind=event_kind, fault_frequency_hz=fault_frequency_hz,
        simulate_event=_simulator(cons), notes=notes_html(cons, preset), **_preset_kwargs(preset))


def build_perc2_dll_live_update_js(cons, block_label, preset=None, block_mw=None, div_id="plot",
                                   fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT, *,
                                   event_kind="voltage", fault_frequency_hz=FREQUENCY_EVENT_HZ) -> str:
    return build_live_update_js(
        perc1_equivalent(cons), _label(block_label), block_mw=block_mw, div_id=div_id,
        fault_duration_s=fault_duration_s, fault_voltage_pu=fault_voltage_pu, event_kind=event_kind,
        fault_frequency_hz=fault_frequency_hz, simulate_event=_simulator(cons), **_preset_kwargs(preset))
