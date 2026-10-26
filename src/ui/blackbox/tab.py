"""The Black-Box Validation tab: pick a PSS/E install, a .dyr and its DLLs and the tests,
run the validation in the background, and read the result.

Left: the run setup (1 PSS/E install, 2 Model, 3 Tests) and Run tests, or, once a run is
shown, a recap of its setup and the previous runs. Right: "No results yet" with a
readiness checklist, the running state, or the run's summary (`ui.blackbox.runs`). Each
run's test explorer, report and PSS/E log open in a tab of their own.

How it works: docs/black_box/BLACK_BOX_VALIDATION.md. All the work happens in `blackbox/`;
this module is widgets and two background threads.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import settings
from app import tokens as t
from blackbox.families import LEVELS, coverage_lines
from blackbox.intake import load_targets, place_on_rig, scan_dyr
from blackbox.protocol import Validation, ValidationSetup
from blackbox.psse_install import (
    SUPPORTED_VERSIONS,
    CheckResult,
    PsseSelection,
    check_install,
    default_install_dir,
    inspect_install,
    load_saved_selection,
    save_selection,
)
from blackbox.report import write_outputs
from blackbox.runs import RunSummary, list_runs, read_run
from presets.ridethrough import RIDE_THROUGH_PRESETS
from ui.blackbox.runs import RunSummaryView, RunTab
from ui.components import button, card, field, label, set_error
from ui.theme import repolish
from ui.widgets import CollapsibleSection, _form, _make_scroll_area

PAGE_EMPTY, PAGE_RUNNING, PAGE_SUMMARY = 0, 1, 2
LEFT_SETUP, LEFT_RECAP = 0, 1
BAD_FOLDER = "This folder does not exist. Choose the folder that holds PSSBIN."
AFTER_A_RUN = (
    "A summary here: pass/fail per standard, worst cases first",
    "A tab for this run with the test explorer: every simulated channel, as interactive plots",
    "An HTML report and a reproducible bundle to save or share",
    "The PSS/E channel files (.outx), with the folder path shown and an Open folder button",
)


def work_root() -> Path:
    """Where runs go: the run folder chosen on the setup screen (kept in settings), else under LOCALAPPDATA."""
    return settings.run_root()


class _CheckThread(QThread):
    finished_check = Signal(object)

    def __init__(self, selection: PsseSelection):
        super().__init__()
        self.selection = selection

    def run(self):
        self.finished_check.emit(check_install(self.selection))


class _RunThread(QThread):
    event = Signal(dict)
    finished_run = Signal(object, object)  # doc, paths (or an exception message)

    def __init__(self, setup: ValidationSetup, folder: Path, dyr_text: str):
        super().__init__()
        self.setup = setup
        self.folder = folder
        self.dyr_text = dyr_text
        self.validation = Validation(setup, folder / "work", on_event=self.event.emit)

    def run(self):
        try:
            doc = self.validation.run()
            paths = write_outputs(doc, self.folder / "work", self.folder, dyr_text=self.dyr_text)
            self.finished_run.emit(doc, paths)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never lost in a thread
            self.finished_run.emit(None, f"{type(exc).__name__}: {exc}")

    def cancel(self):
        self.validation.cancel()


def _section_head(number: str, title: str) -> tuple[QHBoxLayout, QLabel]:
    row = QHBoxLayout()
    row.setSpacing(8)
    mark = QLabel(number)
    mark.setAlignment(Qt.AlignCenter)
    mark.setFixedSize(22, 22)
    row.addWidget(mark)
    row.addWidget(label(title, "cardTitle"))
    row.addStretch()
    return row, mark


def _set_mark(mark: QLabel, state: str, number: str) -> None:
    """A section's state: untouched (its number), failing (!) or ready (✓)."""
    text, fg, bg, border = {"untouched": (number, t.TEXT_MUTED, t.SURFACE, t.CONTROL_BORDER),
                            "failing": ("!", t.TRIP_TEXT, t.TRIP_TINT, t.TRIP_TINT),
                            "ready": ("✓", t.BRAND_DARK, t.BRAND_TINT, t.BRAND_TINT)}[state]
    mark.setText(text)
    mark.setProperty("state", state)
    mark.setStyleSheet(f"border-radius: 11px; border: 1px solid {border}; background: {bg}; color: {fg}; "
                       "font-weight: 600;")


def _row(*widgets, stretch_index: int = 0) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for i, w in enumerate(widgets):
        layout.addWidget(w, stretch=1 if i == stretch_index else 0)
    return holder


class BlackBoxTab(QWidget):
    open_document = Signal(str, str)  # a document under docs/ and a heading anchor (the "Why" link)

    def __init__(self, parent=None, shell=None):
        super().__init__(parent)
        self.shell = shell
        self._check: CheckResult | None = None
        self._check_failed = False
        self._checking = False
        self._check_thread: _CheckThread | None = None
        self._run_thread: _RunThread | None = None
        self._dyr_text = ""
        self._targets: list = []
        self._records: list = []
        self._paths: dict | None = None
        self._cases_done = 0
        self._failed_cases: list[str] = []
        self._started = 0.0
        self._expected_runs = 0
        self.current_run: RunSummary | None = None
        self.previous_runs: list[RunSummary] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        outer.setSpacing(t.GUTTER)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self._build_empty_state())
        self.results_stack.addWidget(self._build_running())
        self.summary_view = RunSummaryView()
        self.summary_view.open_run_tab.connect(self.open_run_tab)
        self.summary_view.open_docs.connect(self.open_document)
        self.results_stack.addWidget(self.summary_view)
        self.left_stack = QStackedWidget()
        self.left_stack.setMinimumWidth(t.LEFT_PANEL_MIN)
        self.left_stack.setMaximumWidth(t.LEFT_PANEL_MAX)
        self.left_stack.addWidget(self._build_setup())
        self.left_stack.addWidget(self._build_recap())
        outer.addWidget(self.left_stack)
        outer.addWidget(self.results_stack, stretch=1)

        self._restore_selection()
        self._refresh_previous_runs()
        self._update_run_enabled()

    # --- the setup panel ----------------------------------------------------------------------------------------

    def _build_setup(self) -> QWidget:
        panel, pl = card(margins=(0, 0, 0, 0), spacing=0)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(t.GUTTER + 2, t.GUTTER, t.GUTTER + 2, t.GUTTER)
        cl.setSpacing(t.FIELD_GAP)
        cl.addWidget(label("Run setup", "panelTitle"))
        cl.addWidget(label("Runs any load model in your own PSS/E and scores it against ride-through standards.",
                           "muted", wrap=True))
        cl.addSpacing(6)
        cl.addLayout(self._build_psse_section())
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)
        cl.addLayout(self._build_model_section())
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)
        cl.addLayout(self._build_tests_section())
        cl.addStretch()
        scroll = _make_scroll_area(content)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pl.addWidget(scroll, stretch=1)

        footer = QWidget()
        footer.setObjectName("cardFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(t.GUTTER + 2, 12, t.GUTTER + 2, 12)
        self.run_button = button("Run tests", self.start_run)
        self.cancel_button = button("Cancel", self._cancel, kind="secondary")
        self.cancel_button.setVisible(False)
        self.run_hint = label("", "muted", wrap=True)
        fl.addWidget(self.run_button)
        fl.addWidget(self.cancel_button)
        fl.addWidget(self.run_hint, stretch=1)
        pl.addWidget(footer)
        return panel

    # 1 · PSS/E install

    def _build_psse_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)
        head, self.psse_mark = _section_head("1", "PSS/E install")
        box.addLayout(head)
        self.version_combo = QComboBox()
        self.version_combo.addItems(SUPPORTED_VERSIONS)
        self.version_combo.setCurrentText("35.6")
        self.version_combo.setMaximumWidth(90)
        self.folder_edit = QLineEdit()
        self.folder_edit.setProperty("mono", True)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(field("Version", self.version_combo))
        row.addWidget(field("Install folder", _row(self.folder_edit, button("Browse…", self._browse_folder,
                                                                           kind="secondary"))), stretch=1)
        box.addLayout(row)
        self.folder_error = label("", "errorText", wrap=True)
        self.folder_error.setVisible(False)
        box.addWidget(self.folder_error)
        self.python_edit = QLineEdit()
        self.python_edit.setPlaceholderText("Found automatically after the check")
        box.addWidget(field("Python interpreter", _row(self.python_edit, button("Browse…", self._browse_python,
                                                                                 kind="secondary"))))
        self.pspy_combo = QComboBox()
        self.pspy_field = field("Python interface (PSSPYxx)", self.pspy_combo)
        box.addWidget(self.pspy_field)
        check_row = QHBoxLayout()
        self.check_button = button("Check install", self._start_check, kind="secondary")
        self.check_status = label("Not checked yet.", "muted", wrap=True)
        check_row.addWidget(self.check_button)
        check_row.addWidget(self.check_status, stretch=1)
        box.addLayout(check_row)
        self.version_combo.currentTextChanged.connect(self._version_changed)
        self.folder_edit.editingFinished.connect(self._folder_changed)
        self.pspy_combo.currentTextChanged.connect(lambda _=None: self._selection_changed())
        self.python_edit.editingFinished.connect(self._selection_changed)
        return box

    def _restore_selection(self):
        saved = load_saved_selection()
        if saved and saved.version in SUPPORTED_VERSIONS:
            self.version_combo.blockSignals(True)
            self.version_combo.setCurrentText(saved.version)
            self.version_combo.blockSignals(False)
            self.folder_edit.setText(saved.install_dir)
            self.python_edit.setText(saved.python_exe)
            self._fill_pspy(saved.pspy_folder)
            if Path(saved.install_dir).is_dir():
                QTimer.singleShot(0, self._start_check)
        else:
            self.folder_edit.setText(default_install_dir(self.version_combo.currentText()))
            self._fill_pspy()

    def _version_changed(self, version: str):
        previous_defaults = {default_install_dir(v) for v in SUPPORTED_VERSIONS}
        if not self.folder_edit.text() or self.folder_edit.text() in previous_defaults:
            self.folder_edit.setText(default_install_dir(version))
        self._folder_changed()

    def _folder_changed(self):
        self.python_edit.clear()
        self._fill_pspy()
        self._selection_changed()

    def _fill_pspy(self, keep: str = ""):
        self.pspy_combo.blockSignals(True)
        self.pspy_combo.clear()
        layout = inspect_install(self.folder_edit.text())
        for name, (major, minor) in layout.pspy_folders:
            self.pspy_combo.addItem(f"{name} (Python {major}.{minor})", name)
        if keep:
            index = self.pspy_combo.findData(keep)
            if index >= 0:
                self.pspy_combo.setCurrentIndex(index)
        self.pspy_combo.blockSignals(False)
        self.pspy_field.setVisible(self.pspy_combo.count() > 1)
        exists = Path(self.folder_edit.text()).is_dir()
        self.folder_error.setText(BAD_FOLDER if not exists else "; ".join(layout.problems))
        self.folder_error.setVisible(not exists or not layout.ok)
        set_error(self.folder_edit, not exists or not layout.ok)
        self.folder_edit.setCursorPosition(0)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "PSS/E install folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(os.path.normpath(folder))
            self._folder_changed()

    def _browse_python(self):
        path, _ = QFileDialog.getOpenFileName(self, "python.exe for PSS/E", self.python_edit.text(),
                                              "Python (python.exe);;All files (*)")
        if path:
            self.python_edit.setText(os.path.normpath(path))
            self._selection_changed()

    def selection(self) -> PsseSelection:
        return PsseSelection(self.version_combo.currentText(), self.folder_edit.text().strip(),
                             self.python_edit.text().strip(), self.pspy_combo.currentData() or "")

    def _selection_changed(self):
        self._check = None
        self._check_failed = False
        self._set_status("Not checked yet.", "muted")
        self._update_run_enabled()

    def _set_status(self, text: str, kind: str):
        self.check_status.setText(text)
        self.check_status.setObjectName("errorText" if kind == "bad" else "muted")
        self.check_status.setStyleSheet(f"color: {t.BRAND_TEXT};" if kind == "ok" else "")
        repolish(self.check_status)

    def _start_check(self):
        if self._checking:
            return  # _check_done starts another if the selection changed meanwhile
        self._checking = True
        self.check_button.setEnabled(False)
        self._set_status("Starting PSS/E…", "muted")
        self._check_thread = _CheckThread(self.selection())
        self._check_thread.finished_check.connect(self._check_done)
        self._check_thread.start()

    def _check_done(self, result: CheckResult):
        self._checking = False
        self.check_button.setEnabled(True)
        current = self.selection()
        if (result.selection.version, result.selection.install_dir) != (current.version, current.install_dir):
            # The selection changed while PSS/E started: this answer is for the old one, so it must not stand.
            self._start_check()
            return
        self._check = result if result.ok else None
        self._check_failed = not result.ok
        self._set_status(result.message, "ok" if result.ok else "bad")
        if result.ok:
            if not self.python_edit.text():
                self.python_edit.setText(result.selection.python_exe)
            save_selection(result.selection)
        self._update_run_enabled()

    # 2 · Model

    def _build_model_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)
        head, self.model_mark = _section_head("2", "Model")
        box.addLayout(head)
        self.dyr_edit = QLineEdit()
        self.dyr_edit.setReadOnly(True)
        self.dyr_edit.setPlaceholderText("Choose a .dyr file")
        box.addWidget(field(".dyr file", _row(self.dyr_edit, button("Browse…", self._browse_dyr, kind="secondary"))))

        dll_box = QFrame()
        dll_box.setObjectName("dashedBox")
        dll_box.setAttribute(Qt.WA_StyledBackground, True)
        dl = QHBoxLayout(dll_box)
        dl.setContentsMargins(10, 8, 10, 8)
        self.dll_stack = QStackedWidget()
        self.dll_empty = label("No DLLs added. Library models need none.", "muted", wrap=True)
        self.dll_list = QListWidget()
        self.dll_list.setFrameShape(QFrame.NoFrame)
        self.dll_stack.addWidget(self.dll_empty)
        self.dll_stack.addWidget(self.dll_list)
        self.dll_stack.setMaximumHeight(84)
        dl.addWidget(self.dll_stack, stretch=1)
        dll_buttons = QVBoxLayout()
        dll_buttons.addWidget(button("Add DLL…", self._add_dll, kind="small"))
        self.remove_dll_button = button("Remove", self._remove_dlls, kind="small")
        dll_buttons.addWidget(self.remove_dll_button)
        dll_buttons.addStretch()
        dl.addLayout(dll_buttons)
        box.addWidget(field("Model DLLs", dll_box))
        self._sync_dlls()

        self.target_combo = QComboBox()
        self.target_combo.setMinimumContentsLength(12)
        self.target_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.target_combo.setPlaceholderText("Loads in the .dyr are listed here")
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        box.addWidget(field("Load to test", self.target_combo,
                            hint="The first load in the file is picked automatically. Change it only if the .dyr "
                                 "holds several."))
        self.flags_label = label("", None, wrap=True)
        self.flags_label.setStyleSheet(f"color: {t.WARNING_TEXT};")
        box.addWidget(self.flags_label)
        self.placement_text = QPlainTextEdit()
        self.placement_text.setObjectName("monoText")
        self.placement_text.setReadOnly(True)
        self.placement_text.setMinimumHeight(120)
        placement = CollapsibleSection("Records as they will run", expanded=False)
        lay = QVBoxLayout()
        lay.addWidget(self.placement_text)
        placement.set_content_layout(lay)
        box.addWidget(placement)
        return box

    def _browse_dyr(self):
        start = settings.get(settings.LAST_DYR_DIR, "")
        path, _ = QFileDialog.getOpenFileName(self, "Open .dyr", start, "DYR Files (*.dyr);;All files (*)")
        if path:
            settings.set_value(settings.LAST_DYR_DIR, str(Path(path).parent))
            self.load_dyr(path)

    def load_dyr(self, path: str):
        try:
            self._dyr_text = Path(path).read_text(errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "Black-box validation", f"Could not read {path}: {exc}")
            return
        self.dyr_edit.setText(os.path.normpath(path))
        self.dyr_edit.setCursorPosition(0)
        self._records = scan_dyr(self._dyr_text)
        self._targets = load_targets(self._records)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for target in self._targets:
            self.target_combo.addItem(target.label)
        self.target_combo.setCurrentIndex(0 if self._targets else -1)  # the first load, picked automatically
        self.target_combo.blockSignals(False)
        if not self._targets:
            self.flags_label.setText("This file has no load-model record to test.")
            self.placement_text.setPlainText("\n".join(r.label for r in self._records))
        self._target_changed()

    def _target_changed(self, _=None):
        index = self.target_combo.currentIndex()
        if not self._targets or index < 0:
            self._update_run_enabled()
            return
        placed = place_on_rig(self._records, self._targets[index])
        self.flags_label.setText("\n".join(placed.flags))
        self.placement_text.setPlainText("\n".join([*placed.records, "", *placed.notes]))
        self._update_run_enabled()

    def _add_dll(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Model DLLs", "", "DLL (*.dll);;All files (*)")
        self.add_dlls(paths)

    def add_dlls(self, paths) -> None:
        existing = set(self.dlls())
        for p in paths:
            p = os.path.normpath(p)
            if p not in existing:
                self.dll_list.addItem(QListWidgetItem(p))
                existing.add(p)
        self._sync_dlls()

    def _remove_dlls(self):
        for item in self.dll_list.selectedItems():
            self.dll_list.takeItem(self.dll_list.row(item))
        self._sync_dlls()

    def _sync_dlls(self):
        self.dll_stack.setCurrentIndex(1 if self.dll_list.count() else 0)
        self.remove_dll_button.setVisible(self.dll_list.count() > 0)

    def dlls(self) -> tuple[str, ...]:
        return tuple(self.dll_list.item(i).text() for i in range(self.dll_list.count()))

    # 3 · Tests

    def _build_tests_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)
        head, self.tests_mark = _section_head("3", "Tests")
        box.addLayout(head)
        self.level_combo = QComboBox()
        self.level_combo.setMinimumContentsLength(12)
        self.level_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for lid, level in LEVELS.items():
            self.level_combo.addItem(f"{level.title} · {level.runs_text}", lid)
        self.level_combo.setCurrentIndex(1)
        self.level_combo.currentIndexChanged.connect(self._level_changed)
        box.addWidget(field("Test level", self.level_combo))
        self.coverage = QLabel()
        self.coverage.setObjectName("subtleBox")
        self.coverage.setAttribute(Qt.WA_StyledBackground, True)
        self.coverage.setTextFormat(Qt.RichText)
        self.coverage.setWordWrap(True)
        self.coverage.setContentsMargins(10, 8, 10, 8)
        box.addWidget(self.coverage)
        box.addWidget(label("Each test finds the longest event the load rides through. The voltages and frequencies "
                            "where a chosen standard's limits change are always added.", "muted", wrap=True))

        box.addWidget(label("Compare with", "fieldLabel"))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(6)
        self.preset_checks: dict[str, QCheckBox] = {}
        for i, (pid, preset) in enumerate(RIDE_THROUGH_PRESETS.items()):
            short = preset.label if len(preset.label) <= 24 else preset.label.split(" (")[0]
            check = QCheckBox(short)
            check.setChecked(preset.category != "Generic")
            check.setToolTip(f"{preset.label}\n{preset.short_source}")
            check.toggled.connect(lambda _=False: self._update_run_enabled())
            grid.addWidget(check, i // 2, i % 2)
            self.preset_checks[pid] = check
        box.addLayout(grid)

        self.run_folder_edit = QLineEdit(str(work_root()))
        self.run_folder_edit.setProperty("mono", True)
        self.run_folder_edit.setReadOnly(True)
        self.run_folder_edit.setCursorPosition(0)
        box.addWidget(field("Run folder (report, bundle and .outx channel files)",
                            _row(self.run_folder_edit, button("Browse…", self._browse_run_folder, kind="secondary")),
                            hint="Each run gets its own date-and-time subfolder."))

        self.advanced_link = button("Advanced options ›", self._toggle_advanced, kind="link")
        box.addWidget(self.advanced_link, alignment=Qt.AlignLeft)
        self.advanced = QWidget()
        adv = _form(self.advanced)
        self.delt_spin = QDoubleSpinBox()
        self.delt_spin.setDecimals(6)
        self.delt_spin.setRange(0.0, 0.05)
        self.delt_spin.setSingleStep(0.000521)
        self.delt_spin.setSpecialValueText("chosen by the time-step check")
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 32)
        self.workers_spin.setValue(4)
        self.p_spin = QDoubleSpinBox()
        self.p_spin.setRange(0.1, 10000.0)
        self.p_spin.setValue(100.0)
        self.q_spin = QDoubleSpinBox()
        self.q_spin.setRange(-5000.0, 5000.0)
        self.q_spin.setValue(20.0)
        self.map_icons = QCheckBox("Map the record's own bus ICONs to the rig bus")
        self.map_icons.setToolTip("ICONs equal to the record's own bus point at the rig bus")
        self.map_icons.setChecked(True)
        adv.addRow("Time step (s)", self.delt_spin)
        adv.addRow("Parallel PSS/E runs", self.workers_spin)
        adv.addRow("Rig load (MW)", self.p_spin)
        adv.addRow("Rig load (Mvar)", self.q_spin)
        adv.addRow(self.map_icons)
        self.advanced.setVisible(False)
        box.addWidget(self.advanced)
        self._level_changed()
        return box

    def _toggle_advanced(self):
        show = not self.advanced.isVisible()
        self.advanced.setVisible(show)
        self.advanced_link.setText("Advanced options ⌄" if show else "Advanced options ›")

    def _level_changed(self, _=None):
        lines = coverage_lines(self.level_combo.currentData())
        items = "".join(f"<li><b>{title}</b>{': ' + detail if detail else ''}</li>" for title, detail in lines)
        self.coverage.setText(f"<ul style='margin:0 0 0 -24px;'>{items}</ul>")
        if hasattr(self, "check_rows"):
            self._update_run_enabled()

    def _browse_run_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Run folder", self.run_folder_edit.text())
        if folder:
            self.set_run_root(folder)

    def set_run_root(self, folder) -> None:
        settings.set_run_root(os.path.normpath(str(folder)))
        self.run_folder_edit.setText(str(work_root()))
        self.run_folder_edit.setCursorPosition(0)
        self._refresh_previous_runs()

    def preset_ids(self) -> tuple[str, ...]:
        return tuple(pid for pid, check in self.preset_checks.items() if check.isChecked())

    # --- readiness and running ----------------------------------------------------------------------------------

    def _has_target(self) -> bool:
        return bool(self._targets) and self.target_combo.currentIndex() >= 0

    def readiness(self) -> dict[str, tuple[str, str]]:
        """(state, text) for the three setup sections: state is untouched, failing or ready."""
        folder_ok = Path(self.folder_edit.text()).is_dir()
        if self._check is not None:
            psse = ("ready", f"{self._check.selection.version} ready")
        elif not folder_ok:
            psse = ("failing", "Folder not found")
        elif self._check_failed:
            psse = ("failing", "Check failed")
        else:
            psse = ("untouched", "Not checked yet")
        if self._has_target():
            model = ("ready", Path(self.dyr_edit.text()).name)
        elif self._dyr_text:
            model = ("failing", "No load-model record")
        else:
            model = ("untouched", "No .dyr file chosen")
        level = LEVELS[self.level_combo.currentData()].title
        n = len(self.preset_ids())
        tests = ("ready", f"{level} level · {n} standard{'s' if n != 1 else ''}")
        return {"psse": psse, "model": model, "tests": tests}

    def _update_run_enabled(self):
        if not (hasattr(self, "check_rows") and hasattr(self, "run_button")):
            return  # still building
        running = bool(self._run_thread and self._run_thread.isRunning())
        ready = self.readiness()
        _set_mark(self.psse_mark, ready["psse"][0], "1")
        _set_mark(self.model_mark, ready["model"][0], "2")
        _set_mark(self.tests_mark, ready["tests"][0], "3")
        for key, (state, text) in ready.items():
            mark, status = self.check_rows[key]
            _set_mark(mark, state, "")
            status.setText(text)
            status.setStyleSheet(f"color: {t.TRIP};" if state == "failing" else f"color: {t.TEXT_MUTED};")
        can_run = self._check is not None and self._has_target() and not running
        self.run_button.setEnabled(can_run)
        self.run_button.setVisible(not running)
        self.cancel_button.setVisible(running)
        failing = ready["psse"][0] == "failing"
        if running:
            hint = "Running…"
        elif self._check is None and not self._has_target():
            hint = ("Fix" if failing else "Check") + " the PSS/E install, then choose a .dyr file."
        elif self._check is None:
            hint = ("Fix" if failing else "Check") + " the PSS/E install first."
        elif not self._has_target():
            hint = "Choose a .dyr file with a load model."
        else:
            hint = ""
        self.run_hint.setText(hint)

    def start_run(self):
        if self._check is None or not self._has_target():
            return
        folder = work_root() / time.strftime("%Y%m%d-%H%M%S")
        setup = ValidationSetup(
            self._check.selection, self._dyr_text, target_index=self.target_combo.currentIndex(), dlls=self.dlls(),
            preset_ids=self.preset_ids(), level=self.level_combo.currentData(),
            delt=self.delt_spin.value() or None, workers=self.workers_spin.value(), p_mw=self.p_spin.value(),
            q_mvar=self.q_spin.value(), map_own_bus_icons=self.map_icons.isChecked(),
            dyr_name=Path(self.dyr_edit.text()).name)
        self._paths = None
        self._cases_done = 0
        self._failed_cases = []
        self._started = time.time()
        self._expected_runs = LEVELS[setup.level].approx_runs
        self.log.clear()
        self.failed_list.clear()
        self.failed_box.setVisible(False)
        self.progress.setRange(0, self._expected_runs)
        self.progress.setValue(0)
        self.running_title.setText(f"Running · {LEVELS[setup.level].title} level")
        self.stage_label.setText("Starting…")
        self.running_folder.setText(str(folder))
        self.left_stack.setCurrentIndex(LEFT_SETUP)
        self.results_stack.setCurrentIndex(PAGE_RUNNING)
        self._run_thread = _RunThread(setup, folder, self._dyr_text)
        self._run_thread.event.connect(self._on_event)
        self._run_thread.finished_run.connect(self._run_done)
        self._run_thread.start()
        self._tick.start()
        self._update_run_enabled()
        self._log(f"Working folder: {folder}")

    def _cancel(self):
        if self._run_thread:
            self._run_thread.cancel()
            self._log("Cancelling: runs already started will finish first.")
            self.stage_label.setText("Cancelling…")

    def _on_event(self, event: dict):
        kind = event.get("kind")
        if kind == "stage":
            self.stage_label.setText(f"{event['stage'].replace('_', ' ').capitalize()}: {event['message']}")
            self._log(f"== {event['message']}")
        elif kind == "case":
            self._cases_done += 1
            self.progress.setMaximum(max(self._expected_runs, self._cases_done))
            self.progress.setValue(self._cases_done)
            self._update_counter()
            if event.get("status") != "ok":
                text = f"{event.get('label')}: {event.get('status')}"
                self._failed_cases.append(text)
                self.failed_list.addItem(text)
                self.failed_box.setVisible(True)
                self._log(text)
        elif kind == "diagnosis":
            self._log(f"Action: {event['action']} ({event['reason']})")
        elif kind == "license_backoff":
            self._log(f"PSS/E refused a license; now running {event['workers']} at a time.")

    def _update_counter(self):
        elapsed = int(time.time() - self._started)
        self.counter_label.setText(f"{self._cases_done} of about {self._expected_runs} cases done · "
                                   f"{elapsed // 60}:{elapsed % 60:02d} elapsed")

    def _run_done(self, doc, paths):
        self._tick.stop()
        self._update_counter()
        if doc is None:
            self.stage_label.setText("The validation failed to run.")
            self._log(str(paths))
            QMessageBox.warning(self, "Black-box validation", str(paths))
        else:
            self._paths = paths
            self.stage_label.setText(doc["stopped"] and f"Stopped: {doc['stopped']}" or "Finished.")
            self._refresh_previous_runs()
            self.show_run(paths["json"].parent)
        self._update_run_enabled()

    def _log(self, text: str):
        self.log.appendPlainText(text)

    # --- the right-hand pages -------------------------------------------------------------------------------------

    def _build_empty_state(self) -> QWidget:
        frame, layout = card(margins=(48, 40, 48, 40))
        layout.addStretch(2)
        inner = QWidget()
        inner.setMaximumWidth(560)
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(10)
        il.addWidget(label("No results yet", "emptyTitle"))
        il.addWidget(label("A run drives your PSS/E through voltage and frequency events, records how the load trips "
                           "and reconnects, and scores each response against the standards you pick.", "muted",
                           wrap=True))
        il.addSpacing(6)
        self.check_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title in (("psse", "PSS/E install"), ("model", "Model"), ("tests", "Tests")):
            row = QHBoxLayout()
            mark = QLabel()
            mark.setFixedSize(22, 22)
            mark.setAlignment(Qt.AlignCenter)
            status = label("", "muted")
            row.addWidget(mark)
            row.addWidget(label(title))
            row.addStretch()
            row.addWidget(status)
            il.addLayout(row)
            self.check_rows[key] = (mark, status)
        il.addSpacing(8)
        after = QFrame()
        after.setObjectName("subtleBox")
        after.setAttribute(Qt.WA_StyledBackground, True)
        al = QVBoxLayout(after)
        al.setContentsMargins(14, 12, 14, 12)
        al.addWidget(label("After a run you get", "sectionLabel"))
        for text in AFTER_A_RUN:
            al.addWidget(label(f"•  {text}", None, wrap=True))
        il.addWidget(after)
        self.empty_previous = QFrame()
        pl = QVBoxLayout(self.empty_previous)
        pl.setContentsMargins(0, 8, 0, 0)
        pl.addWidget(label("Previous runs", "sectionLabel"))
        self.empty_runs_list = QListWidget()
        self.empty_runs_list.setMaximumHeight(130)
        self.empty_runs_list.itemClicked.connect(self._open_previous_item)
        pl.addWidget(self.empty_runs_list)
        pl.addWidget(button("Open results…", self._open_results_dialog, kind="small"), alignment=Qt.AlignLeft)
        il.addWidget(self.empty_previous)
        layout.addWidget(inner, alignment=Qt.AlignHCenter)
        layout.addStretch(3)
        return frame

    def _build_running(self) -> QWidget:
        frame, layout = card(margins=(28, 24, 28, 24))
        self.running_title = label("Running", "panelTitle")
        layout.addWidget(self.running_title)
        self.stage_label = label("Choose a PSS/E install and a model, then Run tests.", None, wrap=True)
        layout.addWidget(self.stage_label)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.counter_label = label("", "mono")
        self.counter_label.setStyleSheet(f"color: {t.TEXT_MUTED};")
        layout.addWidget(self.counter_label)
        layout.addWidget(label("The count is an estimate: each search stops once its boundary is found.", "muted",
                               wrap=True))
        folder_row = QHBoxLayout()
        folder_row.addWidget(label("Run folder", "muted"))
        self.running_folder = label("", "mono")
        self.running_folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
        folder_row.addWidget(self.running_folder, stretch=1)
        layout.addLayout(folder_row)
        self.failed_box = QFrame()
        fl = QVBoxLayout(self.failed_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(label("Cases that did not complete", "sectionLabel"))
        self.failed_list = QListWidget()
        self.failed_list.setMaximumHeight(120)
        fl.addWidget(self.failed_list)
        self.failed_box.setVisible(False)
        layout.addWidget(self.failed_box)
        layout.addWidget(label("Log", "sectionLabel"))
        self.log = QPlainTextEdit()
        self.log.setObjectName("monoText")
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_counter)
        return frame

    def _build_recap(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.GUTTER)
        recap, rl = card()
        head = QHBoxLayout()
        head.addWidget(label("Run setup", "panelTitle"))
        head.addStretch()
        head.addWidget(button("Edit setup", self.edit_setup, kind="small"))
        rl.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.recap_values: dict[str, QLabel] = {}
        for row, key in enumerate(("PSS/E", "Model", "DLL", "Level", "Compared")):
            grid.addWidget(label(key, "muted"), row, 0, alignment=Qt.AlignTop)
            value = label("", "mono", wrap=True)
            grid.addWidget(value, row, 1)
            self.recap_values[key] = value
        grid.setColumnStretch(1, 1)
        rl.addLayout(grid)
        self.run_again_button = button("Run again", self.run_again)
        rl.addWidget(self.run_again_button, alignment=Qt.AlignLeft)
        layout.addWidget(recap)

        runs, pl = card()
        pl.addWidget(label("Previous runs", "sectionLabel"))
        self.runs_list = QListWidget()
        self.runs_list.setFrameShape(QFrame.NoFrame)
        self.runs_list.itemClicked.connect(self._open_previous_item)
        pl.addWidget(self.runs_list, stretch=1)
        pl.addWidget(button("Open results…", self._open_results_dialog, kind="small"), alignment=Qt.AlignLeft)
        layout.addWidget(runs, stretch=1)
        return holder

    # --- runs ---------------------------------------------------------------------------------------------------

    def _refresh_previous_runs(self) -> None:
        self.previous_runs = list_runs(work_root())
        for listing in (self.runs_list, self.empty_runs_list):
            listing.clear()
            for run in self.previous_runs:
                item = QListWidgetItem(f"{run.title}\n{run.date_text(year=False)} · {run.cases} cases")
                item.setData(Qt.UserRole, str(run.folder))
                listing.addItem(item)
        self.empty_previous.setVisible(bool(self.previous_runs))
        self._mark_current_run()

    def _mark_current_run(self) -> None:
        current = str(self.current_run.folder) if self.current_run else None
        for i in range(self.runs_list.count()):
            item = self.runs_list.item(i)
            item.setSelected(item.data(Qt.UserRole) == current)

    def _open_previous_item(self, item: QListWidgetItem) -> None:
        self.show_run(item.data(Qt.UserRole))

    def _open_results_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open a run folder", str(work_root()))
        if folder:
            self.show_run(folder)

    def show_run(self, folder) -> RunSummary | None:
        """Show a run's summary (from its folder) with its setup recap on the left."""
        try:
            self.current_run = self.summary_view.show_run(folder)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Black-box validation", f"{folder} is not a run folder: {exc}")
            return None
        doc, run = self.summary_view.doc, self.current_run
        sel = doc.get("environment", {}).get("selection", {})
        python = f" · Python {run.python}" if run.python else ""
        self.recap_values["PSS/E"].setText(f"{run.psse_version or sel.get('version', '')}{python}")
        self.recap_values["Model"].setText(f"{run.dyr_name} · {run.model}")
        self.recap_values["DLL"].setText(", ".join(Path(d).name for d in run.dlls) or "none")
        self.recap_values["Level"].setText(run.level_title)
        self.recap_values["Compared"].setText(", ".join(name for name, _v, _p in run.compared) or "none")
        self.left_stack.setCurrentIndex(LEFT_RECAP)
        self.results_stack.setCurrentIndex(PAGE_SUMMARY)
        self._mark_current_run()
        return run

    def edit_setup(self) -> None:
        """Back to the setup, filled with the shown run's level and standards."""
        doc = self.summary_view.doc if self.current_run is not None else None
        if doc:
            index = self.level_combo.findData(doc.get("setup", {}).get("level"))
            if index >= 0:
                self.level_combo.setCurrentIndex(index)
            compared = {p["id"] for p in doc.get("setup", {}).get("presets", [])} or set(doc.get("comparison", {}))
            if compared:
                for pid, check in self.preset_checks.items():
                    check.setChecked(pid in compared)
        self.left_stack.setCurrentIndex(LEFT_SETUP)
        self.results_stack.setCurrentIndex(PAGE_EMPTY)
        self._update_run_enabled()

    def run_again(self) -> None:
        """The same setup again, into a new run folder."""
        self.edit_setup()
        if self.run_button.isEnabled():
            self.start_run()

    def open_run_tab(self, folder: str) -> QWidget | None:
        if self.shell is None:
            return None
        run = read_run(folder)[1]

        def make():
            tab = RunTab(folder)
            tab.show_summary.connect(self._summary_from_tab)
            return tab

        return self.shell.open_run_tab(f"run:{Path(folder).resolve()}", run.tab_title, make)

    def _summary_from_tab(self, folder: str) -> None:
        self.show_run(folder)
        if self.shell is not None:
            self.shell.set_current("blackbox")

    def prefill(self, dyr: str | None = None, dlls=()) -> None:
        """Load a model handed over from another screen (Post-Commissioning's user-defined block)."""
        self.edit_setup()
        if dyr:
            self.load_dyr(dyr)
        self.add_dlls(list(dlls))
        self._update_run_enabled()

    def shutdown(self):
        """Stop background work when the window closes."""
        if self._run_thread and self._run_thread.isRunning():
            self._run_thread.cancel()
            self._run_thread.wait(30000)
        if self._check_thread and self._check_thread.isRunning():
            self._check_thread.wait(30000)
