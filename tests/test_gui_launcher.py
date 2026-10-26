import pytest

from app.launcher import build_parser, main


def test_launcher_default_mode_is_screening():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.mode == "screening"


def test_launcher_parser_supports_all_modes():
    parser = build_parser()

    screening = parser.parse_args(["--mode", "screening"])
    post_commissioning = parser.parse_args(["--mode", "post-commissioning"])

    assert screening.mode == "screening"
    assert post_commissioning.mode == "post-commissioning"


def test_launcher_rejects_multiple_mode_selection():
    with pytest.raises(SystemExit):
        main(["--screening", "--post-commissioning"])


def test_a_command_runs_the_automation_cli(capsys):
    import json

    with pytest.raises(SystemExit) as exit_info:
        main(["info"])
    assert exit_info.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["command"] == "info"


def test_help_lists_the_cli_commands(capsys):
    with pytest.raises(SystemExit):
        main(["help"])
    out = capsys.readouterr().out
    assert "Usage: perc-studio" in out and "params" in out and "blackbox" in out


def test_without_the_cli_a_command_explains_the_source_install(monkeypatch, capsys):
    import sys

    monkeypatch.setitem(sys.modules, "dev.cli.main", None)  # what the installer's bundle looks like
    assert main(["params", "show", "case.json"]) == 2
    assert "source install" in capsys.readouterr().err
