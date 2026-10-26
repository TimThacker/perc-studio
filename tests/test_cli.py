import json
import os

from dev.cli.main import cli


def _envelope(result):
    return json.loads(result.output)


def _generate_preset_case(cli_runner, path, preset_id="ercot_nogrr282"):
    result = cli_runner.invoke(
        cli, ["params", "generate", "--source", "preset", "--preset-id", preset_id, "--out", path]
    )
    assert result.exit_code == 0, result.output
    return result


def test_root_help_smoke(cli_runner):
    result = cli_runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_every_subcommand_group_has_help(cli_runner):
    for args in (
        ["params", "--help"],
        ["export", "--help"],
        ["run", "--help"],
        ["validate", "--help"],
        ["report", "--help"],
        ["sweep", "--help"],
    ):
        result = cli_runner.invoke(cli, args)
        assert result.exit_code == 0, args


def test_params_generate_from_preset(cli_runner, tmp_path):
    out = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, out)

    with open(out, "r", encoding="utf-8") as f:
        case_dict = json.load(f)
    assert case_dict["it_block"]["preset_id"] == "ercot_nogrr282"


def test_params_generate_missing_preset_id_is_usage_error(cli_runner):
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset"])
    assert result.exit_code == 2
    assert _envelope(result)["ok"] is False


def test_params_generate_unknown_preset_id_is_usage_error(cli_runner):
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset", "--preset-id", "not_real"])
    assert result.exit_code == 2
    env = _envelope(result)
    assert env["ok"] is False
    assert "not_real" in env["errors"][0]


def test_params_generate_overrides_source(cli_runner, tmp_path):
    base = str(tmp_path / "base.json")
    out = str(tmp_path / "overridden.json")
    _generate_preset_case(cli_runner, base)

    result = cli_runner.invoke(cli, [
        "params", "generate", "--source", "overrides", "--base-case", base, "--override", "it.VDPA=0.55", "--out", out,
    ])
    assert result.exit_code == 0, result.output
    with open(out, "r", encoding="utf-8") as f:
        case_dict = json.load(f)
    assert case_dict["it_block"]["cons"]["VDPA"] == 0.55


def test_params_generate_overrides_unknown_con_is_usage_error(cli_runner, tmp_path):
    base = str(tmp_path / "base.json")
    _generate_preset_case(cli_runner, base)

    result = cli_runner.invoke(cli, [
        "params", "generate", "--source", "overrides", "--base-case", base, "--override", "it.NOT_A_CON=1.0",
    ])
    assert result.exit_code == 2
    assert _envelope(result)["ok"] is False


def test_params_validate_valid_case(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, ["params", "validate", case_path])
    assert result.exit_code == 0
    assert _envelope(result)["data"]["valid"] is True


def test_params_show_human_flag(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, ["params", "show", case_path, "--human"])
    assert result.exit_code == 0
    assert "case_id:" in result.output


def test_export_dyr(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    dyr_path = str(tmp_path / "it.dyr")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, ["export", "dyr", case_path, "--block", "it", "--out", dyr_path])
    assert result.exit_code == 0
    with open(dyr_path, "r", encoding="utf-8") as f:
        text = f.read()
    assert "PERCBL" in text


def test_run_with_mock_runner_reaching_the_dwell_time_trips(cli_runner, tmp_path):
    """ercot_nogrr282's collapsed Option-1 point is VDPA=0.90pu/DMA=2.00s - a
    fault that reaches that dwell should trip under the mock runner too."""
    case_path = str(tmp_path / "case.json")
    result_path = str(tmp_path / "result.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, [
        "run", case_path, "--fault-duration-s", "2.0", "--fault-voltage-pu", "0.75",
        "--runner", "mock", "--out", result_path,
    ])
    assert result.exit_code == 0, result.output
    env = _envelope(result)
    assert env["data"]["result"]["tripped"] is True
    assert os.path.exists(result_path)


def test_run_with_psse_runner_is_unavailable(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, [
        "run", case_path, "--fault-duration-s", "0.6", "--fault-voltage-pu", "0.75", "--runner", "psse",
    ])
    assert result.exit_code == 4
    assert _envelope(result)["ok"] is False


def test_run_without_scenario_or_fault_flags_is_usage_error(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, ["run", case_path])
    assert result.exit_code == 2


def test_validate_results_pass_when_dwell_time_is_reached(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    result_path = str(tmp_path / "result.json")
    _generate_preset_case(cli_runner, case_path)
    run_result = cli_runner.invoke(cli, [
        "run", case_path, "--fault-duration-s", "2.0", "--fault-voltage-pu", "0.75",
        "--runner", "mock", "--out", result_path,
    ])
    assert run_result.exit_code == 0, run_result.output

    result = cli_runner.invoke(cli, [
        "validate", "results", "--case", case_path, "--result", result_path,
        "--block", "it", "--preset-id", "ercot_nogrr282",
    ])
    assert result.exit_code == 0, result.output
    assert _envelope(result)["data"]["report"]["all_passed"] is True


def test_validate_results_mismatch_exits_5(cli_runner, tmp_path):
    """A deliberately non-compliant override (FCEASE=0, "rides through with no
    trip expected") against a deep, long sag the real ERCOT envelope requires
    tripping for - a genuine mismatch, to exercise `validate results`' exit-5
    path. (A 0.6s/0.75pu sag against an unmodified ercot_nogrr282 preset used
    to be this test's example - PSS/E testing confirmed the
    compiled DLL always evaluates Option 3's full 4-stage table, and
    ridethrough_presets.py now encodes that table from the preset's own real
    envelope, so the mock runner and the validator now correctly agree that
    scenario trips - see docs/developer/PERC1_MODEL.md's "Option 3 is always live".)"""
    case_path = str(tmp_path / "case.json")
    override_path = str(tmp_path / "case_override.json")
    result_path = str(tmp_path / "result.json")
    _generate_preset_case(cli_runner, case_path)
    override_result = cli_runner.invoke(cli, [
        "params", "generate", "--source", "overrides", "--base-case", case_path,
        "--override", "it.FCEASE=0.0", "--out", override_path,
    ])
    assert override_result.exit_code == 0, override_result.output

    run_result = cli_runner.invoke(cli, [
        "run", override_path, "--fault-duration-s", "2.0", "--fault-voltage-pu", "0.75",
        "--runner", "mock", "--out", result_path,
    ])
    assert run_result.exit_code == 0, run_result.output

    result = cli_runner.invoke(cli, [
        "validate", "results", "--case", override_path, "--result", result_path,
        "--block", "it", "--preset-id", "ercot_nogrr282",
    ])
    assert result.exit_code == 5
    env = _envelope(result)
    assert env["ok"] is True  # ran fine - this is a real finding, not a tool error
    assert env["data"]["report"]["all_passed"] is False


def test_report_case_writes_html(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    result_path = str(tmp_path / "result.json")
    report_path = str(tmp_path / "report.html")
    _generate_preset_case(cli_runner, case_path)
    cli_runner.invoke(cli, [
        "run", case_path, "--fault-duration-s", "2.0", "--fault-voltage-pu", "0.75",
        "--runner", "mock", "--out", result_path,
    ])

    result = cli_runner.invoke(cli, [
        "report", "case", "--case", case_path, "--result", result_path, "--block", "it", "--out", report_path,
    ])
    assert result.exit_code == 0, result.output
    assert os.path.exists(report_path)


def test_sweep_end_to_end_produces_summary_and_report_sweep_reads_it(cli_runner, tmp_path):
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sweep_example.json")
    output_dir = str(tmp_path / "sweep_out")

    result = cli_runner.invoke(cli, ["sweep", spec_path, "--output-dir", output_dir])
    assert result.exit_code in (0, 5), result.output
    assert os.path.exists(os.path.join(output_dir, "reports", "summary.json"))

    follow_up = cli_runner.invoke(cli, ["report", "sweep", "--output-dir", output_dir])
    assert follow_up.exit_code == 0, follow_up.output
    assert _envelope(follow_up)["data"]["summary"]["total_cases"] == 4


def test_sweep_with_psse_runner_is_unavailable(cli_runner, tmp_path):
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sweep_example.json")
    output_dir = str(tmp_path / "sweep_out_psse")

    result = cli_runner.invoke(cli, ["sweep", spec_path, "--runner", "psse", "--output-dir", output_dir])
    assert result.exit_code == 4


def test_export_dyr_supports_every_record_scope(cli_runner, tmp_path):
    case_path = str(tmp_path / "case.json")
    _generate_preset_case(cli_runner, case_path)

    result = cli_runner.invoke(cli, ["export", "dyr", case_path, "--block", "all", "--scope", "zone",
                                     "--subsystem-number", "12"])
    assert result.exit_code == 0, result.output
    text = _envelope(result)["data"]["dyr_text"]
    assert text.count("'PERCZN' 12 3") == 2
    assert "'CLODZN'" in text

    missing = cli_runner.invoke(cli, ["export", "dyr", case_path, "--scope", "owner"])
    assert missing.exit_code == 2
