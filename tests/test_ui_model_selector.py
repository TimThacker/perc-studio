"""The PERC1 model-version selector: choosing the standard model swaps the whole editor,
the record written and the response page; choosing the DLL model restores them."""

import importlib

import pytest
from PySide6.QtWidgets import QApplication

from export.dyr import build_dyr_text
from export.report import build_html_report
from load_models import get_load_model
from load_models.perc1_dll.cons import PERC1_DISPLAY_FIELDS
from load_models.perc1_standard.cons import CON_NAMES
from presets.ridethrough import RIDE_THROUGH_PRESETS


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


def test_dll_is_the_default_and_offers_both_models(window):
    combo = window.pc_it_model_combo
    assert combo.currentData() == "perc1_dll"
    models = [combo.itemData(i) for i in range(combo.count())]
    # One selector per block; Post-Commissioning blocks also offer a user-defined (black-box) model.
    assert models == ["perc1_dll", "perc1_standard", "perc2_standard", "perc2_dll", "user_defined"]
    screening = window.pc_screening_model_combo
    assert [screening.itemData(i) for i in range(screening.count())] == ["perc1_dll", "perc1_standard", "perc2_standard",
                                                                         "perc2_dll"]
    assert window._state_from_post_form()["it_model_id"] == "perc1_dll"


def test_selecting_standard_replaces_the_field_set(window):
    dll_fields = set(window.pc_it_fields)
    assert {"VDPA", "FUFTP1", "NPA"} <= dll_fields and len(dll_fields) == len(PERC1_DISPLAY_FIELDS)

    _choose(window, "it", "perc1_standard")
    fields = window.pc_it_fields
    assert set(fields) == set(CON_NAMES)
    assert not dll_fields & set(fields) - {"nP"}  # no DLL-only CON survives
    # Bounds are the measured PSS/E limits: the deadband edges have fixed signs.
    assert fields["dbfl"].maximum() == 0.0 and fields["dbfh"].minimum() == 0.0
    assert fields["fcease"].maximum() == 1.0
    # The other block keeps its own model and fields.
    assert "VDPA" in window.pc_vfd_fields


def test_standard_fields_take_the_presets_values_and_follow_preset_changes(window):
    _choose(window, "it", "perc1_standard")
    for preset_id in ("ercot_nogrr282", "pjm_lcl", "standard_itic"):
        window._apply_preset_to_block("it", preset_id)
        expected = get_load_model("perc1_standard").cons_for_preset(RIDE_THROUGH_PRESETS[preset_id], "it")
        for name in CON_NAMES:
            assert window.pc_it_fields[name].value() == pytest.approx(expected[name], abs=1e-4), (preset_id, name)


def test_switching_back_restores_the_dll_fields_and_values(window):
    window._apply_preset_to_block("it", "ercot_nogrr282")
    _choose(window, "it", "perc1_standard")
    _choose(window, "it", "perc1_dll")
    assert "VDPA" in window.pc_it_fields and "Vcease" not in window.pc_it_fields
    assert window.pc_it_fields["VDPA"].value() == pytest.approx(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle["VDPA"])


def test_state_and_dyr_use_each_blocks_own_model(window):
    _choose(window, "it", "perc1_standard")
    state = window._state_from_post_form()
    assert state["it_model_id"] == "perc1_standard" and state["vfd_model_id"] == "perc1_dll"
    assert "it_adv_Vcease" in state and "it_adv_VDPA" not in state and "vfd_adv_VDPA" in state
    text = build_dyr_text(state)
    assert "'MAINBL10'" in text and "'PERCBL1U'" in text  # IT: standard
    assert text.count("'PERCBL'") == 1  # VFD: DLL
    assert "PERC1 standard" in text


def test_editing_a_standard_field_is_exported_and_flagged(window):
    _choose(window, "it", "perc1_standard")
    window.pc_it_fields["Tdelay"].setValue(0.05)
    assert "Tdelay" in window.pc_it_notes_label.text()
    assert window.pc_it_notes_label.isHidden() is False
    assert window._state_from_post_form()["it_adv_Tdelay"] == pytest.approx(0.05)
    window.pc_it_fields["Tdelay"].setValue(0.0)
    assert "Tdelay" not in window.pc_it_notes_label.text()


def test_unrepresentable_preset_content_is_shown(window):
    _choose(window, "it", "perc1_standard")
    window._apply_preset_to_block("it", "nerc_prc029")
    text = window.pc_it_notes_label.text()
    assert "overvoltage" in text and "frequency" in text


def test_operating_mode_sets_the_voltage_exponents_of_either_model(window):
    _choose(window, "it", "perc1_standard")
    window.pc_it_mode.setCurrentIndex(window.pc_it_mode.findText("Eco-mode / line-interactive"))
    window._on_mode_changed("it")
    assert window.pc_it_fields["nP"].value() == window.pc_it_fields["nQ"].value()
    _choose(window, "it", "perc1_dll")
    window._on_mode_changed("it")
    assert "NPA" in window.pc_it_fields


def test_html_report_handles_a_standard_block_next_to_a_dll_block(window):
    _choose(window, "it", "perc1_standard")
    window._apply_preset_to_block("it", "ercot_nogrr282")
    html = build_html_report(window._state_from_post_form())
    assert "PERC1 standard (PSS/E 36.7+)" in html
    assert "Cease voltage (filtered)" in html and "PERCBL1U" in html
    assert "plot-it" in html and "plot-vfd" in html


def test_review_table_lists_the_selected_models_cons(window):
    _choose(window, "it", "perc1_standard")
    state = window._state_from_post_form()
    window._populate_post_review_table(window.pc_review, state)
    labels = [window.pc_review.item(r, 0).text() for r in range(window.pc_review.rowCount())]
    assert "IT model" in labels and any("Cease voltage" in label for label in labels)
    assert any(label.startswith("VFD Undervoltage stage 1 trip") for label in labels)


def test_screening_tab_writes_the_selected_models_record(window):
    combo = window.pc_screening_model_combo
    combo.setCurrentIndex(combo.findData("perc1_standard"))
    window._generate_screening_output()
    text = window.screening_output.toPlainText()
    assert "'MAINBL10'" in text and "'PERCBL1U'" in text
    assert "PSS/E ignores the model below 5 MW" in text
    state = window._state_from_screening_report_form()
    assert state["it_model_id"] == "perc1_standard"
    assert "PERC1 standard" in build_html_report(state)


def test_preview_panel_renders_the_standard_page_for_each_event_kind(window):
    _choose(window, "it", "perc1_standard")
    window._refresh_preview("it")
    window.pc_it_kind_group.buttons()[1].click()  # frequency event
    window._refresh_preview("it")
    window.pc_it_kind_group.buttons()[0].click()
    window._refresh_preview("it")


def test_the_editor_warns_about_a_large_post_fault_power_peak(window):
    _choose(window, "it", "perc1_standard")
    window._apply_preset_to_block("it", "ercot_nogrr282")  # nP 0, Ipmax 1.25, Ldfact 0.8: 156%
    assert "Post-fault power peak" in window.pc_it_notes_label.text() and "156%" in window.pc_it_notes_label.text()
    window.pc_it_fields["Ipmax"].setValue(0.8)
    assert "Post-fault power peak" not in window.pc_it_notes_label.text()
    window.pc_it_fields["Ipmax"].setValue(1.25)
    window.pc_it_fields["nP"].setValue(1.0)
    assert "Post-fault power peak" not in window.pc_it_notes_label.text()


def test_the_report_page_carries_the_post_fault_peak_warning(window):
    _choose(window, "it", "perc1_standard")
    window._apply_preset_to_block("it", "ercot_nogrr282")
    assert "Post-fault power peak" in build_html_report(window._state_from_post_form())
