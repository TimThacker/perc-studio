"""The standard PERC1 model through the developer loop and the UI/case converters: perc-studio (generate, export,
run, validate, report, sweep) and the desktop UI's state <-> case round trip."""

import importlib
import json
import os

import pytest
from PySide6.QtWidgets import QApplication

from dev.cli.main import cli
from dev.validation.case_model import (
    case_to_ui_state,
    from_json,
    schema_problems,
    ui_state_to_case,
)

STANDARD = ["--model", "perc1_standard"]


def _env(result):
    return json.loads(result.output)


def _case(cli_runner, tmp_path, preset="ercot_nogrr282"):
    path = str(tmp_path / "case.json")
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset", "--preset-id", preset, "--out", path,
                                     *STANDARD])
    assert result.exit_code == 0, result.output
    return path


def test_models_list_reports_the_standard_model_capabilities(cli_runner):
    models = {m["id"]: m for m in _env(cli_runner.invoke(cli, ["models", "list"]))["data"]["models"]}
    caps = models["perc1_standard"]["capabilities"]
    assert models["perc1_standard"]["con_count"] == 30
    assert caps["mock_run"] and caps["frequency_mock_run"] and caps["ride_through_presets"]


def test_generate_export_run_validate_report_for_the_standard_model(cli_runner, tmp_path):
    case_path = _case(cli_runner, tmp_path)
    with open(case_path, encoding="utf-8") as f:
        case = from_json(f.read())
    assert case.it_block.model_id == "perc1_standard" and schema_problems(case) == []

    dyr = _env(cli_runner.invoke(cli, ["export", "dyr", case_path, "--block", "it"]))["data"]["dyr_text"]
    assert "'MAINBL10'" in dyr and "'PERCBL1U' 230 1 0 30 8 24 2" in dyr

    result_path = str(tmp_path / "result.json")
    run = cli_runner.invoke(cli, ["run", case_path, "--fault-duration-s", "3.0", "--fault-voltage-pu", "0.5",
                                  "--runner", "mock", "--out", result_path])
    assert run.exit_code == 0, run.output
    assert _env(run)["data"]["result"]["tripped"] is True

    shallow = cli_runner.invoke(cli, ["run", case_path, "--fault-duration-s", "1.0", "--fault-voltage-pu", "0.95",
                                      "--runner", "mock"])
    assert _env(shallow)["data"]["result"]["tripped"] is False

    report_path = str(tmp_path / "report.html")
    report = cli_runner.invoke(cli, ["report", "case", "--case", case_path, "--result", result_path, "--block", "it",
                                     "--out", report_path])
    assert report.exit_code == 0, report.output
    assert os.path.exists(report_path)


def test_overvoltage_scenarios_are_reported_as_not_modelled_not_failed(cli_runner, tmp_path):
    case_path = _case(cli_runner, tmp_path, "pjm_lcl")
    result_path = str(tmp_path / "swell.json")
    run = cli_runner.invoke(cli, ["run", case_path, "--fault-duration-s", "20.0", "--fault-voltage-pu", "1.3",
                                  "--runner", "mock", "--out", result_path])
    assert run.exit_code == 0, run.output
    result = cli_runner.invoke(cli, ["validate", "results", "--case", case_path, "--result", result_path, "--block", "it",
                                     "--preset-id", "pjm_lcl"])
    assert result.exit_code == 0, result.output
    report = _env(result)["data"]["report"]
    assert report["all_passed"] is True
    assert "Not modelled" in report["points"][0]["notes"] or report["points"][0]["expected_trip"] is False


def test_overrides_use_the_standard_models_con_names(cli_runner, tmp_path):
    base = _case(cli_runner, tmp_path)
    out = str(tmp_path / "c.json")
    bad = cli_runner.invoke(cli, ["params", "generate", "--source", "overrides", "--base-case", base,
                                  "--override", "it.VDPA=0.5"])
    assert bad.exit_code == 2
    ok = cli_runner.invoke(cli, ["params", "generate", "--source", "overrides", "--base-case", base,
                                 "--override", "it.Vcease=0.6", "--out", out])
    assert ok.exit_code == 0, ok.output
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["it_block"]["cons"]["Vcease"] == 0.6


def test_sweep_over_presets_runs_on_the_standard_model(cli_runner, tmp_path):
    spec = {
        "sweep_id": "standard_sweep", "model": "perc1_standard", "runner": "mock", "block": "it",
        "base_case": {"facility": {"name": "T", "bus_number": 101, "bus_name": "B", "total_mw": 300.0,
                                   "power_factor": 0.99, "pct_it": 70.0, "pct_cooling_vfd": 20.0,
                                   "pct_cooling_motor": 5.0, "pct_other": 5.0}},
        "presets": ["ercot_nogrr282", "spp_hill", "pjm_lcl"],
        "scenarios": [
            {"id": "deep_long", "fault_start_s": 0.5, "fault_duration_s": 3.0, "fault_voltage_pu": 0.2},
            {"id": "ride", "fault_start_s": 0.5, "fault_duration_s": 0.3, "fault_voltage_pu": 0.6},
            {"id": "swell", "fault_start_s": 0.5, "fault_duration_s": 5.0, "fault_voltage_pu": 1.25},
        ],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    out = str(tmp_path / "out")
    result = cli_runner.invoke(cli, ["sweep", str(spec_path), "--output-dir", out])
    assert result.exit_code in (0, 5), result.output
    summary = _env(cli_runner.invoke(cli, ["report", "sweep", "--output-dir", out]))["data"]["summary"]
    assert summary["total_cases"] == 9  # 3 presets x 3 scenarios


def test_ui_state_round_trip_keeps_the_standard_model_and_its_cons(cli_runner, tmp_path):
    with open(_case(cli_runner, tmp_path), encoding="utf-8") as f:
        case = from_json(f.read())
    state = case_to_ui_state(case)
    assert state["it_model_id"] == "perc1_standard" and "it_adv_Vcease" in state
    restored = ui_state_to_case(state)
    assert restored.it_block.model_id == "perc1_standard"
    assert restored.it_block.cons == pytest.approx(case.it_block.cons)


def test_desktop_state_converts_to_a_case_that_writes_the_same_record():
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    combo = window.pc_it_model_combo
    combo.setCurrentIndex(combo.findData("perc1_standard"))
    window._apply_preset_to_block("it", "pjm_lcl")
    state = window._state_from_post_form()
    case = ui_state_to_case(state)
    assert case.it_block.model_id == "perc1_standard" and case.vfd_block.model_id == "perc1_dll"
    from dev.validation.case_model import block_dyr_record
    from export.dyr import build_dyr_text

    record = block_dyr_record(case, "it", state["load_id_it"])
    assert record.split("\n")[-1] in build_dyr_text(state)
    window.close()
    app.processEvents()
