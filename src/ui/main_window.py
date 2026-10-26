"""PySide6 desktop app for PERC Studio.

`MainWindow` is the app shell (`ui.shell.AppShell`: app bar with the workflow tabs and
run tabs, version pill, footer) holding the Screening, Post-Commissioning, Black-Box
Validation and Documentation pages. Each model block (Screening's
one block, Post-Commissioning's IT/UPS and VFD blocks) is a `ui.block.BlockController`.

"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import settings
from app import tokens as t
from app.config import DEFAULTS
from editor.dyr_import import ImportedRecord
from editor.model_ui import (
    DLL_MODEL_ID,
    PERC2_DLL_MODEL_ID,
    PERC2_MODEL_ID,
    STANDARD_MODEL_ID,
    ModelUiSpec,
    get_ui_spec,
)
from editor.user_model import USER_DEFINED_ID, USER_DEFINED_LABEL
from export.dyr import build_dyr_text
from export.report import build_html_report
from load_models import get_load_model
from load_models.base import RECORD_SCOPES, record_number
from load_models.clod.cons import CLOD_DISPLAY_FIELDS, derive_clod_params
from preview.model import build_preview
from ui.block import BlockController
from ui.components import (
    LoadSplitBar,
    Stepper,
    button,
    card,
    field,
    grid,
    label,
    section_label,
)

# Moved to their own modules; re-exported so `from ui import ...` keeps working.
from ui.docs import (  # noqa: F401
    DOC_LIBRARY_FILE,
    PRESET_DOCS_DIR,
    USER_DOCS_DIR,
    DocumentationPanel,
    _about_html,
    _documentation_html,
    _DocumentBrowser,
    _heading_slug,
    _table_rows,
)
from ui.preview_view import _PLOTLY_JS, ResponsePreviewPanel  # noqa: F401
from ui.shell import AppShell, TabsCompat
from ui.theme import apply_app_theme as _apply_app_theme
from ui.theme import repolish
from ui.widgets import (  # noqa: F401
    CollapsibleSection,
    RecordSettingsGroup,
    _ClickableLabel,
    _combo,
    _field_label_in_section,
    _field_widget,
    _form,
    _make_scroll_area,
    _perc1_advanced_widget,
    _style_review_table,
)

BLOCK_KEYS = ("screening", "it", "vfd")
IT_MODES = ["Double conversion (online)", "Eco-mode / line-interactive", "Direct-online (no UPS buffering)"]
VFD_MODES = ["Active front-end (regenerative, near-unity PF)", "Standard front-end (diode rectifier)"]
POST_STEPS = ["Site", "IT / UPS", "VFD", "Cooling motors", "Review & export"]
STEP_SITE, STEP_IT, STEP_VFD, STEP_CLOD, STEP_REVIEW = range(5)


def _spin(lo: float, hi: float, value: float, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    spin.setMinimumWidth(70)
    return spin


def _scroll(inner: QWidget, *, horizontal: bool = False) -> QScrollArea:
    area = _make_scroll_area(inner)
    area.setFrameShape(QFrame.NoFrame)
    if not horizontal:
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def _tile() -> QFrame:
    tile = QFrame()
    tile.setObjectName("tile")
    tile.setAttribute(Qt.WA_StyledBackground, True)
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(2)
    return tile


class MainWindow(QMainWindow):
    """Screening + Post-Commissioning + Black-Box Validation + Documentation."""

    def __init__(self, initial_mode: str = "screening") -> None:
        super().__init__()
        self.state = dict(DEFAULTS)
        self.controllers: dict[str, BlockController] = {}
        self.mode_fields: dict[str, QWidget] = {}
        self.setWindowTitle("PERC Studio")
        self.resize(1320, 860)
        self.setMinimumSize(1080, 720)
        _apply_app_theme()

        self.shell = AppShell()
        self.tabs = TabsCompat(self.shell)
        self.screening_tab = self._build_screening_tab()
        self.post_tab = self._build_post_commissioning_tab()
        self.docs_tab = DocumentationPanel()
        self.docs_tab.layout().setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)

        self.shell.add_page("screening", "Screening", self.screening_tab)
        self.shell.add_page("post", "Post-Commissioning", self.post_tab)
        from ui.blackbox.tab import BlackBoxTab

        self.blackbox_tab = BlackBoxTab(shell=self.shell)
        self.blackbox_tab.open_document.connect(self._open_doc)
        self.shell.add_page("blackbox", "Black-Box Validation", self.blackbox_tab)
        self.shell.add_page("docs", "Documentation", self.docs_tab)
        self.setCentralWidget(self.shell)
        self.shell.set_current("post" if initial_mode == "post-commissioning" else "screening")

    # --- compatibility: the per-block names used before the controllers --------------------------------------

    def __getattr__(self, name: str):
        """`pc_<block>_<name>` reads `<name>` from that block's controller (`pc_it_fields`, `pc_vfd_preview`, ...)."""
        if name.startswith("pc_"):
            try:
                controllers = object.__getattribute__(self, "controllers")
            except AttributeError:
                controllers = {}
            for key in BLOCK_KEYS:
                prefix = f"pc_{key}_"
                if name.startswith(prefix) and key in controllers:
                    return getattr(controllers[key], name[len(prefix):])
        raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")

    def controller(self, key: str) -> BlockController:
        return self.controllers[key]

    def closeEvent(self, event) -> None:
        self.shell.shutdown()
        if self.blackbox_tab is not None:
            self.blackbox_tab.shutdown()
        super().closeEvent(event)

    def navigate(self, key: str, **prefill) -> None:
        if key in self.shell.page_keys():
            self.shell.go(key, **prefill)

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    # --- block delegations ---------------------------------------------------------------------------------

    def _schedule_preview_refresh(self, block_key: str) -> None:
        self.controllers[block_key].schedule_refresh()

    def _collect_block_params(self, block_key: str) -> dict:
        return self.controllers[block_key].collect_params()

    def _block_model_id(self, block_key: str) -> str:
        return self.state.get(f"{block_key}_model_id", DLL_MODEL_ID)

    def _block_spec(self, block_key: str) -> ModelUiSpec:
        return self.controllers[block_key].spec

    def _block_mw(self, block_key: str) -> float | None:
        if block_key == "screening":
            return float(self.screening_mw.value()) if "screening_mw" in self.__dict__ else None
        if "pc_vfd_pct" not in self.__dict__:
            return None
        total = float(self.pc_total_mw.value())
        pct = float(self.pc_it_pct.value()) if block_key == "it" else float(self.pc_vfd_pct.value())
        return total * pct / 100.0

    def _refresh_preview(self, block_key: str) -> None:
        self.controllers[block_key].refresh_preview()

    def _apply_preset_to_block(self, block_key: str, preset_id: str) -> None:
        self.controllers[block_key].apply_preset(preset_id)

    def _apply_imported_to_block(self, block_key: str, imported: ImportedRecord, source: str = "") -> None:
        self.controllers[block_key].apply_imported(imported, source)

    def _reset_block_to_preset(self, block_key: str) -> None:
        """Reset: back to the block's baseline (the preset's values, or the imported file's)."""
        self.controllers[block_key].reset()

    def _on_mode_changed(self, block_key: str) -> None:
        self.controllers[block_key].on_mode_changed()

    def _event_kind(self, block_key: str) -> str:
        return self.controllers[block_key].event_kind()

    def _set_event_kind(self, block_key: str, kind: str) -> None:
        self.controllers[block_key].set_event_kind(kind)

    def _fault_duration_s(self, block_key: str) -> float:
        return self.controllers[block_key].fault_duration_s()

    def _fault_voltage_pu(self, block_key: str) -> float:
        return self.controllers[block_key].fault_voltage_pu()

    def _fault_frequency_hz(self, block_key: str) -> float:
        return self.controllers[block_key].fault_frequency_hz()

    def _open_doc(self, name: str, anchor: str = "") -> None:
        """A document under docs/ (such as the black-box guide), scrolled to a heading."""
        path = Path(USER_DOCS_DIR).parent / name
        if not path.is_file():
            return
        self.docs_tab.open_document(path)
        if anchor:
            self.docs_tab._scroll_to_heading(anchor)
        self.shell.set_current("docs")

    def _show_preset_docs(self, block_key: str) -> None:
        """A block's "Preset docs": open its preset's page in the Documentation tab."""
        preset = self.controllers[block_key].active_preset
        if preset is None:
            return
        self.docs_tab.open_document(PRESET_DOCS_DIR / f"{preset.id}.md")
        self.shell.set_current("docs")

    # --- importing a .dyr --------------------------------------------------------------------------------

    def _import_dyr(self, block_key: str) -> None:
        self.controllers[block_key].import_dyr()

    def _choose_dyr_file(self) -> str:
        start = settings.get(settings.LAST_DYR_DIR, "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Import .dyr file", start, "DYR Files (*.dyr);;Text Files (*.txt);;All files (*)")
        if path:
            settings.set_value(settings.LAST_DYR_DIR, str(Path(path).parent))
        return path

    def _choose_dyr_record(self, refs) -> int | None:
        """The index of the record to import, asking only when the file holds several; None if cancelled."""
        if len(refs) == 1:
            return refs[0].index
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose a record to import")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"This file holds {len(refs)} records. Which one should be loaded?"))
        listing = QListWidget()
        for ref in refs:
            listing.addItem(ref.label)
            if not ref.inspectable:
                listing.item(listing.count() - 1).setFlags(Qt.NoItemFlags)
        listing.setCurrentRow(next(r.index for r in refs if r.inspectable))
        listing.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return listing.currentRow() if dialog.exec() == QDialog.Accepted else None

    def _show_import_error(self, text: str) -> None:
        QMessageBox.warning(self, "Import .dyr", text)

    # --- Screening ----------------------------------------------------------------------------------------

    def _build_screening_tab(self) -> QWidget:
        ctrl = BlockController(self, "screening")
        self.controllers["screening"] = ctrl
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.screening_records = RecordSettingsGroup([("load_id_it", "Load ID", "S1")])
        self.screening_records.setVisible(False)
        self.screening_records.scope_combo.setMinimumWidth(220)
        self.screening_records.scope_combo.setMaximumWidth(16777215)
        ctrl.add_model_bar_field(field("PSS/E record", self.screening_records.scope_combo))
        outer.addWidget(ctrl.model_bar)

        body = QHBoxLayout()
        body.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        body.setSpacing(t.GUTTER)
        outer.addLayout(body, stretch=1)

        # Left panel: 1 · Load, 2 · Parameters, pinned actions.
        left, left_layout = card(margins=(0, 0, 0, 0), spacing=0)
        left.setMinimumWidth(t.LEFT_PANEL_MIN)
        left.setMaximumWidth(t.LEFT_PANEL_MAX)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(t.GUTTER + 4, t.GUTTER + 2, t.GUTTER + 4, t.GUTTER)
        cl.setSpacing(t.FIELD_GAP)
        cl.addWidget(section_label("1 · Load"))
        self.screening_name = QLineEdit(self.state["facility_name"])
        self.screening_bus_number = QSpinBox()
        self.screening_bus_number.setRange(1, 999999)
        self.screening_bus_number.setValue(int(self.state["bus_number"]))
        self.screening_bus_name = QLineEdit(self.state["bus_name"])
        self.screening_mw = _spin(0.0, 10000.0, float(self.state["screening_active_power_mw"]), 3)
        self.screening_mvar = _spin(-3000.0, 3000.0, float(self.state["screening_reactive_power_mvar"]), 3)
        load_id = self.screening_records.load_id_edits["load_id_it"]
        g = grid(2)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        g.addWidget(field("Facility name", self.screening_name), 0, 0)
        g.addWidget(field("Load ID", load_id), 0, 1)
        g.addWidget(field("Bus number", self.screening_bus_number), 1, 0)
        g.addWidget(field("Bus name", self.screening_bus_name), 1, 1)
        g.addWidget(field("Active power (MW)", self.screening_mw), 2, 0)
        g.addWidget(field("Reactive power (Mvar)", self.screening_mvar), 2, 1)
        self.screening_number_field = field("Record number", self.screening_records.number_spin)
        g.addWidget(self.screening_number_field, 3, 0)
        cl.addLayout(g)
        self.screening_scope_hint = label("", "fieldHint", wrap=True)
        cl.addWidget(self.screening_scope_hint)
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)
        ctrl.set_parameters_title("2 · Parameters")
        cl.addWidget(ctrl.parameters_panel)
        left_layout.addWidget(_scroll(content), stretch=1)

        footer = QWidget()
        footer.setObjectName("cardFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(t.GUTTER + 4, 12, t.GUTTER + 4, 12)
        fl.setSpacing(8)
        fl.addWidget(button("Save .dyr…", self._save_screening_output))
        fl.addWidget(button("Save report…", self._generate_screening_html_report, kind="secondary"))
        fl.addStretch()
        fl.addWidget(button("View .dyr", self._show_screening_dyr, kind="link"))
        left_layout.addWidget(footer)
        body.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.GUTTER)
        rl.addWidget(ctrl.event_card)
        rl.addWidget(ctrl.preview_stack, stretch=1)
        body.addWidget(_scroll(right), stretch=1)

        # The generated record, kept current; shown by "View .dyr".
        self.screening_output = QPlainTextEdit()
        self.screening_output.setObjectName("monoText")
        self.screening_output.setReadOnly(True)

        for spin in (self.screening_mw, self.screening_mvar, self.screening_bus_number):
            spin.valueChanged.connect(lambda _=None: ctrl.schedule_refresh())
        for edit in (self.screening_name, self.screening_bus_name):
            edit.textChanged.connect(lambda _=None: self._generate_screening_output())
        self.screening_records.changed.connect(self._sync_screening_scope)
        ctrl.preview_updated.connect(lambda _r: self._generate_screening_output())
        ctrl.edits_changed.connect(self._generate_screening_output)
        self._sync_screening_scope()
        return page

    def _sync_screening_scope(self) -> None:
        records = self.screening_records
        scope = RECORD_SCOPES[records.scope_combo.currentData()]
        needs_number = scope.id not in ("bus", "all")
        self.screening_number_field.setVisible(needs_number)
        if needs_number:
            self.screening_number_field.caption.setText(scope.number_label)
        self.screening_scope_hint.setVisible(scope.id != "bus")
        self.screening_scope_hint.setText(records.hint.text())
        self._generate_screening_output()

    def _show_screening_dyr(self) -> None:
        self._generate_screening_output()
        dialog = QDialog(self)
        dialog.setWindowTitle("Generated .dyr")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(self.screening_output.toPlainText())
        view.setObjectName("monoText")
        view.setReadOnly(True)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        save = buttons.addButton("Save .dyr…", QDialogButtonBox.ActionRole)
        save.clicked.connect(self._save_screening_output)
        layout.addWidget(buttons)
        dialog.exec()

    def _state_from_screening_form(self) -> dict:
        return {
            "facility_name": self.screening_name.text() or self.state["facility_name"],
            "bus_number": int(self.screening_bus_number.value()),
            "bus_name": self.screening_bus_name.text() or self.state["bus_name"],
            "screening_active_power_mw": float(self.screening_mw.value()),
            "screening_reactive_power_mvar": float(self.screening_mvar.value()),
            "use_case": self.state["use_case"],
            **self.screening_records.state(),
        }

    def _generate_screening_output(self) -> None:
        if "screening_output" not in self.__dict__:
            return
        ctrl = self.controllers["screening"]
        state = self._state_from_screening_form()
        params = ctrl.collect_params()
        scope = state["record_scope"]
        number = record_number(scope, state["bus_number"], state["subsystem_number"])
        preset = ctrl.active_preset
        model_id = ctrl.model_id
        if model_id in (STANDARD_MODEL_ID, PERC2_MODEL_ID):
            name, suffix = ("PERC2", "2U") if model_id == PERC2_MODEL_ID else ("PERC1", "1U")
            model_lines = [
                (f"/ Model: {name} standard (PSS/E 36.7+, built in, no DLL) - attaches as "
                 f"'{RECORD_SCOPES[scope].model_name('PERC')}{suffix}' under a MAIN{RECORD_SCOPES[scope].suffix}10 "
                 "record."),
                "/ It is a component of a composite load: the load's MW/Mvar come from the power flow (.raw case),",
                "/ and PSS/E ignores the model below 5 MW, below |P/Q| 1.61, or at a bus voltage of 0.97 pu or less.",
            ]
        elif model_id == PERC2_DLL_MODEL_ID:
            model_lines = [
                (f"/ Model: PERC2 DLL v2.3 (PERC2_v35_v2p3.dll / PERC2_v36_v2p3.dll), PSS/E v34-v36 UDM - attaches "
                 f"as '{RECORD_SCOPES[scope].model_name('PERC')}' with 179 CONs."),
                "/ It replaces the PERC1 DLL (both register PERCBL). RAMPA and RAMPUA last CON x LFM.",
                "/ It is a USRLOD model and carries no MW/Mvar of its own; ensure a static Load",
                "/ record with matching bus/ID and this MW/Mvar exists in the power flow (.raw case).",
            ]
        else:
            model_lines = [
                (f"/ Model: PERC1 (Power Electronic Load Model), PSS/E v34/v35 UDM - attaches as "
                 f"'{RECORD_SCOPES[scope].model_name('PERC')}'."),
                "/ PERC1 is a USRLOD model and carries no MW/Mvar of its own; ensure a static Load",
                "/ record with matching bus/ID and this MW/Mvar exists in the power flow (.raw case).",
            ]
        if ctrl.imported is not None:
            source = f"Imported from {ctrl.import_source or ctrl.imported.ref.label}"
        else:
            source = f"Ride-through preset: {preset.label if preset else '(custom)'}"
        edited = ctrl.tracker.edited_count()
        if edited:
            source += f" ({edited} parameter{'s' if edited != 1 else ''} edited)"
        lines = [
            f"/ Screening load model generated on {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"/ Facility: {state['facility_name']} | Bus: {state['bus_number']} ({state['bus_name']})",
            f"/ {source}",
            (f"/ Approximate load: {state['screening_active_power_mw']:.3f} MW, "
             f"{state['screening_reactive_power_mvar']:.3f} Mvar"),
            *model_lines,
            "/",
            get_load_model(model_id).build_dyr_record(number, state["load_id_it"], params, scope=scope),
        ]
        self.screening_output.setPlainText("\n".join(lines) + "\n")

    def _save_screening_output(self) -> None:
        self._generate_screening_output()
        text = self.screening_output.toPlainText()
        path, _ = QFileDialog.getSaveFileName(self, "Save .dyr file", "screening_model.dyr",
                                              "DYR Files (*.dyr);;Text Files (*.txt)")
        if path:
            Path(path).write_text(text, encoding="utf-8")

    def _state_from_screening_report_form(self) -> dict:
        """Screening's single block in the shape `build_html_report` expects. `report_kind: "screening"` gives
        the abbreviated, PERC1-only report: Screening models one load, not a facility composition."""
        ctrl = self.controllers["screening"]
        base = self._state_from_screening_form()
        preset = ctrl.active_preset
        state = {
            "facility_name": base["facility_name"],
            "bus_number": base["bus_number"],
            "bus_name": base["bus_name"],
            "report_kind": "screening",
            "total_mw": base["screening_active_power_mw"],
            "reactive_mvar": base["screening_reactive_power_mvar"],
            "power_factor": 0.99,
            "pct_it": 100.0,
            "pct_cooling_vfd": 0.0,
            "pct_cooling_motor": 0.0,
            "pct_other": 0.0,
            "it_ups_mode": "Direct-online (no UPS buffering)",
            "include_vfd_block": False,
            "include_motor_block": False,
            "it_advanced": True,
            "vfd_advanced": False,
            "motor_advanced": False,
            "it_data_confidence": "Placeholder (screening estimate) - not yet field-validated",
            "vfd_data_confidence": "Placeholder (screening estimate) - not yet field-validated",
            "load_id_vfd": "2",
            "load_id_motor": "3",
            **self.screening_records.state(),
            "prepared_by": "",
            "data_source_note": "Screening-level estimate - not yet field-validated.",
            "gen_notes": "",
            "has_onsite_gen": False,
            "use_case": self.state["use_case"],
            "use_case_pct": self.state["use_case_pct"],
            "it_preset": preset,
            "vfd_preset": None,
            "it_fault_duration_s": ctrl.fault_duration_s(),
            "it_fault_voltage_pu": ctrl.fault_voltage_pu(),
            "it_event_kind": ctrl.event_kind(),
            "it_fault_frequency_hz": ctrl.fault_frequency_hz(),
        }
        state["it_model_id"] = ctrl.model_id
        # Every CON, not just the editor's fields - see BlockController.collect_params().
        for name, value in ctrl.collect_params().items():
            state[f"it_adv_{name}"] = value
        return state

    def _generate_screening_html_report(self) -> None:
        html = build_html_report(self._state_from_screening_report_form())
        path, _ = QFileDialog.getSaveFileName(self, "Save HTML report", "screening_report.html", "HTML Files (*.html)")
        if path:
            Path(path).write_text(html, encoding="utf-8")

    # --- Post-Commissioning ------------------------------------------------------------------------------

    def _build_post_commissioning_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        for key, modes, title in (("it", IT_MODES, "IT / UPS model"), ("vfd", VFD_MODES, "VFD model")):
            self.controllers[key] = BlockController(self, key, mode_options=modes, allow_user_defined=True,
                                                    model_bar_title=title, version_caption="Model for this block")

        stepper_bar = QWidget()
        stepper_bar.setObjectName("stepperBar")
        stepper_bar.setAttribute(Qt.WA_StyledBackground, True)
        sb = QHBoxLayout(stepper_bar)
        sb.setContentsMargins(t.GUTTER, 8, t.GUTTER + 4, 8)
        self.pc_stepper = Stepper(POST_STEPS)
        self.pc_stepper.step_clicked.connect(self._set_post_step)
        self.pc_step_buttons = self.pc_stepper.buttons
        sb.addWidget(self.pc_stepper)
        sb.addStretch()
        self.pc_site_label = label("", "muted")
        sb.addWidget(self.pc_site_label)
        sb.addSpacing(10)
        self.pc_split_bar = LoadSplitBar()
        self.pc_split_bar.setFixedWidth(250)
        sb.addWidget(self.pc_split_bar)
        outer.addWidget(stepper_bar)

        self.pc_strip_stack = QStackedWidget()
        self.pc_strip_stack.addWidget(QWidget())
        self.pc_strip_stack.addWidget(self.controllers["it"].model_bar)
        self.pc_strip_stack.addWidget(self.controllers["vfd"].model_bar)
        outer.addWidget(self.pc_strip_stack)

        self.pc_step_stack = QStackedWidget()
        self.pc_step_stack.addWidget(self._build_post_step_facility())
        self.pc_step_stack.addWidget(self._build_block_step("it"))
        self.pc_step_stack.addWidget(self._build_block_step("vfd"))
        self.pc_step_stack.addWidget(self._build_post_step_motor())
        self.pc_step_stack.addWidget(self._build_post_step_review())
        outer.addWidget(self.pc_step_stack, stretch=1)

        for key in ("it", "vfd"):
            ctrl = self.controllers[key]
            ctrl.preview_updated.connect(lambda _r, k=key: self._refresh_facility_tiles(k))
            ctrl.model_changed.connect(lambda _m, k=key: self._on_block_model_changed(k))
        for spin in (self.pc_total_mw, self.pc_it_pct):
            spin.valueChanged.connect(lambda _=None: self.controllers["it"].schedule_refresh())
        for spin in (self.pc_total_mw, self.pc_vfd_pct):
            spin.valueChanged.connect(lambda _=None: self.controllers["vfd"].schedule_refresh())
        for widget in (self.pc_total_mw, self.pc_it_pct, self.pc_vfd_pct, self.pc_motor_pct, self.pc_other_pct,
                       self.pc_bus_number):
            widget.valueChanged.connect(lambda _=None: self._update_site_summary())
        self.pc_facility_name.textChanged.connect(lambda _=None: self._update_site_summary())
        self.pc_records.changed.connect(self._update_site_summary)
        self._update_site_summary()
        self._set_post_step(STEP_SITE)
        self._generate_post_output()
        return page

    def _step_footer(self, back: tuple[str, int] | None, forward: tuple[str, int] | None) -> QWidget:
        footer = QWidget()
        footer.setObjectName("cardFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(t.GUTTER + 4, 12, t.GUTTER + 4, 12)
        if back:
            fl.addWidget(button(f"‹ {back[0]}", lambda _=False, i=back[1]: self._set_post_step(i), kind="secondary"))
        fl.addStretch()
        if forward:
            fl.addWidget(button(f"Next: {forward[0]} ›", lambda _=False, i=forward[1]: self._set_post_step(i)))
        return footer

    def _panel_page(self, max_width: int = 900) -> tuple[QWidget, QVBoxLayout, QVBoxLayout]:
        """A step page with one card: (page, the card's scrolling content layout, the card's own layout)."""
        page = QWidget()
        body = QHBoxLayout(page)
        body.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        panel, pl = card(margins=(0, 0, 0, 0), spacing=0)
        panel.setMaximumWidth(max_width)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(t.GUTTER + 4, t.GUTTER + 2, t.GUTTER + 4, t.GUTTER)
        cl.setSpacing(t.FIELD_GAP)
        pl.addWidget(_scroll(content), stretch=1)
        body.addWidget(panel, stretch=1)
        body.addStretch(0)
        return page, cl, pl

    def _build_post_step_facility(self) -> QWidget:
        page, cl, pl = self._panel_page()
        cl.addWidget(label("Site", "panelTitle"))
        cl.addWidget(label("The facility, where it connects, and how its load splits between the blocks.", "muted",
                           wrap=True))
        cl.addSpacing(6)
        cl.addWidget(section_label("Facility"))
        self.pc_facility_name = QLineEdit(self.state["facility_name"])
        self.pc_bus_number = QSpinBox()
        self.pc_bus_number.setRange(1, 999999)
        self.pc_bus_number.setValue(int(self.state["bus_number"]))
        self.pc_bus_name = QLineEdit(self.state["bus_name"])
        g = grid(3)
        g.addWidget(field("Facility name", self.pc_facility_name), 0, 0)
        g.addWidget(field("Bus number", self.pc_bus_number), 0, 1)
        g.addWidget(field("Bus name", self.pc_bus_name), 0, 2)
        cl.addLayout(g)
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)

        cl.addWidget(section_label("Load composition"))
        self.pc_total_mw = _spin(0.0, 10000.0, float(self.state["total_mw"]), 2, " MW")
        self.pc_it_pct = _spin(0.0, 100.0, float(self.state["pct_it"]), 2, " %")
        self.pc_vfd_pct = _spin(0.0, 100.0, float(self.state["pct_cooling_vfd"]), 2, " %")
        self.pc_motor_pct = _spin(0.0, 100.0, float(self.state["pct_cooling_motor"]), 2, " %")
        self.pc_other_pct = _spin(0.0, 100.0, float(self.state["pct_other"]), 2, " %")
        g = grid(5)
        for col, (caption, widget) in enumerate((("Total load", self.pc_total_mw), ("IT / UPS", self.pc_it_pct),
                                                 ("Cooling VFD", self.pc_vfd_pct),
                                                 ("Motors", self.pc_motor_pct), ("Other", self.pc_other_pct))):
            g.addWidget(field(caption, widget), 0, col)
        cl.addLayout(g)
        # A live sum, so a split that doesn't reach 100% is visible here rather than in the exported report.
        self.pc_split_total = QLabel("")
        self.pc_split_total.setObjectName("fieldHint")
        cl.addWidget(self.pc_split_total)
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)

        cl.addWidget(section_label("PSS/E records"))
        self.pc_records = RecordSettingsGroup([
            ("load_id_it", "IT / UPS load ID", "1"),
            ("load_id_vfd", "Cooling VFD load ID", "2"),
            ("load_id_motor", "Motor load ID", "3"),
        ])
        self.pc_records.setTitle("")
        self.pc_records.setStyleSheet("QGroupBox { border: none; margin-top: 0; padding: 0; background: transparent; }")
        cl.addWidget(self.pc_records)
        cl.addStretch()
        pl.addWidget(self._step_footer(None, ("IT / UPS", STEP_IT)))

        for spin in (self.pc_it_pct, self.pc_vfd_pct, self.pc_motor_pct, self.pc_other_pct):
            spin.valueChanged.connect(lambda _=None: self._update_split_total())
        self._update_split_total()
        return page

    def _update_split_total(self) -> None:
        total = sum(spin.value() for spin in (self.pc_it_pct, self.pc_vfd_pct, self.pc_motor_pct, self.pc_other_pct))
        ok = abs(total - 100.0) < 0.01
        color = t.BRAND_TEXT if ok else t.TRIP
        self.pc_split_total.setText(
            f'<span style="color:{color};font-weight:600;">Total {total:.2f} %</span>'
            + ("" if ok else " - the split should add up to 100 %"))

    def _block_line(self, key: str) -> str:
        mw = self._block_mw(key) or 0.0
        pct = self.pc_it_pct.value() if key == "it" else self.pc_vfd_pct.value()
        load_id = self.pc_records.state()[f"load_id_{key}"]
        return f"{mw:.2f} MW · {pct:g} % of facility · load ID {load_id}"

    def _build_block_step(self, key: str) -> QWidget:
        ctrl = self.controllers[key]
        page = QWidget()
        body = QHBoxLayout(page)
        body.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        body.setSpacing(t.GUTTER)

        panel, pl = card(margins=(0, 0, 0, 0), spacing=0)
        panel.setMinimumWidth(t.LEFT_PANEL_MIN)
        panel.setMaximumWidth(t.LEFT_PANEL_MAX)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(t.GUTTER + 4, t.GUTTER + 2, t.GUTTER + 4, t.GUTTER)
        cl.setSpacing(t.FIELD_GAP)
        cl.addWidget(label(ctrl.title, "panelTitle"))
        block_line = label("", "mono")
        block_line.setStyleSheet(f"color: {t.TEXT_MUTED};")
        setattr(self, f"pc_{key}_line_label", block_line)
        cl.addWidget(block_line)
        cl.addSpacing(6)
        default_mode = self.state["it_ups_mode"] if key == "it" else self.state["vfd_type"]
        self.mode_fields[key] = field("Operating mode", ctrl.build_mode_combo(default_mode))
        cl.addWidget(self.mode_fields[key])
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)
        cl.addWidget(ctrl.parameters_panel)
        pl.addWidget(_scroll(content), stretch=1)
        steps = {"it": (("Site", STEP_SITE), ("VFD", STEP_VFD)),
                 "vfd": (("IT / UPS", STEP_IT), ("Cooling motors", STEP_CLOD))}
        pl.addWidget(self._step_footer(*steps[key]))
        body.addWidget(panel)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.GUTTER)
        rl.addWidget(ctrl.event_card)
        rl.addWidget(ctrl.preview_stack, stretch=1)
        tiles_card, tl = card()
        tl.addWidget(label("Facility response to this event", "cardTitle"))
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(12)
        tiles = {}
        for tile_key in ("it", "vfd", "motor", "other"):
            tile = _tile()
            tile.caption, tile.value = label("", "muted"), label("", "cardTitle")
            tile.layout().addWidget(tile.caption)
            tile.layout().addWidget(tile.value)
            tiles_row.addWidget(tile, stretch=1)
            tiles[tile_key] = tile
        tl.addLayout(tiles_row)
        setattr(self, f"pc_{key}_tiles", tiles)
        rl.addWidget(tiles_card)
        right.setMinimumHeight(900)
        body.addWidget(_scroll(right), stretch=1)
        return page

    def _build_post_step_motor(self) -> QWidget:
        page, cl, pl = self._panel_page()
        cl.addWidget(label("Cooling motors", "panelTitle"))
        self.pc_motor_line = label("", "mono")
        self.pc_motor_line.setStyleSheet(f"color: {t.TEXT_MUTED};")
        cl.addWidget(self.pc_motor_line)
        cl.addWidget(label("The motor and ancillary load is a PSS/E CLOD composite load. It is not simulated in the "
                           "live preview.", "muted", wrap=True))
        cl.addSpacing(6)
        self.pc_motor_type = _combo(
            ["Modern - large chillers, mostly VFD elsewhere, some fixed-speed backup",
             "Mixed - moderate mix of large & small motors",
             "Legacy - many small fixed-speed fan/pump motors, older CRAC units"],
            self.state["motor_facility_type"],
        )
        self.pc_motor_lighting = QCheckBox("Includes significant lighting / floor-space load")
        self.pc_motor_lighting.setChecked(bool(self.state["motor_has_lighting"]))
        cl.addWidget(field("Motor facility type", self.pc_motor_type))
        cl.addWidget(self.pc_motor_lighting)
        cl.addSpacing(t.SECTION_GAP - t.FIELD_GAP)
        cl.addWidget(section_label("Motor composition"))
        motor_defaults = derive_clod_params(self.state["motor_facility_type"], bool(self.state["motor_has_lighting"]))
        form = _form()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for field_name, field_label in CLOD_DISPLAY_FIELDS:
            widget = _spin(0.0, 100.0, float(motor_defaults[field_name]), 2)
            setattr(self, f"pc_clod_adv_{field_name.lower()}", widget)
            caption = QLabel(field_label)
            caption.setWordWrap(True)
            form.addRow(caption, widget)
        cl.addLayout(form)
        cl.addStretch()
        pl.addWidget(self._step_footer(("VFD", STEP_VFD), ("Review & export", STEP_REVIEW)))
        return page

    def _build_post_step_review(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        body.setSpacing(t.GUTTER)
        head, hl = card()
        top = QHBoxLayout()
        top.addWidget(label("Review & export", "panelTitle"))
        top.addStretch()
        top.addWidget(button("Save report…", self._generate_post_html_report, kind="secondary"))
        top.addWidget(button("Save .dyr…", self._save_post_output))
        hl.addLayout(top)
        hl.addWidget(label("Each block as it will be written to the facility .dyr and report.", "muted"))
        self.pc_review_cards = QHBoxLayout()
        self.pc_review_cards.setSpacing(12)
        hl.addLayout(self.pc_review_cards)
        body.addWidget(head)
        table_card, tcl = card()
        tcl.addWidget(section_label("Every exported value"))
        self.pc_review = QTableWidget()
        _style_review_table(self.pc_review, 320)
        tcl.addWidget(self.pc_review, stretch=1)
        body.addWidget(table_card, stretch=1)
        nav = QHBoxLayout()
        nav.addWidget(button("‹ Cooling motors", lambda: self._set_post_step(STEP_CLOD), kind="secondary"))
        nav.addStretch()
        body.addLayout(nav)
        return page

    def _review_cards(self, state: dict) -> None:
        while self.pc_review_cards.count():
            item = self.pc_review_cards.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        total = float(state.get("total_mw", 0.0))
        for key, title, pct_key in (("it", "IT / UPS", "pct_it"), ("vfd", "VFD", "pct_cooling_vfd"),
                                    ("motor", "Cooling motors", "pct_cooling_motor"), ("other", "Other", "pct_other")):
            tile = _tile()
            mw = total * float(state.get(pct_key, 0.0)) / 100.0
            tile.layout().addWidget(label(f"{title} · {mw:.2f} MW", "cardTitle"))
            if key in ("it", "vfd"):
                ctrl = self.controllers[key]
                if ctrl.is_user_defined:
                    lines = [USER_DEFINED_LABEL, ctrl.user_model.source_file if ctrl.user_model else "no file chosen"]
                else:
                    source = (f"Imported: {ctrl.import_source}" if ctrl.imported is not None
                              else ctrl.active_preset.label if ctrl.active_preset else "custom")
                    edits = ctrl.tracker.edited_count()
                    lines = [get_ui_spec(ctrl.model_id).choice_label, source,
                             f"{edits} edited" if edits else "no edits"]
            elif key == "motor":
                lines = ["CLOD composite load", self.pc_motor_type.currentText().split(" - ")[0]]
            else:
                lines = ["Static load (not modelled)"]
            for text in lines:
                tile.layout().addWidget(label(text, "muted", wrap=True))
            self.pc_review_cards.addWidget(tile, stretch=1)

    def _update_site_summary(self) -> None:
        if "pc_stepper" not in self.__dict__:
            return
        total = self.pc_total_mw.value()
        shares = [self.pc_it_pct.value(), self.pc_vfd_pct.value(), self.pc_motor_pct.value(), self.pc_other_pct.value()]
        self.pc_split_bar.set_shares(shares)
        self.pc_stepper.set_mw(STEP_SITE, f"{total:g} MW")
        for index, share in ((STEP_IT, shares[0]), (STEP_VFD, shares[1]), (STEP_CLOD, shares[2])):
            self.pc_stepper.set_mw(index, f"{total * share / 100.0:g} MW")
        self.pc_site_label.setText(f"{self.pc_facility_name.text() or self.state['facility_name']} · "
                                   f"bus {self.pc_bus_number.value()}")
        for key in ("it", "vfd"):
            line = self.__dict__.get(f"pc_{key}_line_label")
            if line is not None:
                line.setText(self._block_line(key))
        if "pc_motor_line" in self.__dict__:
            self.pc_motor_line.setText(f"{total * shares[2] / 100.0:.2f} MW · {shares[2]:g} % of facility · load ID "
                                       f"{self.pc_records.state()['load_id_motor']}")
        ok = abs(sum(shares) - 100.0) < 0.01
        self.pc_stepper.set_done({STEP_SITE} if ok else set())

    def _on_block_model_changed(self, key: str) -> None:
        ctrl = self.controllers[key]
        if key in self.mode_fields:
            self.mode_fields[key].setVisible(not ctrl.is_user_defined)
        self._refresh_facility_tiles(key)

    def _refresh_facility_tiles(self, viewed: str) -> None:
        """Every block's response to the event of the block being viewed."""
        tiles = self.__dict__.get(f"pc_{viewed}_tiles")
        if tiles is None:
            return
        event = self.controllers[viewed].current_event()
        total = self.pc_total_mw.value()
        for key, title, pct in (("it", "IT / UPS", self.pc_it_pct.value()), ("vfd", "VFD", self.pc_vfd_pct.value()),
                                ("motor", "Cooling motors", self.pc_motor_pct.value()),
                                ("other", "Other", self.pc_other_pct.value())):
            tile = tiles[key]
            tile.caption.setText(f"{title} · {total * pct / 100.0:g} MW")
            state = ""
            if key == "motor":
                text = "Not modelled in preview"
            elif key == "other":
                text = "Static load"
            elif pct <= 0:
                text = "Not set yet"
            else:
                ctrl = self.controllers[key]
                if ctrl.is_user_defined:
                    text = "User-defined · not simulated in preview"
                else:
                    result = ctrl.last_result if key == viewed else build_preview(
                        ctrl.model_id, ctrl.collect_params(), event, preset=ctrl.active_preset)
                    if result is None:
                        text = "…"
                    else:
                        text = result.tile_text()
                        state = "trips" if result.trips else "rides"
            tile.value.setText(text)
            tile.value.setStyleSheet(f"color: {t.TRIP};" if state == "trips" else "")
            tile.setProperty("state", state)
            repolish(tile)

    def _set_post_step(self, index: int) -> None:
        if "pc_step_stack" not in self.__dict__:
            return
        self.pc_step_stack.setCurrentIndex(index)
        self.pc_stepper.set_current(index)
        self.pc_strip_stack.setCurrentIndex({STEP_IT: 1, STEP_VFD: 2}.get(index, 0))
        self.pc_strip_stack.setVisible(index in (STEP_IT, STEP_VFD))
        if index in (STEP_IT, STEP_VFD):
            self._update_site_summary()
            self.controllers["it" if index == STEP_IT else "vfd"].schedule_refresh()
        if index == STEP_REVIEW:  # Review always shows the current inputs
            self._generate_post_output()

    def _state_from_post_form(self) -> dict:
        it, vfd = self.controllers["it"], self.controllers["vfd"]
        it_preset = it.active_preset if not it.is_user_defined else None
        vfd_preset = vfd.active_preset if not vfd.is_user_defined else None
        state = {
            "facility_name": self.pc_facility_name.text() or self.state["facility_name"],
            "bus_number": int(self.pc_bus_number.value()),
            "bus_name": self.pc_bus_name.text() or self.state["bus_name"],
            "total_mw": float(self.pc_total_mw.value()),
            "power_factor": 0.99,
            "pct_it": float(self.pc_it_pct.value()),
            "pct_cooling_vfd": float(self.pc_vfd_pct.value()),
            "pct_cooling_motor": float(self.pc_motor_pct.value()),
            "pct_other": float(self.pc_other_pct.value()),
            "it_ups_mode": it.mode.currentText(),
            "vfd_type": vfd.mode.currentText(),
            "motor_facility_type": self.pc_motor_type.currentText(),
            "motor_has_lighting": bool(self.pc_motor_lighting.isChecked()),
            "include_vfd_block": bool(self.state["include_vfd_block"]),
            "include_motor_block": bool(self.state["include_motor_block"]),
            "it_advanced": True,
            "vfd_advanced": True,
            "motor_advanced": True,
            "it_data_confidence": "Field-validated (matches as-built equipment/relay settings)",
            "vfd_data_confidence": "Field-validated (matches as-built equipment/relay settings)",
            **self.pc_records.state(),
            "prepared_by": "",
            "data_source_note": "",
            "gen_notes": "",
            "has_onsite_gen": False,
            "use_case": self.state["use_case"],
            "use_case_pct": self.state["use_case_pct"],
            "it_preset": it_preset,
            "vfd_preset": vfd_preset,
            "it_fault_duration_s": it.fault_duration_s(),
            "vfd_fault_duration_s": vfd.fault_duration_s(),
            "it_fault_voltage_pu": it.fault_voltage_pu(),
            "vfd_fault_voltage_pu": vfd.fault_voltage_pu(),
            "it_event_kind": it.event_kind(),
            "vfd_event_kind": vfd.event_kind(),
            "it_fault_frequency_hz": it.fault_frequency_hz(),
            "vfd_fault_frequency_hz": vfd.fault_frequency_hz(),
        }
        # Every CON, not just the editor's fields - see BlockController.collect_params().
        for ctrl in (it, vfd):
            state.update(ctrl.export_state())
        for field_name, _label in CLOD_DISPLAY_FIELDS:
            state[f"clod_adv_{field_name.lower().replace('pc_', '')}"] = float(
                getattr(self, f"pc_clod_adv_{field_name.lower()}").value())
        return state

    def _populate_post_review_table(self, table: QTableWidget, state: dict) -> None:
        total = float(state.get("total_mw", 0.0))
        rows = [
            ("Bus number", state.get("bus_number", "")),
            ("Bus name", state.get("bus_name", "")),
            ("Load MW", f"{total:.2f}"),
            ("IT block MW", f"{total * float(state.get('pct_it', 0.0)) / 100.0:.2f}"),
            ("VFD block MW", f"{total * float(state.get('pct_cooling_vfd', 0.0)) / 100.0:.2f}"),
            ("Motor block MW", f"{total * float(state.get('pct_cooling_motor', 0.0)) / 100.0:.2f}"),
            ("Other block MW", f"{total * float(state.get('pct_other', 0.0)) / 100.0:.2f}"),
            ("IT ride-through preset", state.get("it_preset").label if state.get("it_preset") else "-"),
            ("VFD ride-through preset", state.get("vfd_preset").label if state.get("vfd_preset") else "-"),
        ]
        for block, title in (("it", "IT"), ("vfd", "VFD")):
            model_id = state.get(f"{block}_model_id", DLL_MODEL_ID)
            if model_id == USER_DEFINED_ID:
                rows.append((f"{title} model", USER_DEFINED_LABEL))
                rows.append((f"{title} model file", state.get(f"{block}_user_source", "-")))
                rows.append((f"{title} model DLLs", ", ".join(state.get(f"{block}_user_dlls", [])) or "-"))
                continue
            rows.append((f"{title} model", get_ui_spec(model_id).choice_label))
            for field_name, field_label, _tooltip in get_ui_spec(model_id).display_fields:
                rows.append((f"{title} {field_label}", state.get(f"{block}_adv_{field_name}", "")))
        rows += [
            (f"Motor {field_label}", state.get(f"clod_adv_{field_name.lower().replace('pc_', '')}", ""))
            for field_name, field_label in CLOD_DISPLAY_FIELDS
        ]
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Parameter", "Value"])
        table.setRowCount(len(rows))
        for row_index, (text, value) in enumerate(rows):
            table.setItem(row_index, 0, QTableWidgetItem(str(text)))
            table.setItem(row_index, 1, QTableWidgetItem(str(value)))
        table.setColumnWidth(0, 300)
        table.resizeRowsToContents()

    def _generate_post_output(self) -> None:
        state = self._state_from_post_form()
        self._populate_post_review_table(self.pc_review, state)
        self._review_cards(state)

    def _generate_post_html_report(self) -> None:
        html = build_html_report(self._state_from_post_form())
        path, _ = QFileDialog.getSaveFileName(self, "Save HTML report", "post_commissioning_report.html",
                                              "HTML Files (*.html)")
        if path:
            Path(path).write_text(html, encoding="utf-8")

    def _save_post_output(self) -> None:
        text = build_dyr_text(self._state_from_post_form())
        path, _ = QFileDialog.getSaveFileName(self, "Save .dyr file", "post_commissioning_model.dyr",
                                              "DYR Files (*.dyr);;Text Files (*.txt)")
        if path:
            Path(path).write_text(text, encoding="utf-8")


def render_app() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


__all__ = ["MainWindow", "render_app"]
