"""Importing a .dyr into an editor block: the model switches to the file's, every CON lands in the editor and the
preview, edits are tracked against the file's values, Reset returns to the file, and choosing a preset leaves the
import."""

import importlib

import pytest
from PySide6.QtWidgets import QApplication

from editor.dyr_import import list_records
from export.dyr import build_dyr_text
from load_models import get_load_model
from load_models.perc1_dll.dyr import build_perc1_dyr_block, parse_perc1_records
from load_models.perc1_standard.cons import CON_NAMES
from load_models.perc1_standard.dyr import (
    build_perc1_standard_dyr_block,
    parse_perc1_standard_records,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS

DLL_CONS = get_load_model("perc1_dll").cons_for_preset(RIDE_THROUGH_PRESETS["pjm_lcl"], "it")
STD_CONS = get_load_model("perc1_standard").cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    yield win
    win.close()
    app.processEvents()


@pytest.fixture
def import_file(window, tmp_path, monkeypatch):
    """Import `text` into `block`, answering the file and record dialogs; `pick` is the record index to choose."""
    def run(block, text, pick=0):
        path = tmp_path / "model.dyr"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(window, "_choose_dyr_file", lambda: str(path))
        monkeypatch.setattr(window, "_choose_dyr_record", lambda refs: pick if len(refs) > 1 else refs[0].index)
        window._import_dyr(block)
    return run


def _std_text(**overrides):
    return build_perc1_standard_dyr_block(100, "1", {**STD_CONS, **overrides})


def test_importing_a_standard_record_switches_the_model_and_fills_the_editor(window, import_file):
    assert window.pc_it_model_combo.currentData() == "perc1_dll"
    import_file("it", _std_text(Vcease=0.62))
    assert window.pc_it_model_combo.currentData() == "perc1_standard"
    assert set(window.pc_it_fields) == set(CON_NAMES)
    assert window.pc_it_fields["Vcease"].value() == pytest.approx(0.62)
    assert window.pc_it_active_preset is None
    assert "Imported" in window.pc_it_status_label.text()
    # the preset field gives way to the imported file's name
    assert window.pc_it_imported_field.text() == "model.dyr"
    assert window.pc_it_preset_field.isHidden() and not window.pc_it_imported_box.isHidden()
    assert window.pc_it_import_btn.text() == "Import another .dyr…"
    assert "VDPA" in window.pc_vfd_fields  # the other block is untouched
    assert window._state_from_post_form()["vfd_model_id"] == "perc1_dll"


def test_importing_a_dll_record_keeps_cons_that_have_no_editor_field(window, import_file):
    window.pc_it_model_combo.setCurrentIndex(window.pc_it_model_combo.findData("perc1_standard"))
    cons = {**DLL_CONS, "ZETAA": 0.77}  # not shown in the editor
    import_file("it", build_perc1_dyr_block(100, "1", cons))
    assert window.pc_it_model_combo.currentData() == "perc1_dll"
    params = window._collect_block_params("it")
    assert params["ZETAA"] == 0.77
    assert params == pytest.approx(cons)


def test_preview_and_export_carry_the_imported_cons_exactly(window, import_file):
    import_file("it", _std_text(Tdelay=0.0, Tt=0.0123456))
    params = window._collect_block_params("it")
    assert params["Tt"] == pytest.approx(0.0123456, abs=1e-12)  # more digits than the spin box shows
    text = build_dyr_text(window._state_from_post_form())
    exported = parse_perc1_standard_records(text)[0]["cons"]
    assert exported["Tt"] == pytest.approx(0.0123456, rel=1e-5)
    for name in CON_NAMES:
        assert exported[name] == pytest.approx(window._collect_block_params("it")[name], rel=1e-5, abs=1e-9)


def test_dll_export_after_import_reproduces_the_file(window, import_file):
    import_file("vfd", build_perc1_dyr_block(100, "2", DLL_CONS))
    records = parse_perc1_records(build_dyr_text(window._state_from_post_form()))
    vfd = next(r for r in records if r["load_id"] == "2")
    assert vfd["cons"] == pytest.approx(DLL_CONS)


def test_out_of_range_values_widen_the_field_and_warn(window, import_file):
    import_file("it", build_perc1_dyr_block(100, "1", {**DLL_CONS, "VDPA": 1.5}))
    widget = window.pc_it_fields["VDPA"]
    assert widget.value() == pytest.approx(1.5) and widget.maximum() >= 1.5
    assert window._collect_block_params("it")["VDPA"] == 1.5
    assert "VDPA = 1.5" in window.pc_it_notes_label.text()


def test_editing_after_import_marks_the_field_and_keeps_the_rest(window, import_file):
    import_file("it", _std_text())
    assert window.pc_it_reset_button.text() == "Reset to file"
    assert not window.pc_it_reset_button.isEnabled()
    window.pc_it_fields["Tcease"].setValue(1.0)
    assert window.pc_it_field_labels["Tcease"].property("edited") is True
    assert not window.pc_it_field_labels["Vcease"].property("edited")
    assert window.pc_it_tracker.edited_cons() == {"Tcease"}
    assert window.pc_it_edited_pill.text() == "1 edited"
    assert window.pc_it_reset_button.isEnabled()
    assert window.pc_it_baseline_note.text() == "Edits are shown against model.dyr"
    params = window._collect_block_params("it")
    assert params["Tcease"] == 1.0 and params["Vcease"] == pytest.approx(STD_CONS["Vcease"])
    assert window.pc_it_imported is not None


def test_choosing_a_preset_leaves_the_import(window, import_file):
    import_file("it", _std_text(Vcease=0.62))
    window._apply_preset_to_block("it", "pjm_lcl")
    assert window.pc_it_imported is None
    assert not window.pc_it_preset_field.isHidden()
    assert window.pc_it_active_preset is RIDE_THROUGH_PRESETS["pjm_lcl"]
    expected = get_load_model("perc1_standard").cons_for_preset(RIDE_THROUGH_PRESETS["pjm_lcl"], "it")
    assert window.pc_it_fields["Vcease"].value() == pytest.approx(expected["Vcease"], abs=1e-4)


def test_reset_returns_to_the_files_values_and_stays_imported(window, import_file):
    """Reset restores the baseline: for an imported record that is the file's values, and the block stays on the
    file (it no longer drops the import)."""
    import_file("it", _std_text(Vcease=0.62, Tt=0.0123456))
    window.pc_it_fields["Vcease"].setValue(0.5)
    window.pc_it_fields["Tcease"].setValue(1.5)
    assert window.pc_it_tracker.edited_count() == 2
    window._reset_block_to_preset("it")
    assert window.pc_it_imported is not None
    assert window.pc_it_fields["Vcease"].value() == pytest.approx(0.62)
    assert window._collect_block_params("it")["Tt"] == pytest.approx(0.0123456, abs=1e-12)  # file digits kept
    assert window.pc_it_tracker.edited_count() == 0 and not window.pc_it_reset_button.isEnabled()
    assert window.pc_it_imported_field.text() == "model.dyr"


def test_use_a_preset_instead_returns_to_the_last_preset(window, import_file):
    window._apply_preset_to_block("it", "pjm_lcl")
    import_file("it", _std_text(Vcease=0.62))
    window.pc_it_use_preset_link.click()
    assert window.pc_it_imported is None
    assert window.pc_it_active_preset is RIDE_THROUGH_PRESETS["pjm_lcl"]
    assert window.pc_it_preset_combo.currentText() == RIDE_THROUGH_PRESETS["pjm_lcl"].label


def test_leaving_an_edited_import_asks_first(window, import_file, monkeypatch):
    asked = []
    monkeypatch.setattr(window, "_confirm", lambda title, text: asked.append(text) or False)
    import_file("it", _std_text(Vcease=0.62))
    window.pc_it_use_preset_link.click()  # nothing edited: no question
    assert asked == [] and window.pc_it_imported is None
    import_file("it", _std_text(Vcease=0.62))
    window.pc_it_fields["Tcease"].setValue(1.5)
    window.pc_it_use_preset_link.click()
    assert len(asked) == 1 and "1 edited parameter" in asked[0]
    assert window.pc_it_imported is not None  # declined: still on the file, edit kept
    assert window.pc_it_fields["Tcease"].value() == pytest.approx(1.5)


def test_reimporting_replaces_the_previous_import(window, import_file):
    import_file("it", _std_text(Vcease=0.5))
    import_file("it", build_perc1_dyr_block(100, "1", DLL_CONS))
    assert window.pc_it_preset_combo.findText("Imported .dyr") < 0  # the file has its own field, not a preset entry
    assert window.pc_it_model_combo.currentData() == "perc1_dll"
    assert window.pc_it_imported.model_id == "perc1_dll"


def test_a_multi_record_file_imports_the_chosen_record(window, import_file):
    text = "\n".join([build_perc1_dyr_block(1, "1", DLL_CONS), _std_text(Vcease=0.55)])
    assert len(list_records(text)) == 2
    import_file("it", text, pick=1)
    assert window.pc_it_model_combo.currentData() == "perc1_standard"
    assert window.pc_it_fields["Vcease"].value() == pytest.approx(0.55)


def test_unreadable_files_show_an_error_and_change_nothing(window, import_file, monkeypatch):
    shown = []
    monkeypatch.setattr(window, "_show_import_error", shown.append)
    before = window._collect_block_params("it")
    import_file("it", "1 'GENROU' 1 /")
    import_file("it", "3 'CLODBL' '3' 1 2 3 4 5 /")
    assert len(shown) == 2 and "CLOD" in shown[1]
    assert window.pc_it_imported is None and window._collect_block_params("it") == before


def test_cancelling_the_file_dialog_does_nothing(window, monkeypatch):
    monkeypatch.setattr(window, "_choose_dyr_file", lambda: "")
    window._import_dyr("it")
    assert window.pc_it_imported is None


def test_screening_block_can_import_too(window, import_file):
    import_file("screening", _std_text(Vcease=0.7))
    assert window.pc_screening_model_combo.currentData() == "perc1_standard"
    assert window._collect_block_params("screening")["Vcease"] == pytest.approx(0.7)
    window._generate_screening_output()
    assert "0.7" in window.screening_output.toPlainText()
