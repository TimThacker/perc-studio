"""The .dyr text the app exports: which model each block uses, its parameters, and the assembled file."""

from __future__ import annotations

import os
from datetime import datetime

from load_models import get_load_model
from load_models.base import (
    get_record_scope,
    record_number,
)
from load_models.clod.cons import derive_clod_params
from load_models.clod.dyr import clod_record

USER_DEFINED_ID = "user_defined"


def block_model_id(session_state, block):
    """The load model a block uses: the DLL variant unless the UI chose another."""
    return session_state.get(f"{block}_model_id", "perc1_dll")


def is_user_defined(session_state, block):
    """A user-defined (black-box) block: its records come from the user's own .dyr, unedited."""
    return block_model_id(session_state, block) == USER_DEFINED_ID


# The PSS/E 36.7 built-in models (PERC1 standard, PERC2 standard).
STANDARD_STYLE_MODELS = ("perc1_standard", "perc2_standard")
# Models whose CONs come from the editor spec's defaults: the 36.7 models and the PERC2 DLL v2.3. The PERC1 DLL
# overlays the editor's values on the model's own default CONs.
_EDITOR_SOURCED_MODELS = (*STANDARD_STYLE_MODELS, "perc2_dll")


def _standard_params(session_state, block):
    from editor.model_ui import get_ui_spec

    spec = get_ui_spec(block_model_id(session_state, block))
    return {k: session_state.get(f"{block}_adv_{k}", v) for k, v in spec.default_params().items()}


def get_it_params(session_state):
    if is_user_defined(session_state, "it"):
        return {}
    if block_model_id(session_state, "it") in _EDITOR_SOURCED_MODELS:
        return _standard_params(session_state, "it")
    defaults = get_load_model("perc1_dll").default_cons
    return {k: session_state.get(f"it_adv_{k}", v) for k, v in defaults.items()}


def get_vfd_params(session_state):
    if is_user_defined(session_state, "vfd"):
        return {}
    if block_model_id(session_state, "vfd") in _EDITOR_SOURCED_MODELS:
        return _standard_params(session_state, "vfd")
    defaults = get_load_model("perc1_dll").default_cons
    return {k: session_state.get(f"vfd_adv_{k}", v) for k, v in defaults.items()}


def get_clod_params(session_state):
    derived = derive_clod_params(session_state["motor_facility_type"], session_state["motor_has_lighting"])
    if session_state["motor_advanced"]:
        keymap = {
            "PC_LM": "clod_adv_lm",
            "PC_SM": "clod_adv_sm",
            "PC_TX": "clod_adv_tx",
            "PC_DL": "clod_adv_dl",
            "PC_CP": "clod_adv_cp",
        }
        return {k: session_state.get(keymap[k], v) for k, v in derived.items()}
    return derived


def clod_model_name(session_state):
    """CLODBL/CLODOW/CLODZN/CLODAR/CLODAL for this export's record scope."""
    return get_record_scope(session_state.get("record_scope", "bus")).model_name("CLOD")


def _standard_blocks(session_state):
    """The PSS/E 36.7 built-in models (PERC1 standard, PERC2 standard) the exported blocks use."""
    blocks = ("it", "vfd") if session_state.get("include_vfd_block", True) else ("it",)
    return sorted({block_model_id(session_state, b) for b in blocks} & set(STANDARD_STYLE_MODELS))


def _record_scope(session_state):
    """(scope id, record first field) for this export - bus-scoped unless the
    UI's "Record format" selector says otherwise."""
    scope = session_state.get("record_scope", "bus")
    number = record_number(scope, session_state.get("bus_number", 100001), session_state.get("subsystem_number"))
    return scope, number


def _record_scope_comment(scope, number):
    record_scope = get_record_scope(scope)
    if record_scope.id == "bus":
        return None
    target = "every load in the case" if record_scope.id == "all" else f"{record_scope.label.lower()} {number}"
    return (f"/ Record format: {record_scope.label} (PERC{record_scope.suffix}, IT={record_scope.it}) - "
            f"applies to loads with the given ID across {target}.")


def block_dyr_record_text(session_state, block, number, load_id, params, scope):
    """One block's record(s): from whichever PERC1 model the block uses, or - for a user-defined block - the
    user's own records, attached to this load (first field and load ID only; CONs and ICONs unchanged)."""
    if is_user_defined(session_state, block):
        from editor.user_model import dyr_block_text

        return dyr_block_text(session_state, block, number, load_id)
    return get_load_model(block_model_id(session_state, block)).build_dyr_record(number, load_id, params, scope=scope)


def user_defined_block_html(session_state, block):
    """The report's paragraph for a user-defined block, in place of a parameter table and a response chart."""
    import html as _html

    source = _html.escape(session_state.get(f"{block}_user_source") or "a user .dyr file")
    dlls = ", ".join(_html.escape(os.path.basename(d)) for d in session_state.get(f"{block}_user_dlls", [])) or "none listed"
    header = _html.escape(session_state.get(f"{block}_user_header", ""))
    return (f"<p><strong>User-defined model</strong> (not edited or simulated by this app): {source}"
            f"{f' (originally {header})' if header else ''}. DLLs: {dlls}. Its records are written to the .dyr as "
            "they are in the file, attached to this block's load; check how it rides through in Black-Box "
            "Validation.</p>")


def build_dyr_text(session_state):
    total_mw = session_state["total_mw"]
    mw_it = total_mw * session_state["pct_it"] / 100.0
    mw_vfd = total_mw * session_state["pct_cooling_vfd"] / 100.0
    mw_motor = total_mw * session_state["pct_cooling_motor"] / 100.0

    it_params = get_it_params(session_state)
    vfd_params = get_vfd_params(session_state) if session_state["include_vfd_block"] else None
    clod_params = get_clod_params(session_state) if session_state["include_motor_block"] else None

    lines = []
    lines.append(f"/ .dyr file generated by PERC Studio on {datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"/ Facility: {session_state['facility_name']}  |  POI Bus: {session_state['bus_number']} ({session_state['bus_name']})")
    lines.append(f"/ Total facility load: {total_mw:.2f} MW  |  Use case: {session_state['use_case']} ({session_state['use_case_pct']}%)")
    lines.append(f"/ IT/UPS block confidence: {session_state['it_data_confidence']}")
    if session_state["include_vfd_block"]:
        lines.append(f"/ Cooling VFD block confidence: {session_state['vfd_data_confidence']}")
    lines.append("/ VERIFY CONs order against your installed PSS/E Model Library before use.")
    if standard := _standard_blocks(session_state):
        names = " and ".join({"perc1_standard": "PERC1 standard (PERCxx1U)", "perc2_standard": "PERC2 standard (PERCxx2U)"}[m]
                             for m in standard)
        lines.append(f"/ {names} blocks (PSS/E 36.7+) are components of a composite load: each has a")
        lines.append("/ MAINxx10 record above it and needs no DLL. They take the load's MW/Mvar from the power flow.")
        lines.append("/ PERC1 DLL and CLOD blocks are USRLOD models and carry no MW/Mvar of their own.")
    else:
        lines.append("/ PERC1 and CLOD are both USRLOD models: neither carries MW/Mvar itself.")
    if any(block_model_id(session_state, b) == "perc2_dll"
           for b in (("it", "vfd") if session_state.get("include_vfd_block", True) else ("it",))):
        lines.append("/ PERC2 DLL v2.3 blocks (179 CONs) need PERC2_v35_v2p3.dll or PERC2_v36_v2p3.dll, not the PERC1")
        lines.append("/ DLL: both register PERCBL, so a case loads one or the other. RAMPA/RAMPUA last CON x LFM.")
    lines.append("/ Ensure a static Load record with matching bus/ID and MW/Mvar exists in")
    lines.append("/ the power flow (.raw case) for every block below.")
    scope, number = _record_scope(session_state)
    if (comment := _record_scope_comment(scope, number)) is not None:
        lines.append(comment)
    lines.append("/")
    lines.append(f"/ --- IT / UPS load block ({mw_it:.2f} MW) ---")
    lines.append(block_dyr_record_text(session_state, "it", number, session_state["load_id_it"], it_params, scope))

    if session_state["include_vfd_block"] and mw_vfd > 0:
        lines.append(f"/ --- Cooling VFD load block ({mw_vfd:.2f} MW) ---")
        lines.append(block_dyr_record_text(session_state, "vfd", number, session_state["load_id_vfd"], vfd_params, scope))

    if session_state["include_motor_block"] and mw_motor > 0:
        lines.append(f"/ --- Cooling motor load block ({mw_motor:.2f} MW) - {clod_model_name(session_state)} ---")
        lines.append(clod_record(number, session_state["load_id_motor"], clod_params, scope))

    if session_state["has_onsite_gen"]:
        lines.append("/")
        lines.append("/ NOTE: Facility reports on-site generation/BESS. This is NOT represented")
        lines.append("/ in the load records above. Model separately as a generator/BESS record")
        lines.append(f"/ if operated in parallel with the BPS. Notes: {session_state['gen_notes']}")

    lines.append("/")
    lines.append(f"/ Prepared by: {session_state['prepared_by']}")
    lines.append(f"/ Data source: {session_state['data_source_note']}")
    return "\n".join(lines) + "\n"

