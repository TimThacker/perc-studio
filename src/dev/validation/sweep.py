"""Sweep spec loading, cartesian expansion, and the generate -> export ->
run -> validate -> report orchestration a single `perc-studio sweep` command
drives. `run_sweep` is directly unit-testable without Click at all - the
CLI's `sweep` command is a thin wrapper around it.
"""

from __future__ import annotations

import itertools
import json
import os

from dev.validation.case_model import (
    FacilityInfo,
    LoadComposition,
    block_dyr_record,
    case_from_preset,
    to_json,
)
from dev.validation.checks import validate_case
from dev.validation.reports import (
    build_case_report_html,
    build_sweep_summary_html,
    build_sweep_summary_json,
)
from load_models import DEFAULT_BLOCK_MODELS, get_load_model
from presets.ridethrough import RIDE_THROUGH_PRESETS
from psse.runner import FaultScenario, get_runner

DEFAULT_LOAD_ID = "1"


def load_sweep_spec(path: str) -> dict:
    """JSON by default; .yaml/.yml is supported only if pyyaml is installed
    (an optional dependency - see pyproject.toml/src/dev/cli/README.md)."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "reading a .yaml/.yml sweep spec requires the optional 'pyyaml' dependency"
            ) from exc
        return yaml.safe_load(text)
    return json.loads(text)


def _facility_and_load_from_spec(spec_facility: dict) -> tuple:
    facility = FacilityInfo(
        name=spec_facility.get("name", "Sweep facility"),
        bus_number=int(spec_facility.get("bus_number", 100001)),
        bus_name=spec_facility.get("bus_name", "BUS_1"),
        use_case=spec_facility.get("use_case", "AI Training"),
        use_case_pct=int(spec_facility.get("use_case_pct", 100)),
        total_mw=float(spec_facility.get("total_mw", 300.0)),
        power_factor=float(spec_facility.get("power_factor", 0.99)),
    )
    load_composition = LoadComposition(
        pct_it=float(spec_facility.get("pct_it", 70.0)),
        pct_cooling_vfd=float(spec_facility.get("pct_cooling_vfd", 20.0)),
        pct_cooling_motor=float(spec_facility.get("pct_cooling_motor", 5.0)),
        pct_other=float(spec_facility.get("pct_other", 5.0)),
    )
    return facility, load_composition


def expand_cases(spec: dict) -> list:
    """Cartesian product of spec["presets"] x spec["scenarios"], as
    (preset_id, FaultScenario) pairs."""
    scenarios = [FaultScenario.from_dict(s) for s in spec["scenarios"]]
    return list(itertools.product(spec["presets"], scenarios))


def run_sweep(spec: dict, output_dir: str, *, runner=None) -> dict:
    """Runs the full generate -> export -> run -> validate -> report loop
    for every (preset, scenario) pair in `spec`, writing artifacts under
    `output_dir` (the CLI is responsible for naming that directory, e.g.
    output/<sweep_id>-<timestamp>/):

        output_dir/
          cases/<case_id>.json
          cases/<case_id>__<block>.dyr
          results/<case_id>__<block>__<scenario_id>.json
          reports/<case_id>__<block>__<scenario_id>.html
          reports/summary.html
          reports/summary.json

    Returns the same dict written to reports/summary.json.

    `model` (default "perc1_dll") is the load model under test - any
    registered model with a `cons_for_preset` hook, which encodes each
    preset's envelope into that model's CONs. `block` (default "it") must be
    "it" or "vfd", the blocks ride-through presets apply to."""
    block = spec.get("block", "it")
    if block not in ("it", "vfd"):
        raise ValueError(f"sweep only supports block 'it' or 'vfd' (ride-through presets), got {block!r}")
    model = get_load_model(spec.get("model", DEFAULT_BLOCK_MODELS[block]))
    if not model.supports_presets:
        raise ValueError(f"load model {model.id!r} has no cons_for_preset hook, so it cannot be swept over presets")

    runner = runner or get_runner(spec.get("runner", "mock"))
    if getattr(runner, "runner_id", None) == "mock" and not model.can_run_mock:
        raise ValueError(f"load model {model.id!r} cannot be mock-run: it needs parse_dyr_record and simulate hooks")
    facility, load_composition = _facility_and_load_from_spec(spec.get("base_case", {}).get("facility", {}))

    cases_dir = os.path.join(output_dir, "cases")
    results_dir = os.path.join(output_dir, "results")
    reports_dir = os.path.join(output_dir, "reports")
    for d in (cases_dir, results_dir, reports_dir):
        os.makedirs(d, exist_ok=True)

    case_reports = []
    for preset_id, scenario in expand_cases(spec):
        preset = RIDE_THROUGH_PRESETS[preset_id]
        case = case_from_preset(preset_id, facility=facility, load_composition=load_composition, model_id=model.id)
        to_json(case, os.path.join(cases_dir, f"{case.case_id}.json"))

        dyr_text = block_dyr_record(case, block, DEFAULT_LOAD_ID)
        dyr_path = os.path.join(cases_dir, f"{case.case_id}__{block}.dyr")
        with open(dyr_path, "w", encoding="utf-8") as f:
            f.write(dyr_text)

        result = runner.run(None, dyr_text, scenario, block_name=block, case_id=case.case_id)
        result_path = os.path.join(results_dir, f"{case.case_id}__{block}__{scenario.id}.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

        report = validate_case(case, block, [(scenario, result)], preset=preset)
        case_reports.append(report)

        report_html = build_case_report_html(
            case, block, scenario, result, report.points[0],
            envelope=preset.envelope, overvoltage_envelope=preset.overvoltage_envelope,
        )
        report_path = os.path.join(reports_dir, f"{case.case_id}__{block}__{scenario.id}.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)

    sweep_id = spec.get("sweep_id", "sweep")
    summary_json = build_sweep_summary_json(case_reports)
    summary_html = build_sweep_summary_html(sweep_id, case_reports)
    with open(os.path.join(reports_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2)
    with open(os.path.join(reports_dir, "summary.html"), "w", encoding="utf-8") as f:
        f.write(summary_html)

    return summary_json
