"""Per-case and aggregate HTML/JSON report builders for the perc-studio
validation loop (generate -> run -> validate -> report). Kept separate from
export/report.py: this is dev-CLI-specific output, not part of the live app's
GUI export path.

`build_sweep_summary_json` is the primary artifact for agent consumption;
`build_sweep_summary_html` is always rendered from the same
CaseValidationReport data, never a second independent computation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from load_models.base import format_con


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _con_table_html(model, cons: dict) -> str:
    """The model's own display fields; a model with no display fields lists
    every CON instead."""
    fields = model.display_fields or tuple((name, name) for name in model.con_names)
    rows = "".join(
        f'<tr><td title="{rest[0] if rest else name}">{label}</td><td>{format_con(cons[name])}</td></tr>'
        for name, label, *rest in fields
    )
    return f'<table class="con-table"><tbody>{rows}</tbody></table>'


def _generic_result_figure(result, block_label: str, height=None):
    """The disturbance (bus voltage, or frequency for a frequency event) and
    active power vs. time straight from a SimulationResult - used for any load
    model without its own `result_figure` hook, and for every frequency event."""
    if result.frequency_hz is not None:
        top_title, top_y, top_name = f"{block_label}: frequency (Hz)", result.frequency_hz, "Frequency (Hz)"
    else:
        top_title, top_y, top_name = f"{block_label}: bus voltage (pu)", result.voltage_pu, "Voltage (pu)"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=(top_title, "Active power (pu)"))
    fig.add_trace(go.Scatter(x=result.time_s, y=top_y, mode="lines", name=top_name), row=1, col=1)
    fig.add_trace(go.Scatter(x=result.time_s, y=result.active_power_pu, mode="lines", name="Power (pu)"),
                  row=2, col=1)
    if result.tripped and result.trip_time_s is not None:
        fig.add_vline(x=result.trip_time_s, line_dash="dot", line_color="#c0392b")
    fig.update_xaxes(title_text="Time (s)", row=2, col=1)
    fig.update_layout(height=height or 600, showlegend=False)
    return fig


def _verdict_banner_html(point) -> str:
    color = "#1a7a3c" if point.passed else "#c0392b"
    label = "PASS" if point.passed else "FAIL"
    return f"""
    <div style="border:1px solid #c7d2de;border-radius:6px;padding:12px 16px;margin:12px 0;">
      <h3 style="margin:0 0 8px;color:{color};">{label}</h3>
      <p style="margin:0 0 4px;color:#5b6b7c;">Scenario <code>{point.scenario_id}</code></p>
      <p style="margin:0 0 4px;">Expected: <strong>{"trip" if point.expected_trip else "no trip"}</strong>
         &nbsp;|&nbsp; Actual: <strong>{"trip" if point.actual_trip else "no trip"}</strong></p>
      {f'<p style="margin:0;color:#c0392b;">{point.notes}</p>' if point.notes else ""}
    </div>
    """


def build_case_report_html(case, block_name: str, scenario, result, point, *, envelope=None,
                            overvoltage_envelope=None) -> str:
    """One (case, block, scenario) test point's report: the response figure
    (real/mock SimulationResult) + a pass/fail banner + the block's CON
    table + the scenario's expected-behavior reasoning. One of these is
    written per scenario in a sweep - see the output/<run_id>/reports/
    convention in src/dev/cli/README.md."""
    block = case.block(block_name)
    model = block.model
    if model.result_figure is not None and scenario.event_kind == "voltage":
        fig = model.result_figure(
            result, block.cons, block_name, envelope=envelope, overvoltage_envelope=overvoltage_envelope, height=900,
        )
    else:
        fig = _generic_result_figure(result, block_name)
    figure_html = fig.to_html(include_plotlyjs="cdn", full_html=False, config={"displaylogo": False})
    banner_html = _verdict_banner_html(point)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>perc-studio case report - {case.case_id} / {scenario.id}</title></head>
<body style="font-family:-apple-system, Segoe UI, Arial, sans-serif; margin:24px;">
  <h1>Case report: {case.case_id}</h1>
  <p>Generated {_now_iso()}</p>
  {banner_html}
  {figure_html}
  <h3>Scenario reasoning</h3>
  <p>{point.expected_reason}</p>
  <h3>{block_name} block CONs ({model.label})</h3>
  {_con_table_html(model, block.cons)}
</body></html>
"""


def build_sweep_summary_json(case_reports: list) -> dict:
    """The primary machine-readable artifact for a sweep run."""
    total = len(case_reports)
    passed = sum(1 for r in case_reports if r.all_passed)
    return {
        "generated_at": _now_iso(),
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "all_passed": passed == total,
        "reports": [r.to_dict() for r in case_reports],
    }


def build_sweep_summary_html(sweep_id: str, case_reports: list, generated_at: str | None = None) -> str:
    """Aggregate pass/fail table across every case x scenario in a sweep -
    always rendered from the same CaseValidationReport list
    build_sweep_summary_json uses, never a second independent computation."""
    generated_at = generated_at or _now_iso()
    total = len(case_reports)
    passed = sum(1 for r in case_reports if r.all_passed)

    rows = []
    for r in case_reports:
        status = "PASS" if r.all_passed else "FAIL"
        color = "#1a7a3c" if r.all_passed else "#c0392b"
        scenario_summary = ", ".join(
            f"{p.scenario_id}={'PASS' if p.passed else 'FAIL'}" for p in r.points
        )
        rows.append(
            f'<tr><td>{r.case_id}</td><td>{r.block_name}</td><td>{r.preset_id or ""}</td>'
            f'<td style="color:{color};font-weight:bold;">{status}</td><td>{scenario_summary}</td></tr>'
        )

    overall = "ALL PASSED" if passed == total else f"{total - passed} of {total} FAILED"
    overall_color = "#1a7a3c" if passed == total else "#c0392b"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>perc-studio sweep summary - {sweep_id}</title></head>
<body style="font-family:-apple-system, Segoe UI, Arial, sans-serif; margin:24px;">
  <h1>Sweep summary: {sweep_id}</h1>
  <p>Generated {generated_at}</p>
  <h2 style="color:{overall_color};">{overall}</h2>
  <table style="border-collapse:collapse;width:100%;">
    <thead><tr><th>Case</th><th>Block</th><th>Preset</th><th>Verdict</th><th>Scenarios</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</body></html>
"""
