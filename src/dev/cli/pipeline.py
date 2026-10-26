"""`perc-studio export dyr|run|validate results|report case|report sweep|sweep`
- the rest of the generate -> run -> validate -> report pipeline."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime

import click

from app.config import DEFAULTS
from dev.validation.case_model import block_dyr_record, case_to_ui_state, from_json
from dev.validation.checks import validate_case, validate_result
from dev.validation.reports import build_case_report_html
from dev.validation.sweep import expand_cases, load_sweep_spec, run_sweep
from load_models.base import RECORD_SCOPES
from presets.ridethrough import RIDE_THROUGH_PRESETS
from psse.runner import FaultScenario, SimulationResult, get_runner

from ._output import (
    RunnerUnavailableError,
    UsageError,
    ValidationMismatch,
    cli_result,
    pretty_option,
)

DEFAULT_LOAD_IDS = {"it": DEFAULTS["load_id_it"], "vfd": DEFAULTS["load_id_vfd"], "motor": DEFAULTS["load_id_motor"]}


def _export_block_dyr(case, block_name: str, scope: str = "bus", subsystem_number: int | None = None,
                      load_id: str | None = None) -> str:
    """The block's .dyr record, written by whichever load model the block uses."""
    try:
        return block_dyr_record(case, block_name, load_id or DEFAULT_LOAD_IDS[block_name], scope=scope,
                                subsystem_number=subsystem_number) + "\n"
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def _export_all_dyr(case, scope: str = "bus", subsystem_number: int | None = None, load_id: str | None = None) -> str:
    parts = []
    for block_name in ("it", "vfd", "motor"):
        if case.block(block_name) is not None:
            parts.append(f"/ --- {block_name} block ({case.block(block_name).model_id}) ---")
            parts.append(_export_block_dyr(case, block_name, scope, subsystem_number, load_id))
    return "\n".join(parts)


# --- export dyr --------------------------------------------------------


@click.group("export")
def export_group():
    """Export a case's blocks to PSS/E .dyr text."""


@export_group.command("dyr")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--block", type=click.Choice(["it", "vfd", "motor", "all"]), default="it")
@click.option("--scope", type=click.Choice(list(RECORD_SCOPES)), default="bus",
              help="Record format: bus (PERCBL, IT=1), owner (PERCOW), zone (PERCZN), area (PERCAR), all (PERCAL).")
@click.option("--subsystem-number", type=int, default=None,
              help="Owner/zone/area number - the record's first field for those scopes.")
@click.option("--load-id", default=None,
              help="PSS/E load id (1-2 characters) for every exported record. Default: 1 it, 2 vfd, 3 motor "
              "(app.config DEFAULTS).")
@click.option("--out", type=click.Path(dir_okay=False), default=None)
@pretty_option
def export_dyr(case_json, block, scope, subsystem_number, load_id, out, pretty):
    """The block's bare .dyr record(s), with no header comments."""
    with cli_result("export dyr", pretty) as result:
        case = from_json(case_json)
        text = (_export_all_dyr(case, scope, subsystem_number, load_id) if block == "all"
                else _export_block_dyr(case, block, scope, subsystem_number, load_id))
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
        result["data"] = {"case_id": case.case_id, "block": block, "out": out, "dyr_text": text}


@export_group.command("facility")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", type=click.Path(dir_okay=False), default=None)
@pretty_option
def export_facility(case_json, out, pretty):
    """The whole facility .dyr as the desktop app's Export writes it: header comments, MW per block, notes."""
    from export.dyr import build_dyr_text

    with cli_result("export facility", pretty) as result:
        case = from_json(case_json)
        try:
            text = build_dyr_text(case_to_ui_state(case))
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
        result["data"] = {"case_id": case.case_id, "out": out, "dyr_text": text}


@export_group.command("report")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", type=click.Path(dir_okay=False), required=True, help="Write the HTML report here.")
@pretty_option
def export_report(case_json, out, pretty):
    """The desktop app's HTML report for a case: parameters, expected-response plots, the standards each block meets."""
    from export.report import build_html_report

    with cli_result("export report", pretty) as result:
        case = from_json(case_json)
        try:
            html = build_html_report(case_to_ui_state(case))
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        result["data"] = {"case_id": case.case_id, "out": out}


# --- run -----------------------------------------------------------------


@click.command("run")
@click.argument("case_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--scenario", "scenario_json", type=click.Path(exists=True, dir_okay=False), default=None,
              help="FaultScenario JSON file. Alternative to --fault-duration-s/--fault-voltage-pu.")
@click.option("--scenario-id", default=None, help="Scenario id when built from --fault-* flags.")
@click.option("--fault-start-s", type=float, default=0.5)
@click.option("--fault-duration-s", type=float, default=None)
@click.option("--fault-voltage-pu", type=float, default=None)
@click.option("--fault-frequency-hz", type=float, default=None,
              help="Frequency event instead of a voltage event (with --fault-duration-s).")
@click.option("--block", type=click.Choice(["it", "vfd", "motor"]), default="it")
@click.option("--runner", "runner_name", type=click.Choice(["mock", "psse"]), default="mock")
@click.option("--raw-case", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Path to a .raw power-flow case (recorded for provenance; the mock runner never reads it).")
@click.option("--out", type=click.Path(dir_okay=False), default=None)
@pretty_option
def run(case_json, scenario_json, scenario_id, fault_start_s, fault_duration_s, fault_voltage_pu,
        fault_frequency_hz, block, runner_name, raw_case, out, pretty):
    with cli_result("run", pretty) as result:
        case = from_json(case_json)

        if scenario_json:
            with open(scenario_json, "r", encoding="utf-8") as f:
                scenario = FaultScenario.from_dict(json.load(f))
        elif fault_duration_s is not None and fault_frequency_hz is not None:
            scenario = FaultScenario(
                id=scenario_id or f"adhoc_{fault_frequency_hz}hz_{fault_duration_s}s",
                fault_start_s=fault_start_s, fault_duration_s=fault_duration_s,
                fault_frequency_hz=fault_frequency_hz,
            )
        elif fault_duration_s is not None and fault_voltage_pu is not None:
            scenario = FaultScenario(
                id=scenario_id or f"adhoc_{fault_voltage_pu}pu_{fault_duration_s}s",
                fault_start_s=fault_start_s, fault_duration_s=fault_duration_s, fault_voltage_pu=fault_voltage_pu,
            )
        else:
            raise UsageError(
                "pass --scenario, or --fault-duration-s with either --fault-voltage-pu or --fault-frequency-hz"
            )

        try:
            runner = get_runner(runner_name)
        except NotImplementedError as exc:
            raise RunnerUnavailableError(str(exc)) from exc

        dyr_text = _export_block_dyr(case, block)
        try:
            sim_result = runner.run(raw_case, dyr_text, scenario, block_name=block, case_id=case.case_id)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
        # Carry the scenario alongside the result so `validate results`/`report case`
        # can reconstruct it later from the result JSON alone.
        sim_result = dataclasses.replace(
            sim_result, metadata={**sim_result.metadata, "scenario": scenario.to_dict()}
        )

        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(sim_result.to_dict(), f, indent=2)
        result["data"] = {"result": sim_result.to_dict()}


# --- validate results ------------------------------------------------------


@click.group("validate")
def validate_group():
    """Behavioral validation: compare actual SimulationResults against what
    a preset's envelope says should happen. See `perc-studio params validate`
    for schema-only (no-run) validation."""


def _load_scenario_result_pair(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        sim_result = SimulationResult.from_dict(json.load(f))
    scenario_data = sim_result.metadata.get("scenario")
    if not scenario_data:
        raise UsageError(
            f"{path} has no metadata.scenario - results produced by `perc-studio run` carry this "
            "automatically; a hand-built result JSON must include metadata.scenario"
        )
    return FaultScenario.from_dict(scenario_data), sim_result


@validate_group.command("results")
@click.option("--case", "case_json", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--result", "result_jsons", type=click.Path(exists=True, dir_okay=False), multiple=True, required=True)
@click.option("--block", type=click.Choice(["it", "vfd"]), default="it")
@click.option("--preset-id", default=None, help="Defaults to the block's own preset_id if it has one.")
@pretty_option
def validate_results(case_json, result_jsons, block, preset_id, pretty):
    with cli_result("validate results", pretty) as result:
        case = from_json(case_json)
        preset = RIDE_THROUGH_PRESETS[preset_id] if preset_id else None
        pairs = [_load_scenario_result_pair(path) for path in result_jsons]

        try:
            report = validate_case(case, block, pairs, preset=preset)
        except (ValueError, KeyError) as exc:
            raise UsageError(str(exc)) from exc

        if report.all_passed:
            result["data"] = {"report": report.to_dict()}
        else:
            failed = sum(1 for p in report.points if not p.passed)
            raise ValidationMismatch(f"{failed} of {len(report.points)} scenario(s) failed", {"report": report.to_dict()})


# --- report ----------------------------------------------------------------


@click.group("report")
def report_group():
    """Render HTML reports from case/result artifacts."""


@report_group.command("case")
@click.option("--case", "case_json", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--result", "result_json", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--block", type=click.Choice(["it", "vfd"]), default="it")
@click.option("--preset-id", default=None, help="Defaults to the block's own preset_id if it has one.")
@click.option("--out", type=click.Path(dir_okay=False), required=True)
@pretty_option
def report_case(case_json, result_json, block, preset_id, out, pretty):
    with cli_result("report case", pretty) as result:
        case = from_json(case_json)
        scenario, sim_result = _load_scenario_result_pair(result_json)

        block_obj = case.block(block)
        if block_obj is None:
            raise UsageError(f"case {case.case_id!r} has no {block} block")
        effective_preset_id = preset_id or block_obj.preset_id
        if not effective_preset_id:
            raise UsageError("no preset available - pass --preset-id or use a preset-sourced case")
        try:
            preset = RIDE_THROUGH_PRESETS[effective_preset_id]
        except KeyError as exc:
            raise UsageError(str(exc)) from exc

        point = validate_result(preset, scenario, sim_result)
        html = build_case_report_html(
            case, block, scenario, sim_result, point,
            envelope=preset.envelope, overvoltage_envelope=preset.overvoltage_envelope,
        )
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        result["data"] = {"out": out, "passed": point.passed}


@report_group.command("sweep")
@click.option("--output-dir", type=click.Path(exists=True, file_okay=False), required=True)
@pretty_option
def report_sweep(output_dir, pretty):
    """Re-print a completed `perc-studio sweep` run's reports/summary.json -
    for re-inspecting an existing run, not regenerating it (the sweep
    command already writes both summary.json and summary.html itself)."""
    with cli_result("report sweep", pretty) as result:
        summary_path = os.path.join(output_dir, "reports", "summary.json")
        if not os.path.exists(summary_path):
            raise UsageError(f"{summary_path} not found - run `perc-studio sweep` first")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        result["data"] = {"summary": summary, "summary_path": summary_path}


# --- sweep -------------------------------------------------------------


@click.command("sweep")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--runner", "runner_name", type=click.Choice(["mock", "psse"]), default=None,
              help="Overrides the spec file's own \"runner\" field if given.")
@click.option("--output-dir", type=click.Path(file_okay=False), default=None,
              help="Defaults to output/<sweep_id>-<UTC timestamp>/.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Check the spec and list the (preset, scenario) cases it would run; run nothing, write nothing.")
@pretty_option
def sweep_command(spec_file, runner_name, output_dir, dry_run, pretty):
    with cli_result("sweep", pretty) as result:
        try:
            spec = load_sweep_spec(spec_file)
        except ImportError as exc:
            raise UsageError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise UsageError(f"could not read the sweep spec: {exc}") from exc
        if runner_name:
            spec["runner"] = runner_name

        if dry_run:
            unknown = [p for p in spec.get("presets", []) if p not in RIDE_THROUGH_PRESETS]
            if unknown:
                raise UsageError(f"unknown preset id(s) {unknown}; valid ids: {sorted(RIDE_THROUGH_PRESETS)}")
            try:
                pairs = expand_cases(spec)
            except (KeyError, ValueError) as exc:
                raise UsageError(f"invalid sweep spec: {exc}") from exc
            result["data"] = {
                "sweep_id": spec.get("sweep_id", "sweep"), "runner": spec.get("runner", "mock"),
                "block": spec.get("block", "it"), "model": spec.get("model"), "total_cases": len(pairs),
                "cases": [{"preset_id": p, "scenario": s.to_dict()} for p, s in pairs],
            }
            return

        run_dir = output_dir or os.path.join(
            "output",
            f"{spec.get('sweep_id', 'sweep')}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        )
        os.makedirs(run_dir, exist_ok=True)

        try:
            runner = get_runner(spec.get("runner", "mock"))
        except NotImplementedError as exc:
            raise RunnerUnavailableError(str(exc)) from exc

        try:
            summary = run_sweep(spec, run_dir, runner=runner)
        except (KeyError, ValueError) as exc:
            raise UsageError(str(exc)) from exc

        if summary["all_passed"]:
            result["data"] = {"output_dir": run_dir, "summary": summary}
        else:
            raise ValidationMismatch(
                f"{summary['failed_cases']} of {summary['total_cases']} case(s) failed",
                {"output_dir": run_dir, "summary": summary},
            )
