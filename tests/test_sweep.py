import json
import os

from dev.validation.sweep import expand_cases, load_sweep_spec, run_sweep
from psse.runner import MockPsseRunner

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sweep_example.json")


def test_load_sweep_spec_parses_json_fixture():
    spec = load_sweep_spec(FIXTURE_PATH)
    assert spec["sweep_id"] == "example_sweep"
    assert spec["presets"] == ["ercot_nogrr282", "spp_hill"]
    assert len(spec["scenarios"]) == 2


def test_expand_cases_is_the_cartesian_product():
    spec = load_sweep_spec(FIXTURE_PATH)
    pairs = expand_cases(spec)
    assert len(pairs) == len(spec["presets"]) * len(spec["scenarios"])
    preset_ids = {p for p, _ in pairs}
    assert preset_ids == set(spec["presets"])


def test_run_sweep_produces_the_expected_artifact_tree(tmp_output_dir):
    spec = load_sweep_spec(FIXTURE_PATH)
    summary = run_sweep(spec, tmp_output_dir, runner=MockPsseRunner())

    n_cases = len(spec["presets"]) * len(spec["scenarios"])
    assert summary["total_cases"] == n_cases
    assert summary["passed_cases"] + summary["failed_cases"] == n_cases

    cases_dir = os.path.join(tmp_output_dir, "cases")
    results_dir = os.path.join(tmp_output_dir, "results")
    reports_dir = os.path.join(tmp_output_dir, "reports")
    assert len(os.listdir(cases_dir)) == 2 * n_cases  # <case_id>.json + <case_id>__it.dyr per case
    assert len(os.listdir(results_dir)) == n_cases
    # n_cases report HTML files + summary.html + summary.json
    assert len(os.listdir(reports_dir)) == n_cases + 2

    assert os.path.exists(os.path.join(reports_dir, "summary.json"))
    assert os.path.exists(os.path.join(reports_dir, "summary.html"))

    with open(os.path.join(reports_dir, "summary.json"), "r", encoding="utf-8") as f:
        summary_on_disk = json.load(f)
    assert summary_on_disk["total_cases"] == summary["total_cases"]


def test_run_sweep_rejects_motor_block(tmp_output_dir):
    spec = load_sweep_spec(FIXTURE_PATH)
    spec = dict(spec, block="motor")
    try:
        run_sweep(spec, tmp_output_dir, runner=MockPsseRunner())
        assert False, "expected ValueError for block='motor'"
    except ValueError as exc:
        assert "motor" in str(exc)
