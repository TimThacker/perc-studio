"""The redesigned screens: the app shell, Screening's model bar and edit tracking, Post-Commissioning's stepper,
facility tiles and user-defined block."""

import importlib

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from app import build_info
from presets.ridethrough import RIDE_THROUGH_PRESETS

USER_DYR = "4021 'USRLOD' '7' 'FAKETRIP' 12 1 0 14 0 0 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n"


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    app = QApplication.instance() or QApplication([])
    win = importlib.import_module("ui.main_window").MainWindow("screening")
    yield win
    win.close()
    app.processEvents()


# --- shell ---------------------------------------------------------------------------------------------------


def test_version_pill_text():
    from ui import shell as ui_shell

    assert ui_shell.version_pill_text() == f"App v{build_info.__version__}"


def test_switching_tabs_keeps_each_page(window):
    shell = window.shell
    screening = shell.page("screening")
    window.controller("screening").fields["VDPA"].setValue(0.55)
    shell.set_current("post")
    shell.set_current("screening")
    assert shell.page("screening") is screening
    assert window.controller("screening").fields["VDPA"].value() == pytest.approx(0.55)
    assert shell._nav["screening"].isChecked() and not shell._nav["post"].isChecked()


def test_run_tabs_open_focus_and_close(window):
    shell = window.shell
    closed = []

    class Run(QLabel):
        def shutdown(self):
            closed.append(self.text())

    made = []

    def factory():
        made.append(1)
        return Run("run A")

    page = shell.open_run_tab("runA", "Run · PERC1 DLL · 35.6", factory)
    assert shell.current_key() == "runA" and shell.run_tab_keys() == ["runA"]
    assert shell.run_tab_button("runA").close_button.accessibleName() == "Close run tab"
    shell.set_current("docs")
    assert shell.open_run_tab("runA", "Run · PERC1 DLL · 35.6", factory) is page  # focuses, does not reopen
    assert len(made) == 1 and shell.current_key() == "runA"
    assert window.tabs.count() == len(shell.page_keys())  # run tabs are not workflow tabs
    shell.close_run_tab("runA")
    assert closed == ["run A"] and shell.run_tab_keys() == []
    assert shell.current_key() in shell.page_keys()


def test_preset_docs_opens_the_documentation_tab(window):
    window._apply_preset_to_block("screening", "ercot_nogrr282")
    window.controller("screening").docs_button.click()
    assert window.shell.current_key() == "docs"
    assert window.docs_tab.title_label.text() == RIDE_THROUGH_PRESETS["ercot_nogrr282"].label


# --- Screening -----------------------------------------------------------------------------------------------


def test_the_model_bar_shows_version_record_and_preset(window):
    ctrl = window.controller("screening")
    assert ctrl.model_combo.currentText() == "PERC1 DLL (PSS/E 34/35)"
    assert window.screening_records.scope_combo.currentText() == "Bus (PERCBL, IT = 1)"
    assert ctrl.preset_combo.currentText() == "Standard (ITIC/CBEMA)"
    assert ctrl.status_label.text() == "Internal"
    assert not ctrl.start_from_label.isHidden() and ctrl.import_btn.text() == "Import .dyr…"


def test_edits_are_counted_shaded_and_reset_to_the_preset(window):
    ctrl = window.controller("screening")
    assert not ctrl.reset_button.isEnabled() and ctrl.reset_button.text() == "Reset to preset"
    assert ctrl.edited_pill.isHidden()
    assert ctrl.baseline_note.text() == "Matches Standard (ITIC/CBEMA)"
    preset_value = ctrl.fields["FUFTP1"].value()

    ctrl.fields["FUFTP1"].setValue(57.5)
    ctrl.fields["IPMAXA"].setValue(1.2)
    assert ctrl.edited_pill.text() == "2 edited" and not ctrl.edited_pill.isHidden()
    assert ctrl.reset_button.isEnabled()
    assert ctrl.baseline_note.text() == "Edits are shown against Standard (ITIC/CBEMA)"
    rows = ctrl.row_widgets
    assert rows["frequency_ride_through"].is_edited() and rows["current_limits"].is_edited()
    assert not rows["load_voltage_response"].is_edited()
    assert rows["frequency_ride_through"].header.toolTip() == "57.5–62.0 Hz"
    assert rows["current_limits"].header.toolTip() == "IPMAX 1.2"

    ctrl.reset_button.click()
    assert ctrl.fields["FUFTP1"].value() == pytest.approx(preset_value)
    assert ctrl.tracker.edited_count() == 0 and not ctrl.reset_button.isEnabled()
    assert not rows["frequency_ride_through"].is_edited()


def test_revert_this_row_only_touches_that_row(window):
    ctrl = window.controller("screening")
    ctrl.fields["FUFTP1"].setValue(57.5)
    ctrl.fields["IPMAXA"].setValue(1.2)
    ctrl.row_widgets["frequency_ride_through"].revert_button.click()
    assert ctrl.tracker.edited_cons() == {"IPMAXA"}


def test_choosing_another_preset_with_edits_asks_first(window, monkeypatch):
    ctrl = window.controller("screening")
    answers = []
    monkeypatch.setattr(window, "_confirm", lambda title, text: answers.append(text) or False)
    ctrl.fields["VDPA"].setValue(0.5)
    pjm_index = ctrl.preset_index_to_id.index("pjm_lcl")
    ctrl.preset_combo.setCurrentIndex(pjm_index)
    assert len(answers) == 1
    assert ctrl.active_preset.id == "standard_itic" and ctrl.preset_combo.currentText() == "Standard (ITIC/CBEMA)"
    assert ctrl.fields["VDPA"].value() == pytest.approx(0.5)  # declined: the edit stays

    monkeypatch.setattr(window, "_confirm", lambda title, text: True)
    ctrl.preset_combo.setCurrentIndex(pjm_index)
    assert ctrl.active_preset.id == "pjm_lcl" and ctrl.tracker.edited_count() == 0


def test_no_question_when_nothing_is_edited(window, monkeypatch):
    ctrl = window.controller("screening")
    monkeypatch.setattr(window, "_confirm", lambda *a: pytest.fail("asked without edits"))
    ctrl.preset_combo.setCurrentIndex(ctrl.preset_index_to_id.index("pjm_lcl"))
    assert ctrl.active_preset.id == "pjm_lcl"


def test_the_verdict_strip_and_the_page_follow_the_event(window):
    ctrl = window.controller("screening")
    result = ctrl.refresh_preview()
    assert result.verdict == "TRIPS"
    assert ctrl.verdict.badge.text() == "TRIPS"
    assert ctrl.verdict.title.text() == "5-cycle sag to 0.30 pu"
    assert ctrl.verdict.figure_texts() == {"load_tripped": "50.00 MW", "reconnects": "50.00 MW", "ramp": "30 s"}
    assert 'id="plot-s"' in ctrl.preview.last_html
    ctrl.depth_slider.setValue(5)  # a 5 % sag rides through
    result = ctrl.refresh_preview()
    assert result.verdict == "RIDES THROUGH" and ctrl.verdict.badge.text() == "RIDES THROUGH"
    assert ctrl.fault_value_label.text() == "5 cycles · 0.083 s"
    assert ctrl.depth_value_label.text() == "5 % sag → 0.95 pu"


def test_view_dyr_text_names_the_edits(window):
    ctrl = window.controller("screening")
    ctrl.fields["VDPA"].setValue(0.55)
    window._generate_screening_output()
    assert "Ride-through preset: Standard (ITIC/CBEMA) (1 parameter edited)" in window.screening_output.toPlainText()


def test_record_scope_number_field_appears_for_owner(window):
    combo = window.screening_records.scope_combo
    assert window.screening_number_field.isHidden()
    combo.setCurrentIndex(combo.findData("owner"))
    assert not window.screening_number_field.isHidden()
    assert window.screening_number_field.caption.text() == "Owner number"


# --- Post-Commissioning --------------------------------------------------------------------------------------


def test_the_stepper_shows_each_blocks_mw_and_the_split(window):
    assert window.pc_stepper.buttons[1].text().endswith("IT / UPS   210 MW")
    assert window.pc_split_bar.shares() == [70.0, 20.0, 5.0, 5.0]
    window.pc_total_mw.setValue(100.0)
    assert window.pc_stepper.buttons[1].text().endswith("70 MW")
    assert window.pc_it_line_label.text() == "70.00 MW · 70 % of facility · load ID 1"


def test_the_model_strip_follows_the_step(window):
    window._set_post_step(1)
    assert window.pc_strip_stack.currentWidget() is window.controller("it").model_bar
    window._set_post_step(2)
    assert window.pc_strip_stack.currentWidget() is window.controller("vfd").model_bar
    window._set_post_step(0)
    assert window.pc_strip_stack.isHidden()


def test_blocks_keep_their_own_model(window):
    it, vfd = window.controller("it"), window.controller("vfd")
    it.model_combo.setCurrentIndex(it.model_combo.findData("perc1_standard"))
    assert it.model_id == "perc1_standard" and vfd.model_id == "perc1_dll"


def test_facility_tiles(window):
    window._set_post_step(1)
    window.controller("it").refresh_preview()
    tiles = window.pc_it_tiles
    assert tiles["it"].value.text() == "Trips · back by 91 s"
    assert tiles["it"].caption.text() == "IT / UPS · 210 MW"
    assert tiles["motor"].value.text() == "Not modelled in preview"
    assert tiles["other"].value.text() == "Static load"
    window.pc_vfd_pct.setValue(0.0)
    window.controller("it").refresh_preview()
    assert tiles["vfd"].value.text() == "Not set yet"


def test_a_user_defined_block_is_exported_as_is(window, tmp_path):
    from export.dyr import build_dyr_text

    path = tmp_path / "vendor.dyr"
    path.write_text(USER_DYR)
    it = window.controller("it")
    it.model_combo.setCurrentIndex(it.model_combo.findData("user_defined"))
    assert it.is_user_defined
    assert it.parameters_stack.currentIndex() == 1 and it.preview_stack.currentIndex() == 1
    assert it.load_user_dyr(str(path))
    it.add_user_dlls(["C:/models/fake.dll"])
    assert it.user_dyr_edit.text() == "vendor.dyr" and it.user_dlls_label.text() == "1 DLL"

    state = window._state_from_post_form()
    assert state["it_model_id"] == "user_defined" and "it_adv_VDPA" not in state
    text = build_dyr_text(state)
    assert f"{state['bus_number']} 'USRLOD' '{state['load_id_it']}' 'FAKETRIP'" in text
    window._refresh_facility_tiles("vfd")
    assert window.pc_vfd_tiles["it"].value.text() == "User-defined · not simulated in preview"
