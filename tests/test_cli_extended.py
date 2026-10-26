"""The `perc-studio` commands that cover the rest of the app: presets, dyr, scenario, results, dll, info, plus the
additions to params/export/sweep."""
import json
import zipfile

from dev.cli.main import cli


def _ok(result, code=0):
    assert result.exit_code == code, result.output
    return json.loads(result.output)


def _case(cli_runner, path, preset_id="ercot_nogrr282", *extra):
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset", "--preset-id", preset_id,
                                     "--out", str(path), *extra])
    assert result.exit_code == 0, result.output
    return str(path)


def test_every_new_group_has_help(cli_runner):
    for group in ("presets", "dyr", "scenario", "results", "dll", "info"):
        assert cli_runner.invoke(cli, [group, "--help"]).exit_code == 0, group


def test_info_reports_models_and_presets(cli_runner):
    data = _ok(cli_runner.invoke(cli, ["info"]))["data"]
    assert "perc2_dll" in data["models"] and data["presets"] > 0


# --- presets -----------------------------------------------------------------


def test_presets_list_and_filters(cli_runner):
    everything = _ok(cli_runner.invoke(cli, ["presets", "list"]))["data"]["presets"]
    with_frequency = _ok(cli_runner.invoke(cli, ["presets", "list", "--with-frequency"]))["data"]["presets"]
    assert with_frequency and len(with_frequency) < len(everything)
    assert all(p["has_frequency_table"] for p in with_frequency)
    generic = _ok(cli_runner.invoke(cli, ["presets", "list", "--category", "Generic"]))["data"]["presets"]
    assert generic and all(p["category"] == "Generic" for p in generic)


def test_presets_show_with_model_cons(cli_runner):
    data = _ok(cli_runner.invoke(cli, ["presets", "show", "pjm_lcl", "--model", "perc1_dll"]))["data"]
    assert data["undervoltage_envelope"] and data["frequency_ride_through"]["underfrequency"]
    assert "VDPA" in data["cons"]


def test_presets_show_unknown_preset_or_model(cli_runner):
    assert _ok(cli_runner.invoke(cli, ["presets", "show", "nope"]), 2)["ok"] is False
    assert _ok(cli_runner.invoke(cli, ["presets", "show", "pjm_lcl", "--model", "nope"]), 2)["ok"] is False
    assert _ok(cli_runner.invoke(cli, ["presets", "show", "pjm_lcl", "--model", "clod"]), 2)["ok"] is False


# --- params diff / show --block -----------------------------------------------


def test_params_diff_lists_changed_cons(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json", "ercot_nogrr282")
    b = _case(cli_runner, tmp_path / "b.json", "spp_hill")
    data = _ok(cli_runner.invoke(cli, ["params", "diff", a, b]))["data"]
    assert data["identical"] is False and data["changed_cons"] > 0
    assert data["blocks"][0]["block"] == "it"


def test_params_diff_identical_and_block_filter(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    data = _ok(cli_runner.invoke(cli, ["params", "diff", a, a]))["data"]
    assert data["identical"] is True and data["blocks"] == []
    b = _case(cli_runner, tmp_path / "b.json", "spp_hill")
    only_motor = _ok(cli_runner.invoke(cli, ["params", "diff", a, b, "--block", "motor"]))["data"]
    assert only_motor["identical"] is True


def test_params_diff_override_shows_the_one_con(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    b = tmp_path / "b.json"
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "overrides", "--base-case", a,
                                     "--override", "it.VDPA=0.55", "--out", str(b)])
    assert result.exit_code == 0, result.output
    data = _ok(cli_runner.invoke(cli, ["params", "diff", a, str(b)]))["data"]
    assert list(data["blocks"][0]["changed"]) == ["VDPA"]
    assert data["blocks"][0]["changed"]["VDPA"]["b"] == 0.55


def test_params_show_single_block(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    data = _ok(cli_runner.invoke(cli, ["params", "show", a, "--block", "it"]))["data"]
    assert data["block_name"] == "it" and "VDPA" in data["block"]["cons"]


def test_params_show_missing_block_is_usage_error(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json", "ercot_nogrr282", "--no-include-vfd")
    assert _ok(cli_runner.invoke(cli, ["params", "show", a, "--block", "vfd"]), 2)["ok"] is False


# --- export ------------------------------------------------------------------


def test_export_dyr_load_id(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    text = _ok(cli_runner.invoke(cli, ["export", "dyr", a, "--block", "all", "--load-id", "Z9"]))["data"]["dyr_text"]
    assert text.count("'Z9'") == 3


def test_export_dyr_rejects_a_long_load_id(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    assert _ok(cli_runner.invoke(cli, ["export", "dyr", a, "--load-id", "TOOLONG"]), 2)["ok"] is False


def test_export_facility_writes_the_app_header(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    out = tmp_path / "facility.dyr"
    data = _ok(cli_runner.invoke(cli, ["export", "facility", a, "--out", str(out)]))["data"]
    assert out.read_text(encoding="utf-8") == data["dyr_text"]
    assert "generated by PERC Studio" in data["dyr_text"] and "PERCBL" in data["dyr_text"]


def test_export_report_writes_html(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    out = tmp_path / "report.html"
    _ok(cli_runner.invoke(cli, ["export", "report", a, "--out", str(out)]))
    assert out.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")


# --- dyr ---------------------------------------------------------------------


def _dyr_file(cli_runner, tmp_path, block="all"):
    a = _case(cli_runner, tmp_path / "a.json")
    dyr = tmp_path / "a.dyr"
    result = cli_runner.invoke(cli, ["export", "dyr", a, "--block", block, "--out", str(dyr)])
    assert result.exit_code == 0, result.output
    return a, str(dyr)


def test_dyr_list_show_and_to_case_round_trip(cli_runner, tmp_path):
    case_path, dyr = _dyr_file(cli_runner, tmp_path)
    records = _ok(cli_runner.invoke(cli, ["dyr", "list", dyr]))["data"]["records"]
    assert [r["model_id"] for r in records] == ["perc1_dll", "perc1_dll", "clod"]
    assert records[2]["inspectable"] is False

    shown = _ok(cli_runner.invoke(cli, ["dyr", "show", dyr, "--record", "0"]))["data"]
    assert "VDPA" in shown["cons"]

    out = tmp_path / "imported.json"
    _ok(cli_runner.invoke(cli, ["dyr", "to-case", dyr, "--record", "0", "--out", str(out)]))
    assert _ok(cli_runner.invoke(cli, ["params", "validate", str(out)]))["data"]["valid"] is True
    diff = _ok(cli_runner.invoke(cli, ["params", "diff", case_path, str(out), "--block", "it"]))["data"]
    assert diff["identical"] is True


def test_dyr_show_needs_a_record_when_there_are_several(cli_runner, tmp_path):
    _, dyr = _dyr_file(cli_runner, tmp_path)
    assert _ok(cli_runner.invoke(cli, ["dyr", "show", dyr]), 2)["ok"] is False


def test_dyr_show_rejects_clod_record(cli_runner, tmp_path):
    _, dyr = _dyr_file(cli_runner, tmp_path)
    assert _ok(cli_runner.invoke(cli, ["dyr", "show", dyr, "--record", "2"]), 2)["ok"] is False


def test_dyr_list_empty_file(cli_runner, tmp_path):
    empty = tmp_path / "empty.dyr"
    empty.write_text("/ nothing here\n")
    assert _ok(cli_runner.invoke(cli, ["dyr", "list", str(empty)]))["data"]["records"] == []


# --- scenario ----------------------------------------------------------------


def test_scenario_make_voltage_and_frequency(cli_runner, tmp_path):
    out = tmp_path / "s.json"
    data = _ok(cli_runner.invoke(cli, ["scenario", "make", "--voltage-pu", "0.5", "--duration-s", "1",
                                       "--out", str(out)]))["data"]
    assert data["scenario"]["id"] == "sag_0.5pu_1s"
    assert json.loads(out.read_text())["fault_voltage_pu"] == 0.5
    freq = _ok(cli_runner.invoke(cli, ["scenario", "make", "--frequency-hz", "58.5", "--duration-s", "310"]))
    assert freq["data"]["scenario"]["fault_frequency_hz"] == 58.5


def test_scenario_make_needs_exactly_one_event_kind(cli_runner):
    assert _ok(cli_runner.invoke(cli, ["scenario", "make", "--duration-s", "1"]), 2)["ok"] is False
    both = ["scenario", "make", "--duration-s", "1", "--voltage-pu", "0.5", "--frequency-hz", "58"]
    assert _ok(cli_runner.invoke(cli, both), 2)["ok"] is False


def test_scenario_made_file_runs(cli_runner, tmp_path):
    a = _case(cli_runner, tmp_path / "a.json")
    s = tmp_path / "s.json"
    _ok(cli_runner.invoke(cli, ["scenario", "make", "--voltage-pu", "0.5", "--duration-s", "2", "--out", str(s)]))
    result = _ok(cli_runner.invoke(cli, ["run", a, "--scenario", str(s)]))["data"]["result"]
    assert result["scenario_id"] == "sag_0.5pu_2s"


def test_scenario_suite_is_runnable_and_in_a_sweep(cli_runner, tmp_path):
    out = tmp_path / "suite.json"
    data = _ok(cli_runner.invoke(cli, ["scenario", "suite", "--preset-id", "ercot_nogrr282",
                                       "--out", str(out)]))["data"]
    scenarios = json.loads(out.read_text())
    assert scenarios == data["scenarios"] and len(scenarios) >= 2
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"sweep_id": "suite", "presets": ["ercot_nogrr282"], "scenarios": scenarios,
                                "runner": "mock", "block": "it"}))
    dry = _ok(cli_runner.invoke(cli, ["sweep", str(spec), "--dry-run"]))["data"]
    assert dry["total_cases"] == len(scenarios)


def test_scenario_suite_unknown_preset(cli_runner):
    assert _ok(cli_runner.invoke(cli, ["scenario", "suite", "--preset-id", "nope"]), 2)["ok"] is False


# --- sweep --dry-run -----------------------------------------------------------


def test_sweep_dry_run_writes_nothing(cli_runner, tmp_path):
    out = tmp_path / "out"
    data = _ok(cli_runner.invoke(cli, ["sweep", "tests/fixtures/sweep_example.json", "--dry-run",
                                       "--output-dir", str(out)]))["data"]
    assert data["total_cases"] == 4 and not out.exists()


def test_sweep_dry_run_catches_unknown_preset(cli_runner, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"presets": ["nope"], "scenarios": []}))
    assert _ok(cli_runner.invoke(cli, ["sweep", str(spec), "--dry-run"]), 2)["ok"] is False


def test_sweep_unreadable_spec_is_usage_error(cli_runner, tmp_path):
    spec = tmp_path / "bad.json"
    spec.write_text("{not json")
    assert _ok(cli_runner.invoke(cli, ["sweep", str(spec)]), 2)["ok"] is False


# --- results / dll -------------------------------------------------------------


def _minimal_run(tmp_path):
    """A run folder with a validation.json, one case folder and a bundle of it."""
    folder = tmp_path / "20261012-140311"
    case = folder / "work" / "cache" / "k1"
    case.mkdir(parents=True)
    doc = {
        "generated": "2026-10-12 14:03:11",
        "setup": {"level": "quick", "level_title": "Quick", "dyr_name": "m.dyr", "dlls": []},
        "stats": {"cases_run": 1, "wall_seconds": 5.0, "workers": 2},
        "stages": {}, "families": {"undervoltage": {"title": "Undervoltage ride-through"}},
        "points": [{"key": "k1", "family": "undervoltage", "event": "0.5 pu for 1 s",
                    "outcome": {"label": "tripped"}, "event_start": 1.0, "event_end": 2.0}],
        "comparison": {},
    }
    (folder / "validation.json").write_text(json.dumps(doc))
    (case / "meta.json").write_text("{}")
    (case / "result.csv").write_text("time,V,F_HZ,P,Q\n0,1,60,1,0\n1,0.5,60,0.5,0\n2,1,60,1,0\n")
    bundle = folder / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.write(folder / "validation.json", "validation.json")
        z.write(case / "result.csv", "cases/k1/result.csv")
        z.write(case / "meta.json", "cases/k1/meta.json")
    return folder


def test_results_list_show_cases_plot(cli_runner, tmp_path):
    folder = _minimal_run(tmp_path)
    runs = _ok(cli_runner.invoke(cli, ["results", "list", str(tmp_path)]))["data"]["runs"]
    assert [r["level"] for r in runs] == ["quick"]
    shown = _ok(cli_runner.invoke(cli, ["results", "show", str(folder)]))["data"]
    assert shown["cases"] == 1 and shown["measured"] == []

    cases = _ok(cli_runner.invoke(cli, ["results", "cases", str(folder)]))["data"]["cases"]
    assert [(c["key"], c["verdict"]) for c in cases] == [("k1", "tripped")]
    assert _ok(cli_runner.invoke(cli, ["results", "cases", str(folder), "--group", "none"]))["data"]["cases"] == []

    out = tmp_path / "plot.html"
    plot = _ok(cli_runner.invoke(cli, ["results", "plot", str(folder / "bundle.zip"), "--case", "k1",
                                       "--out", str(out)]))["data"]
    assert plot["channels"] == ["V", "P"] and out.exists()


def test_results_plot_rejects_unknown_case_and_channel(cli_runner, tmp_path):
    folder = _minimal_run(tmp_path)
    out = str(tmp_path / "p.html")
    assert _ok(cli_runner.invoke(cli, ["results", "plot", str(folder), "--case", "nope", "--out", out]), 2)
    assert _ok(cli_runner.invoke(cli, ["results", "plot", str(folder), "--case", "k1", "--channel", "Zzz",
                                       "--out", out]), 2)


def test_results_show_on_a_non_run_folder(cli_runner, tmp_path):
    assert _ok(cli_runner.invoke(cli, ["results", "show", str(tmp_path)]), 2)["ok"] is False
    assert _ok(cli_runner.invoke(cli, ["results", "cases", str(tmp_path)]), 2)["ok"] is False


def test_dll_inspect_flags_a_file_that_is_not_a_dll(cli_runner, tmp_path):
    fake = tmp_path / "fake.dll"
    fake.write_bytes(b"not a dll")
    envelope = _ok(cli_runner.invoke(cli, ["dll", "inspect", str(fake)]), 5)
    assert envelope["data"]["all_ok"] is False and envelope["data"]["dlls"][0]["problems"]
