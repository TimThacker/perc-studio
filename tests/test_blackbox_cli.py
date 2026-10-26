"""`perc-studio psse check` and `perc-studio blackbox`, against the fake PSS/E."""

import json

from dev.cli.main import cli

DYR = ("@! two loads\n"
       "4021 'USRLOD' '1' 'FAKETRIP' 12 1 0 14 0 0 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n"
       "4022 'USRLOD' '1' 'FAKETRIP' 12 1 0 14 0 0 0.5 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n")


def _args(sel):
    return ["--psse-version", sel.version, "--psse-dir", sel.install_dir, "--python", sel.python_exe]


def test_psse_check(cli_runner, fake_psse_install):
    out = cli_runner.invoke(cli, ["psse", "check", *_args(fake_psse_install)])
    env = json.loads(out.output)
    assert out.exit_code == 0 and env["ok"] and env["data"]["psse_version"] == "35.6.4"


def test_psse_check_reports_a_wrong_version(cli_runner, fake_psse_install):
    args = _args(fake_psse_install)
    args[1] = "36.7"
    out = cli_runner.invoke(cli, ["psse", "check", *args])
    assert out.exit_code == 4 and "not 36.7" in json.loads(out.output)["errors"][0]


def test_blackbox_lists_loads_and_requires_a_choice(cli_runner, fake_psse_install, tmp_path):
    dyr = tmp_path / "two.dyr"
    dyr.write_text(DYR)
    listed = json.loads(cli_runner.invoke(cli, ["blackbox", *_args(fake_psse_install), "--dyr", str(dyr), "--list"]).output)
    assert [x["label"] for x in listed["data"]["loads"]] == ["FAKETRIP - bus 4021, load '1'", "FAKETRIP - bus 4022, load '1'"]
    out = cli_runner.invoke(cli, ["blackbox", *_args(fake_psse_install), "--dyr", str(dyr), "--out", str(tmp_path / "o")])
    assert out.exit_code == 2 and "--load" in json.loads(out.output)["errors"][0]


def test_blackbox_quick_run_writes_the_report(cli_runner, fake_psse_install, tmp_path):
    dyr = tmp_path / "two.dyr"
    dyr.write_text(DYR)
    out = cli_runner.invoke(cli, ["blackbox", *_args(fake_psse_install), "--dyr", str(dyr), "--load", "2",
                                  "--level", "quick", "--preset", "ercot_nogrr282", "--out", str(tmp_path / "o")])
    env = json.loads(out.output)
    assert out.exit_code == 0, env
    assert env["data"]["overall"]["ercot_nogrr282"]
    assert (tmp_path / "o" / "report.html").exists() and (tmp_path / "o" / "bundle.zip").exists()


def test_psse_check_rejects_an_unsupported_version(cli_runner, fake_psse_install):
    """PSS/E 34 is 32-bit: say so instead of failing on a missing Python (B7)."""
    args = _args(fake_psse_install)
    args[1] = "34.0"
    out = cli_runner.invoke(cli, ["psse", "check", *args])
    assert out.exit_code != 0 and "not supported" in json.loads(out.output)["errors"][0]
