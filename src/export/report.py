"""The HTML review report: logo, badges, per-block sections and the embedded response charts."""

from __future__ import annotations

import base64
import os
from datetime import datetime
from html import escape

from plotly.offline import get_plotlyjs

from app import tokens as t
from app.config import (
    CURENT_LOGO_PATH,
    ENGINEERING_TOOL_NOTICE,
    LOGO_FILENAME_CANDIDATES,
    TVA_LOGO_PATH,
)
from export.dyr import (
    USER_DEFINED_ID,
    block_model_id,
    build_dyr_text,
    clod_model_name,
    get_clod_params,
    get_it_params,
    get_vfd_params,
    is_user_defined,
    user_defined_block_html,
)
from load_models.base import (
    FAULT_DURATION,
    FAULT_START,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
    format_con,
)
from load_models.clod.cons import CLOD_DISPLAY_FIELDS
from preview.model import Event, build_preview
from preview.report_page import REPORT_BLOCK_CSS, font_face_css, render_report_block

APP_NAME = "PERC Studio"
# What a block's model is called in the report: its own name, never a generic "PERC1".
MODEL_NAMES = {"perc1_dll": "PERC1 DLL", "perc1_standard": "PERC1 standard", "perc2_standard": "PERC2 standard",
               "perc2_dll": "PERC2 DLL v2.3", USER_DEFINED_ID: "user-defined"}
# The same models with the PSS/E versions they target, for the block headings.
MODEL_FULL_NAMES = {**MODEL_NAMES, "perc1_standard": "PERC1 standard (PSS/E 36.7+)",
                    "perc2_standard": "PERC2 standard (PSS/E 36.7+)"}


def _local_logo_path():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base_dir = os.getcwd()
    for name in LOGO_FILENAME_CANDIDATES:
        candidate = os.path.join(base_dir, name)
        if os.path.exists(candidate):
            return candidate
    return None


def get_logo_bytes_and_mime(session_state):
    local_path = _local_logo_path()
    if local_path:
        ext = os.path.splitext(local_path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}.get(ext, "image/png")
        with open(local_path, "rb") as f:
            return f.read(), mime
    if session_state.get("logo_bytes"):
        return session_state["logo_bytes"], session_state.get("logo_mime", "image/png")
    if os.path.exists(CURENT_LOGO_PATH):
        with open(CURENT_LOGO_PATH, "rb") as f:
            return f.read(), "image/png"
    return None, None


def _image_data_uri(path, mime="image/png"):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"






def _badge(label, bg, fg):
    return (f'<span class="badge" style="background:{bg};color:{fg};">{escape(label)}</span>')


def _confidence_badge(label):
    if "Placeholder" in label:
        return _badge(label, t.TRIP_TINT, t.TRIP_TEXT)
    if "Field-validated" in label:
        return _badge(label, t.BRAND_TINT, t.BRAND_DARK)
    return _badge(label, t.WARNING_BG, t.WARNING_TEXT)


def _preset_status_badge(preset):
    if preset is None:
        return ""
    if preset.status.startswith("Adopted"):
        return _badge(preset.status, t.BRAND_TINT, t.BRAND_DARK)
    return _badge(preset.status, t.WARNING_BG, t.WARNING_TEXT)


def _disturbance_note_html(session_state, block, preset):
    """The caption under a block's chart in the saved report: which event was
    simulated, and what the two tolerance maps compare against."""
    if is_user_defined(session_state, block):
        return ""
    duration = session_state.get(f"{block}_fault_duration_s", FAULT_DURATION)
    if session_state.get(f"{block}_event_kind", "voltage") == "frequency":
        frequency = session_state.get(f"{block}_fault_frequency_hz", FREQUENCY_EVENT_HZ)
        event = (f"system frequency {'drops' if frequency < NOMINAL_FREQUENCY_HZ else 'rises'} to "
                 f"{frequency:.2f} Hz for {duration:.0f} s starting at t={FAULT_START}s (a generation/load "
                 "imbalance), exercising the FUFTP/FOFTP frequency trip stages")
    else:
        voltage = session_state.get(f"{block}_fault_voltage_pu", V_FAULT)
        event = (f"voltage {'rises' if voltage > 1.0 else 'drops'} to {voltage:.2f} pu for "
                 f"{duration * 1000:.0f} ms ({duration * 60:.1f} cycles at 60 Hz) starting at t={FAULT_START}s, "
                 "representing a normally-cleared BPS fault - the event type NERC's Level 3 Alert identifies as "
                 "triggering computational load reductions")
    if preset is None:
        against = "no ride-through preset (none was selected for this block)"
    elif preset.frequency_ride_through is None:
        against = (f"the {preset.label} voltage envelope; {preset.label} publishes no frequency ride-through "
                   "table, so the frequency map shows this block's own trip stages only")
    else:
        against = f"the {preset.label} voltage envelope and frequency ride-through table"
    return (f'<p class="caption">Simulated disturbance: {event}. The tolerance chart compares every trip stage '
            f"against {against}. This is an illustrative fixed scenario, not a "
            "substitute for an EMT/stability simulation.</p>")


def _table(headers, rows, css_class=""):
    head = "".join(f"<th>{h}</th>" for h in headers)
    return f'<div class="table-card"><table class="{css_class}"><tr>{head}</tr>{rows}</table></div>'


def _kv_rows(pairs):
    return "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)


REPORT_CSS = f"""
  :root {{
    --brand: {t.BRAND}; --brand-dark: {t.BRAND_DARK}; --brand-text: {t.BRAND_TEXT}; --brand-tint: {t.BRAND_TINT};
    --text: {t.TEXT}; --muted: {t.TEXT_MUTED}; --card-border: {t.CARD_BORDER}; --hairline: {t.HAIRLINE};
    --ground: {t.GROUND}; --surface: {t.SURFACE}; --subtle: {t.SURFACE_SUBTLE};
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: {t.CSS_FONT_SANS}; font-size: 13px; margin: 0; color: var(--text); line-height: 1.5; background: var(--ground); }}
  .app-bar {{ display: flex; align-items: center; gap: 12px; background: var(--surface); border-bottom: 1px solid var(--card-border);
              padding: 0 28px; min-height: {t.APP_BAR_HEIGHT}px; }}
  .app-bar img {{ height: 34px; }}
  .app-bar .logo-fallback {{ font-weight: 600; color: var(--brand); border: 1px dashed {t.CONTROL_BORDER}; border-radius: 4px; padding: 2px 10px; font-size: 11px; }}
  .app-bar h1 {{ margin: 0; font-size: 16px; font-weight: 600; line-height: 1.2; }}
  .app-bar .subtitle {{ font-size: 11px; color: var(--muted); }}
  .app-bar .tag {{ margin-left: auto; font-size: 11px; color: var(--muted); border: 1px solid {t.CONTROL_BORDER}; border-radius: 11px; padding: 2px 10px; background: var(--surface); }}
  .report-container {{ max-width: 1180px; margin: 0 auto; padding: 8px 28px 40px; }}
  .meta {{ color: var(--muted); font-size: 12px; margin: 14px 0 0; }}
  h2 {{ margin: 30px 0 6px; font-size: 16px; font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid var(--card-border); }}
  h2 small {{ font-weight: 400; color: var(--muted); font-size: 12px; margin-left: 6px; }}
  .table-card {{ background: var(--surface); border: 1px solid var(--card-border); border-radius: {t.RADIUS_CARD}px; margin: 8px 0 14px; overflow: hidden; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 7px 14px; text-align: left; border-bottom: 1px solid var(--hairline); vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  th {{ background: var(--subtle); color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 1px solid var(--card-border); }}
  td:last-child {{ font-family: {t.CSS_FONT_MONO}; font-size: 12px; }}
  .param-table td:first-child {{ width: 60%; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: {t.RADIUS_TAG}px; font-size: 11px; font-weight: 600; }}
  .caption {{ font-size: 12px; color: var(--muted); margin: 8px 0 0; }}
  .callout {{ border-radius: {t.RADIUS_CARD}px; padding: 10px 14px; margin: 16px 0 0; }}
  .callout.warn {{ background: {t.TRIP_BANNER}; border: 1px solid {t.TRIP_BANNER_BORDER}; color: {t.TRIP_TEXT}; }}
  .callout.notice {{ background: {t.EDITED_TINT}; border: 1px solid {t.EDITED_BORDER}; color: {t.EDITED_TEXT}; font-size: 12px; }}
  pre.dyr {{ background: var(--surface); border: 1px solid var(--card-border); border-radius: {t.RADIUS_CARD}px; padding: 14px;
             overflow-x: auto; font-family: {t.CSS_FONT_MONO}; font-size: 12px; line-height: 1.5; margin: 8px 0 0; }}
  .footer {{ margin-top: 34px; font-size: 12px; color: var(--muted); border-top: 1px solid var(--card-border); padding-top: 12px; }}
  .brand-footer {{ margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--card-border); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
  .brand-footer-logos {{ display: flex; align-items: center; gap: 20px; }}
  .brand-footer-logos img {{ height: 28px; }}
  .brand-footer-text {{ font-size: 11px; color: var(--muted); max-width: 440px; }}
  @media (max-width: 760px) {{ .app-bar, .report-container {{ padding-left: 14px; padding-right: 14px; }} }}
"""


def _model_name(session_state, block, full=False):
    return (MODEL_FULL_NAMES if full else MODEL_NAMES).get(block_model_id(session_state, block), "PERC1 DLL")


def build_html_report(session_state):
    total_mw = session_state["total_mw"]
    mw_it = total_mw * session_state["pct_it"] / 100.0
    mw_vfd = total_mw * session_state["pct_cooling_vfd"] / 100.0
    mw_motor = total_mw * session_state["pct_cooling_motor"] / 100.0
    mw_other = total_mw * session_state["pct_other"] / 100.0

    it_params = get_it_params(session_state)
    vfd_params = get_vfd_params(session_state) if session_state["include_vfd_block"] else None
    clod_params = get_clod_params(session_state) if session_state["include_motor_block"] else None

    it_preset = session_state.get("it_preset")
    vfd_preset = session_state.get("vfd_preset")

    def param_rows(p, block="it"):
        from editor.model_ui import get_ui_spec

        fields = get_ui_spec(block_model_id(session_state, block)).display_fields
        return "".join(
            f'<tr><td title="{tooltip}">{label}</td><td>{format_con(p[name])}</td></tr>'
            for name, label, tooltip in fields
        )

    def response_html(block, params, label, preset, mw):
        """The block's three response cards, drawn from the same preview model as the app's live charts."""
        from editor.model_ui import get_ui_spec

        model_id = block_model_id(session_state, block)
        event = Event(
            kind=session_state.get(f"{block}_event_kind", "voltage"),
            duration_s=session_state.get(f"{block}_fault_duration_s", FAULT_DURATION),
            voltage_pu=session_state.get(f"{block}_fault_voltage_pu", V_FAULT),
            frequency_hz=session_state.get(f"{block}_fault_frequency_hz", FREQUENCY_EVENT_HZ))
        result = build_preview(model_id, params, event, preset=preset, block_mw=mw,
                               block_label=f"{label} · {_model_name(session_state, block)}")
        return render_report_block(result, preset, block, notes=get_ui_spec(model_id).notes(params, preset))

    def block_body(block, params, label, preset, mw):
        """The parameter table and response charts of a block, or the user-defined paragraph."""
        if is_user_defined(session_state, block):
            return user_defined_block_html(session_state, block)
        return (_table(("Parameter", "Value"), param_rows(params, block), "param-table")
                + response_html(block, params, label, preset, mw)
                + _disturbance_note_html(session_state, block, preset))

    def preset_line(preset):
        if preset is None:
            return ""
        return (f"<p>Ride-through preset: <strong>{preset.label}</strong> {_preset_status_badge(preset)}<br>"
                f'<span class="caption">{preset.citation}</span></p>')

    it_conf = _confidence_badge(session_state["it_data_confidence"])
    vfd_conf = _confidence_badge(session_state["vfd_data_confidence"]) if session_state["include_vfd_block"] else ""

    vfd_section = ""
    if session_state["include_vfd_block"]:
        vfd_section = f"""
        <h2>Cooling VFD Load Block <small>({mw_vfd:.2f} MW, Load ID '{session_state['load_id_vfd']}', model {_model_name(session_state, "vfd", full=True)})</small></h2>
        <p>Data confidence: {vfd_conf}</p>
        {preset_line(vfd_preset)}
        {block_body("vfd", vfd_params, "Cooling VFD block", vfd_preset, mw_vfd)}
        """

    motor_section = ""
    if session_state["include_motor_block"]:
        motor_rows = "".join(f"<tr><td>{label}</td><td>{clod_params[name]:.1f}</td></tr>" for name, label in CLOD_DISPLAY_FIELDS)
        motor_rows += f"<tr><td>Remainder — voltage-sensitive load (constant Z/I)</td><td>{100 - sum(clod_params.values()):.1f}</td></tr>"
        motor_section = f"""
        <h2>Cooling Motor Load Block <small>({mw_motor:.2f} MW, Load ID '{session_state['load_id_motor']}', model {clod_model_name(session_state).split()[0]})</small></h2>
        <p>Facility type - {session_state['motor_facility_type']};
        significant lighting/office load - {'Yes' if session_state['motor_has_lighting'] else 'No'}</p>
        {_table(("Parameter", "Value (%)"), motor_rows, "param-table")}
        <p class="caption">No trip/ride-through curve is plotted for this block: {clod_model_name(session_state).split()[0]}'s
        motor stall/trip behavior is governed by fixed internal electromechanical parameters
        (inertia, stall voltage/time), not by user-configurable CONs like the PERC models' cease and reconnect
        settings, so there is no user-supplied threshold to plot here.</p>
        """

    gen_section = ""
    if session_state["has_onsite_gen"]:
        gen_section = f"""
        <h2>On-Site Generation / BESS (Informational)</h2>
        <p>Reported present. Not represented in the .dyr load records - requires a separate
        generator/BESS dynamic model if operated in parallel with the BPS.</p>
        <p><strong>Notes:</strong> {session_state['gen_notes'] or '(none provided)'}</p>
        """

    warn_banner = ""
    if "Placeholder" in session_state["it_data_confidence"] or (session_state["include_vfd_block"] and "Placeholder" in session_state["vfd_data_confidence"]):
        warn_banner = """
        <div class="callout warn">
        <strong>Data quality warning:</strong> One or more load blocks are using placeholder values
        rather than field-validated customer data. These should not be
        relied on for a final TPL-level planning study.
        </div>
        """

    _report_logo_bytes, _report_logo_mime = get_logo_bytes_and_mime(session_state)
    if _report_logo_bytes:
        logo_b64 = base64.b64encode(_report_logo_bytes).decode("ascii")
        logo_html = f'<img src="data:{_report_logo_mime};base64,{logo_b64}" alt="Logo" />'
    else:
        logo_html = '<div class="logo-fallback">CURENT</div>'

    _curent_footer_logo = _image_data_uri(CURENT_LOGO_PATH)
    _tva_footer_logo = _image_data_uri(TVA_LOGO_PATH)
    brand_footer_logos = "".join(
        f'<img src="{uri}" alt="{alt}" />'
        for uri, alt in ((_curent_footer_logo, "CURENT logo"), (_tva_footer_logo, "TVA logo"))
        if uri
    )

    # The models this report actually covers, in block order, each named once.
    blocks = ["it"] + (["vfd"] if session_state["include_vfd_block"] else [])
    model_names = list(dict.fromkeys(_model_name(session_state, b) for b in blocks))
    if session_state["include_motor_block"]:
        model_names.append("CLOD")
    platform_models = " + ".join(model_names)

    # Screening models one load, so its report leaves out the facility
    # breakdown and every non-screened section; Post-Commissioning gets them all.
    if session_state.get("report_kind") == "screening":
        report_title = "Screening Report"
        it_block_label = "Load"
        it_heading = f"{_model_name(session_state, 'it')} Load Block"
        mvar = session_state.get("reactive_mvar")
        summary_rows = _kv_rows([
            ("Load name", session_state["facility_name"]),
            ("Bus", f"{session_state['bus_number']} ({session_state['bus_name']})"),
            ("Active power", f"{total_mw:.2f} MW"),
            *([("Reactive power", f"{mvar:.2f} Mvar")] if mvar is not None else []),
        ])
        summary_sections = f"<h2>Load</h2>{_table(('Field', 'Value'), summary_rows)}"
    else:
        report_title = "Data Center Load Model Report"
        it_block_label = "IT/UPS block"
        it_heading = "IT / UPS Load Block"
        summary_rows = _kv_rows([
            ("Facility name", session_state["facility_name"]),
            ("Point of interconnection bus", f"{session_state['bus_number']} ({session_state['bus_name']})"),
            ("Total facility load (max expected)", f"{total_mw:.2f} MW"),
            ("Power factor", session_state["power_factor"]),
            ("Primary use case", f"{session_state['use_case']} ({session_state['use_case_pct']}%)"),
            ("Prepared by", session_state["prepared_by"] or "(not specified)"),
            ("Data source note", session_state["data_source_note"] or "(not specified)"),
        ])
        composition_rows = "".join(
            f"<tr><td>{name}</td><td>{pct}%</td><td>{mw:.2f}</td></tr>"
            for name, pct, mw in (("IT / compute", session_state["pct_it"], mw_it),
                                  ("Cooling (VFD)", session_state["pct_cooling_vfd"], mw_vfd),
                                  ("Cooling (motor)", session_state["pct_cooling_motor"], mw_motor),
                                  ("Other", session_state["pct_other"], mw_other)))
        summary_sections = (f"<h2>Facility Summary</h2>{_table(('Field', 'Value'), summary_rows)}"
                            f"<h2>Load Composition</h2>{_table(('Block', '% of Total', 'MW'), composition_rows)}")

    facility = session_state["facility_name"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{report_title} - {facility} - {APP_NAME}</title>
<style>
{font_face_css()}
{REPORT_CSS}
{REPORT_BLOCK_CSS}
</style>
<script>{get_plotlyjs()}</script>
</head>
<body>
<div class="app-bar">
  {logo_html}
  <div>
    <h1>{report_title}</h1>
    <div class="subtitle">{facility} · {platform_models}</div>
  </div>
  <span class="tag">{APP_NAME}</span>
</div>
<div class="report-container">
  <p class="meta">Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')} | Target platform: PSS/E .dyr ({platform_models})</p>
  {warn_banner}
  {summary_sections}
  <h2>{it_heading} <small>({mw_it:.2f} MW, Load ID '{session_state['load_id_it']}', model {_model_name(session_state, "it", full=True)})</small></h2>
  <p>Data confidence: {it_conf}</p>
  {preset_line(it_preset)}
  {block_body("it", it_params, it_block_label, it_preset, mw_it)}
  {vfd_section}
  {motor_section}
  {gen_section}
  <h2>Generated PSS/E .dyr Content</h2>
  <pre class="dyr">{build_dyr_text(session_state)}</pre>
  <div class="footer">
    Generated by {APP_NAME}. Each block's parameters come from its selected
    ride-through preset or generic tier, plus any values edited in the Advanced editor, using
    the documented rule set in the app's Documentation tab - not an official NERC or vendor
    default table. Confirm CONs
    order against your installed PSS/E Model Library before use in a planning study. Reflects
    NERC Level 3 Alert guidance on computational load modeling (Essential Action to Industry:
    Computational Load Modeling, Studies, Instrumentation, Commissioning, Operations,
    Protection, and Control).
  </div>
  <div class="callout notice"><strong>Engineering tool notice:</strong> {ENGINEERING_TOOL_NOTICE}</div>
  <div class="brand-footer">
    <div class="brand-footer-logos">{brand_footer_logos}</div>
    <div class="brand-footer-text">Developed by CURENT (Center for Ultra-Wide-Area Resilient Electric
    Energy Transmission Networks, University of Tennessee, Knoxville) in partnership with the
    Tennessee Valley Authority.</div>
  </div>
</div>
</body>
</html>
"""
    return html
