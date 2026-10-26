"""The Black-Box Validation tab, driven end to end against the fake PSS/E, and its summary page and run tabs on a
recorded run."""

import importlib
import time

import pytest
from PySide6.QtWidgets import QApplication

DYR = "4021 'USRLOD' '1' 'FAKETRIP' 12 1 0 14 0 0 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n"


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    app = QApplication.instance() or QApplication([])
    win = importlib.import_module("ui.main_window").MainWindow("screening")
    yield win
    win.close()
    app.processEvents()


def wait_for(thread, timeout=120):
    app = QApplication.instance()
    end = time.time() + timeout
    while thread.isRunning() and time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        app.processEvents()
    assert not thread.isRunning()


def test_the_tab_is_always_there(window):
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert labels == ["Screening", "Post-Commissioning", "Black-Box Validation", "Documentation"]





def test_version_choice_fills_the_default_folder(window):
    tab = window.blackbox_tab
    tab.version_combo.setCurrentText("36.7")
    assert tab.folder_edit.text() == r"C:\Program Files\PTI\PSSE36\36.7"
    assert not tab.run_button.isEnabled()


def test_a_missing_install_folder_blocks_the_run_with_the_reason(window, tmp_path):
    tab = window.blackbox_tab
    tab.folder_edit.setText(str(tmp_path / "no-such-psse"))
    tab._folder_changed()
    assert tab.folder_error.text() == "This folder does not exist. Choose the folder that holds PSSBIN."
    assert tab.folder_edit.property("error") is True
    assert tab.readiness()["psse"] == ("failing", "Folder not found")
    assert tab.psse_mark.text() == "!"
    assert tab.run_hint.text() == "Fix the PSS/E install, then choose a .dyr file."
    assert tab.check_rows["model"][1].text() == "No .dyr file chosen"
    assert tab.check_rows["tests"][1].text().startswith("Standard level · ")


def test_the_coverage_list_follows_the_test_level(window):
    tab = window.blackbox_tab
    assert tab.level_combo.currentText() == "Standard · about 400 runs"
    assert "<b>Undervoltage</b>: sags to 0–0.9 pu, up to 20 s" in tab.coverage.text()
    tab.level_combo.setCurrentIndex(0)
    assert "up to 10 s" in tab.coverage.text() and "Reconnection" not in tab.coverage.text()


def test_the_run_folder_is_a_remembered_setting(window, tmp_path):
    from app import settings
    from ui.blackbox import tab as ui_blackbox

    tab = window.blackbox_tab
    assert ui_blackbox.work_root() == settings.default_run_root()
    tab.set_run_root(tmp_path / "runs")
    assert ui_blackbox.work_root() == tmp_path / "runs"
    assert tab.run_folder_edit.text() == str(tmp_path / "runs")


def test_check_load_and_run(window, fake_psse_install, tmp_path):
    tab = window.blackbox_tab
    tab.set_run_root(tmp_path / "runs")
    tab.folder_edit.setText(fake_psse_install.install_dir)
    tab._folder_changed()
    tab.python_edit.setText(fake_psse_install.python_exe)
    tab._start_check()
    wait_for(tab._check_thread)
    assert "ready" in tab.check_status.text(), tab.check_status.text()
    assert tab.psse_mark.text() == "✓"

    path = tmp_path / "model.dyr"
    path.write_text(DYR)
    tab.load_dyr(str(path))
    assert tab.target_combo.currentText() == "FAKETRIP - bus 4021, load '1'"  # picked automatically
    assert "{BUS} 'USRLOD'" in tab.placement_text.toPlainText()
    assert tab.run_button.isEnabled() and tab.run_hint.text() == ""

    tab.level_combo.setCurrentIndex(0)  # quick
    tab.start_run()
    assert tab.results_stack.currentIndex() == 1  # the running page
    wait_for(tab._run_thread)
    assert tab._paths and tab._paths["html"].exists()
    assert tab.stage_label.text() == "Finished."
    run_folder = tab._paths["html"].parent
    assert run_folder.parent == tmp_path / "runs"  # a date-and-time subfolder of the run folder
    # the summary is shown on this tab, with the run's folder and files, and the run is listed
    assert tab.results_stack.currentWidget() is tab.summary_view
    assert tab.summary_view.folder_row.path() == str(run_folder)
    assert "PSS/E channel files, one per case" in tab.summary_view.file_labels[r"work\cache\*\case.outx"].text()
    assert tab.runs_list.count() == 1 and tab.left_stack.currentIndex() == 1
    assert tab.recap_values["Model"].text().startswith("model.dyr")

    run_tab = tab.open_run_tab(str(run_folder))
    assert window.shell.current_key() == f"run:{run_folder.resolve()}"
    assert run_tab.explorer.tree.topLevelItemCount() >= 1 and "cases" in run_tab.explorer.source_label.text()
    assert tab.open_run_tab(str(run_folder)) is run_tab  # opening it again focuses the same tab
    window.shell.close_run_tab(window.shell.run_tab_keys()[0])
    assert window.shell.run_tab_keys() == []


def test_the_check_is_remembered(window, fake_psse_install):
    from blackbox.psse_install import load_saved_selection, save_selection

    save_selection(fake_psse_install)
    assert load_saved_selection().install_dir == fake_psse_install.install_dir


def test_prefill_hands_over_a_model_and_its_dlls(window, tmp_path):
    tab = window.blackbox_tab
    path = tmp_path / "vendor.dyr"
    path.write_text(DYR)
    window.navigate("blackbox", dyr=str(path), dlls=["C:/models/fake.dll"])
    assert window.shell.current_key() == "blackbox"
    assert tab.target_combo.currentIndex() == 0 and tab.dlls() == (r"C:\models\fake.dll",)
    assert tab.dll_stack.currentIndex() == 1


# --- a recorded run ---------------------------------------------------------------------------------------------


@pytest.fixture
def recorded(window, tmp_path):
    import json

    from fixtures.blackbox_doc import documented_doc, write_run
    from test_blackbox_explorer import make_run

    root = tmp_path / "runs"
    cases = make_run(root / "20261012-094100")
    doc = documented_doc()
    doc["points"] = json.loads((cases / "validation.json").read_text())["points"]  # the explorer fixture's cases
    folder = write_run(cases, doc, cases=0)
    window.blackbox_tab.set_run_root(root)
    return folder


def test_a_previous_run_opens_its_summary(window, recorded):
    tab = window.blackbox_tab
    assert tab.empty_runs_list.count() == 1 and not tab.empty_previous.isHidden()
    run = tab.show_run(recorded)
    view = tab.summary_view
    assert view.heading.text() == "PERC1 DLL on PSS/E 35.6 · Standard level"
    assert view.subtitle.text().startswith("12 Oct 2026 · 396 cases, all completed · 32 min on 4 workers")
    assert view.comparison.rowCount() == 1 and view.comparison.item(0, 0).text() == "ERCOT (NOGRR282)"
    assert "Undervoltage misses at 0.5, 0.8, 0.9 pu" in view.comparison_text.text()
    assert view.measured.rowCount() >= 10
    assert tab.recap_values["PSS/E"].text() == "35.6.4 · Python 3.11.9"
    assert tab.recap_values["Compared"].text() == "ERCOT (NOGRR282)"
    assert run.title == "PERC1 DLL · 35.6 · Standard"


def test_the_tolerance_overlay_starts_empty_and_is_never_saved(window, recorded):
    from app import settings

    tab = window.blackbox_tab
    tab.show_run(recorded)
    card = tab.summary_view.tolerance
    assert card.overlay_combo.currentText() == "Choose a standard…" and card.overlay_preset() is None
    assert card.shortfall_list() == []
    assert card.caption.text().startswith("Choose a standard to overlay.")
    card.overlay_combo.setCurrentIndex(card.overlay_combo.findData("ercot_nogrr282"))
    assert [(f.lo, f.hi) for f in card.shortfall_list()] == [(0.5, 0.6), (0.8, 0.9), (0.9, 1.0)]
    assert "Short of ERCOT (NOGRR282) at three undervoltage bands" in card.caption.text()
    assert card.notes["frequency"].text().startswith("ERCOT (NOGRR282) has no frequency table")
    assert not [key for key in settings.load() if "overlay" in key or "tolerance" in key]
    tab.show_run(recorded)  # showing a run again starts without an overlay
    assert card.overlay_preset() is None
    card.overlay_combo.setCurrentIndex(0)
    assert card.shortfall_list() == []


def test_the_run_tab_pages(window, recorded):
    tab = window.blackbox_tab
    run_tab = tab.open_run_tab(str(recorded))
    assert run_tab.current_page() == "Test explorer"
    explorer = run_tab.explorer
    first = explorer.tree.topLevelItem(0)
    assert first.text(0).startswith("Undervoltage ride-through (2)")
    explorer._draw()
    assert explorer.count_label.text() == "3 of 3 cases · 1 ticked"
    assert explorer.files_box.count() == 1  # the ticked case's channel file is listed
    names = [explorer.channels.item(i).data(0x100) for i in range(explorer.channels.count())]
    assert names[:4] == ["V", "F", "P", "Q"] and explorer._checked_channels() == ["V", "P"]
    explorer.filter.setText("tripped")
    assert [first.child(i).isHidden() for i in range(first.childCount())] == [False, True]
    run_tab.set_page(3)
    assert run_tab.current_page() == "PSS/E log" and "psse.log" in run_tab.log_caption.text()
    run_tab.set_page(2)
    assert run_tab.current_page() == "Report"
    run_tab.set_page(0)  # Summary: back to the run's summary on the Black-Box tab
    assert window.shell.current_key() == "blackbox" and tab.results_stack.currentWidget() is tab.summary_view


def test_edit_setup_returns_to_the_setup_with_the_runs_choices(window, recorded):
    tab = window.blackbox_tab
    tab.show_run(recorded)
    tab.edit_setup()
    assert tab.left_stack.currentIndex() == 0 and tab.results_stack.currentIndex() == 0
    assert tab.preset_ids() == ("ercot_nogrr282",)
    assert tab.level_combo.currentData() == "standard"


def test_a_late_check_for_the_old_version_does_not_stand(window):
    """The tab re-checks the saved selection at start-up; if the version changes meanwhile, that answer is for the
    old one and must not mark the new selection ready (B2)."""
    from blackbox.psse_install import CheckResult, PsseSelection

    tab = window.blackbox_tab
    started = []
    tab._start_check = lambda: started.append(tab.selection().version)  # no PSS/E here
    tab.version_combo.setCurrentText("35.6")
    old = PsseSelection("36.7", r"C:\Program Files\PTI\PSSE36.7", "python.exe", "PSSPY314")
    tab._check_done(CheckResult(True, "PSS/E 36.7.1 with Python 3.14.6: ready", old, "36.7.1", "3.14.6"))
    assert tab._check is None and started == ["35.6"]
    new = tab.selection()
    tab._check_done(CheckResult(True, "PSS/E 35.6.4 with Python 3.11.9: ready", new, "35.6.4", "3.11.9"))
    assert tab._check is not None and tab._check.selection.version == "35.6"


def test_the_summary_subtitle_wraps_a_long_stop_message(window):
    assert window.blackbox_tab.summary_view.subtitle.wordWrap()  # B3
