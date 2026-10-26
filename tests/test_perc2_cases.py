"""The PERC2 standard model through the developer loop, the UI/case converters, .dyr import and the desktop editor:
perc-studio (generate, export, run, report), the state <-> case round trip, import of a PERCxx2U record, and the editor
(field set, 0/1 flags, preset values, export, report, screening, preview)."""

import importlib
import json

import pytest
from PySide6.QtWidgets import QApplication, QSpinBox

from dev.cli.main import cli
from dev.validation.case_model import (
    case_to_ui_state,
    from_json,
    schema_problems,
    ui_state_to_case,
)
from editor.dyr_import import import_record, list_records
from export.dyr import build_dyr_text
from export.report import build_html_report
from load_models import get_load_model
from load_models.base import RECORD_SCOPES
from load_models.perc1_dll.dyr import build_perc1_dyr_block
from load_models.perc2_standard.cons import CON_NAMES, ICON_NAMES
from load_models.perc2_standard.dyr import (
    build_perc2_standard_dyr_block,
    parse_perc2_standard_records,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS

PERC2 = ["--model", "perc2_standard"]
MODEL = get_load_model("perc2_standard")
P2_CONS = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")


def _env(result):
    return json.loads(result.output)


def _case(cli_runner, tmp_path, preset="ercot_nogrr282"):
    path = str(tmp_path / "case.json")
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset", "--preset-id", preset, "--out", path,
                                     *PERC2])
    assert result.exit_code == 0, result.output
    return path


# --- the developer loop -------------------------------------------------------------------------------------------


def test_models_list_reports_the_perc2_model(cli_runner):
    models = {m["id"]: m for m in _env(cli_runner.invoke(cli, ["models", "list"]))["data"]["models"]}
    assert models["perc2_standard"]["con_count"] == 63  # 6 flags + 57 CONs
    caps = models["perc2_standard"]["capabilities"]
    assert caps["mock_run"] and caps["frequency_mock_run"] and caps["ride_through_presets"]


def test_generate_export_run_report_for_perc2(cli_runner, tmp_path):
    case_path = _case(cli_runner, tmp_path)
    with open(case_path, encoding="utf-8") as f:
        case = from_json(f.read())
    assert case.it_block.model_id == "perc2_standard" and schema_problems(case) == []
    assert all(isinstance(case.it_block.cons[n], int) for n in ICON_NAMES)

    dyr = _env(cli_runner.invoke(cli, ["export", "dyr", case_path, "--block", "it"]))["data"]["dyr_text"]
    assert "'MAINBL10'" in dyr and "'PERCBL2U' 230 1 6 57 8 44 16" in dyr

    result_path = str(tmp_path / "result.json")
    run = cli_runner.invoke(cli, ["run", case_path, "--fault-duration-s", "3.0", "--fault-voltage-pu", "0.5",
                                  "--runner", "mock", "--out", result_path])
    assert run.exit_code == 0, run.output
    assert _env(run)["data"]["result"]["tripped"] is True
    swell = cli_runner.invoke(cli, ["run", case_path, "--fault-duration-s", "3.0", "--fault-voltage-pu", "1.25",
                                    "--runner", "mock"])
    assert _env(swell)["data"]["result"]["tripped"] is True  # PERC2 has an overvoltage cease

    report = cli_runner.invoke(cli, ["report", "case", "--case", case_path, "--result", result_path, "--block", "it",
                                     "--out", str(tmp_path / "report.html")])
    assert report.exit_code == 0, report.output


def test_ui_state_round_trip_keeps_perc2_and_its_cons(cli_runner, tmp_path):
    with open(_case(cli_runner, tmp_path), encoding="utf-8") as f:
        case = from_json(f.read())
    state = case_to_ui_state(case)
    assert state["it_model_id"] == "perc2_standard" and "it_adv_VLC1" in state and "it_adv_VLMflag" in state
    restored = ui_state_to_case(state)
    assert restored.it_block.model_id == "perc2_standard"
    assert restored.it_block.cons == pytest.approx(case.it_block.cons)


# --- .dyr import ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_perc2_record_round_trips_through_import_for_every_scope(scope):
    number = 0 if scope == "all" else 9
    imported = import_record(build_perc2_standard_dyr_block(number, "P2", P2_CONS, scope=scope))
    assert imported.model_id == "perc2_standard" and imported.ref.scope == scope and imported.ref.load_id == "P2"
    assert list(imported.cons) == list(CON_NAMES)
    for name in CON_NAMES:
        assert imported.cons[name] == pytest.approx(P2_CONS[name], rel=1e-5, abs=1e-9), name
    assert imported.extras["load_fraction"] == 1.0 and "PERC2 standard" in imported.ref.label


def test_a_file_mixing_dll_and_perc2_records_lists_both():
    text = "\n".join([build_perc1_dyr_block(1, "1", get_load_model("perc1_dll").default_cons),
                      build_perc2_standard_dyr_block(2, "2", P2_CONS)])
    refs = list_records(text)
    assert [r.model_id for r in refs] == ["perc1_dll", "perc2_standard"]
    assert import_record(text, refs[1]).model_id == "perc2_standard"


# --- the desktop editor ---------------------------------------------------------------------------------------------


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    yield win
    win.close()
    app.processEvents()


def _choose(window, block, model_id):
    combo = getattr(window, f"pc_{block}_model_combo")
    combo.setCurrentIndex(combo.findData(model_id))


def test_selecting_perc2_gives_its_63_fields_with_integer_flags_and_preset_values(window):
    _choose(window, "it", "perc2_standard")
    fields = window.pc_it_fields
    assert set(fields) == set(CON_NAMES)
    for name in ICON_NAMES:
        assert isinstance(fields[name], QSpinBox) and (fields[name].minimum(), fields[name].maximum()) == (0, 1)
    for preset_id in ("ercot_nogrr282", "pjm_lcl"):
        window._apply_preset_to_block("it", preset_id)
        expected = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS[preset_id], "it")
        params = window._collect_block_params("it")
        for name in CON_NAMES:
            assert params[name] == pytest.approx(expected[name], abs=1e-4), (preset_id, name)
        assert all(isinstance(params[n], int) for n in ICON_NAMES)


def test_perc2_state_exports_its_record_and_report(window):
    _choose(window, "it", "perc2_standard")
    window._apply_preset_to_block("it", "ercot_nogrr282")
    window.pc_it_fields["FHflag"].setValue(0)
    state = window._state_from_post_form()
    assert state["it_model_id"] == "perc2_standard" and state["it_adv_FHflag"] == 0
    text = build_dyr_text(state)
    assert "'PERCBL2U'" in text and "PERC2 standard (PERCxx2U)" in text
    exported = parse_perc2_standard_records(text)[0]["cons"]
    assert exported["FHflag"] == 0 and exported["VLMflag"] == P2_CONS["VLMflag"]
    html = build_html_report(state)
    assert "PERC2 standard (PSS/E 36.7+)" in html and "never reconnects" in html


def test_the_editor_notes_flag_a_long_cease_point_above_the_reconnect_window(window):
    _choose(window, "it", "perc2_standard")
    window._apply_preset_to_block("it", "ercot_nogrr282")
    assert "cycling" not in window.pc_it_notes_label.text()
    window.pc_it_fields["VLrecon"].setValue(0.7)  # below VLC1 0.9: a 0.8 pu sag would cycle
    assert "cycling" in window.pc_it_notes_label.text()


def test_screening_and_preview_with_perc2(window):
    combo = window.pc_screening_model_combo
    combo.setCurrentIndex(combo.findData("perc2_standard"))
    window._generate_screening_output()
    text = window.screening_output.toPlainText()
    assert "'MAINBL10'" in text and "'PERCBL2U'" in text and "PERC2 standard" in text
    _choose(window, "it", "perc2_standard")
    window._refresh_preview("it")
    window.pc_it_kind_group.buttons()[1].click()  # frequency event
    window._refresh_preview("it")
    window.pc_it_kind_group.buttons()[0].click()
    window._refresh_preview("it")
