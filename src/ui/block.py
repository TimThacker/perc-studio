"""One model block's controller: the Screening block, and the IT/UPS and VFD blocks of
Post-Commissioning.

`BlockController` owns everything that belongs to one block: which model it uses
(PERC1 DLL, PERC1 standard, PERC2 standard, PERC2 DLL, or a user-defined model
from the user's own .dyr), the ride-through preset or imported record its values
start from, the edit tracker, the CON field widgets, the test-event settings, the
verdict strip and the live preview. It builds the widgets; the pages place them.

`MainWindow` keeps its old per-block names (`pc_it_fields`, `_apply_preset_to_block`,
...) as thin delegations to the controllers.
"""

from __future__ import annotations

import os
from html import escape as html_escape

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import tokens as t
from editor.block_state import Baseline, EditTracker
from editor.dyr_import import ImportedRecord, import_record, list_records
from editor.model_ui import (
    DLL_MODEL_ID,
    INTEGER_FIELD_RANGES,
    UI_SPECS,
    ModelUiSpec,
    get_ui_spec,
)
from editor.parameter_rows import rows_for
from editor.user_model import (
    USER_DEFINED_ID,
    USER_DEFINED_LABEL,
    ExternalModel,
    read_external_model,
)
from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS, presets_by_category
from preview.model import Event, PreviewResult, build_preview
from ui.components import (
    ParameterRowWidget,
    SegmentedControl,
    VerdictStrip,
    badge,
    button,
    card,
    field,
    label,
    section_label,
    set_badge,
)
from ui.preview_view import ResponsePreviewPanel
from ui.theme import repolish
from ui.widgets import _field_label_in_section, _field_widget, _form

DEFAULT_PRESET_ID = "standard_itic"
BLOCK_TITLES = {"screening": "Screening block", "it": "IT / UPS block", "vfd": "VFD block"}
_EVENT_OPTIONS = [("voltage", "Voltage event"), ("frequency", "Frequency event")]


def preset_badge(preset) -> tuple[str, str]:
    """(text, badge kind): "Internal" for the app's generic tiers, "Published standard" otherwise."""
    return ("Internal", "internal") if preset.category == "Generic" else ("Published standard", "published")


class BlockController(QObject):
    preview_updated = Signal(object)  # PreviewResult (or None for a user-defined block)
    model_changed = Signal(str)
    edits_changed = Signal()

    def __init__(self, window, key: str, *, mode_options: list[str] | None = None,
                 allow_user_defined: bool = False, model_bar_title: str = "Model",
                 version_caption: str = "Model version") -> None:
        super().__init__(window)
        self.window = window
        self.key = key
        self.state = window.state
        self.title = BLOCK_TITLES.get(key, key)
        self.mode_options = mode_options
        self.allow_user_defined = allow_user_defined
        self.active_preset = None
        self.imported: ImportedRecord | None = None
        self.import_source = ""
        self.user_model: ExternalModel | None = None
        self.tracker = EditTracker(Baseline.defaults({}))
        self.fields: dict[str, QWidget] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.rows: list = []
        self.row_widgets: dict[str, ParameterRowWidget] = {}
        self.inner_sections: list[ParameterRowWidget] = []
        self.last_result: PreviewResult | None = None
        self._loading = False
        self.preset_index_to_id: list[str | None] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh_preview)

        self.state.setdefault(f"{key}_model_id", DLL_MODEL_ID)
        self.state.setdefault(f"{key}_fault_cycles", round(FAULT_DURATION * 60.0))
        self.state.setdefault(f"{key}_fault_depth_pct", round((1.0 - V_FAULT) * 100.0))
        self.state.setdefault(f"{key}_event_kind", "voltage")
        self.state.setdefault(f"{key}_freq_duration_s", round(FREQUENCY_EVENT_DURATION))
        self.state.setdefault(f"{key}_freq_offset_tenths", round((FREQUENCY_EVENT_HZ - NOMINAL_FREQUENCY_HZ) * 10))

        self.model_bar = self._build_model_bar(model_bar_title, version_caption)
        self.parameters_panel = self._build_parameters_panel()
        self.event_card = self._build_event_card()
        self.verdict = VerdictStrip()
        self.preview = ResponsePreviewPanel()
        self.preview_stack = self._build_preview_stack()

        self._rebuild_fields()
        default_preset = self.state.get(f"{key}_preset_id", DEFAULT_PRESET_ID)
        self.apply_preset(default_preset if default_preset in RIDE_THROUGH_PRESETS else DEFAULT_PRESET_ID)

    # --- model ------------------------------------------------------------------------------------------

    @property
    def model_id(self) -> str:
        return self.state.get(f"{self.key}_model_id", DLL_MODEL_ID)

    @property
    def is_user_defined(self) -> bool:
        return self.model_id == USER_DEFINED_ID

    @property
    def spec(self) -> ModelUiSpec:
        return get_ui_spec(self.model_id if not self.is_user_defined else DLL_MODEL_ID)

    def block_mw(self) -> float | None:
        return self.window._block_mw(self.key)

    # --- the model bar ----------------------------------------------------------------------------------

    def _build_model_bar(self, title: str, version_caption: str) -> QWidget:
        bar = QWidget()
        bar.setObjectName("modelBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(t.GUTTER + 4, 10, t.GUTTER, 12)
        row.setSpacing(t.GUTTER)
        self.bar_title = section_label(title)
        row.addWidget(self.bar_title, alignment=Qt.AlignBottom)
        row.addSpacing(8)

        self.model_combo = QComboBox()
        for spec in UI_SPECS.values():
            self.model_combo.addItem(spec.choice_label, spec.model_id)
        if self.allow_user_defined:
            self.model_combo.addItem(USER_DEFINED_LABEL, USER_DEFINED_ID)
        self.model_combo.setToolTip("PERC1 has two PSS/E implementations with different parameters: the DLL model "
                                    "(PSS/E 34/35, 173 CONs) and the built-in standard model (PSS/E 36.7+, 30 CONs). "
                                    "PERC2 standard (PSS/E 36.7+, 6 flags + 57 CONs) adds overvoltage, multi-point "
                                    "and frequency cease checks. PERC2 DLL v2.3 (PSS/E 34-36, 2 flags + 179 CONs) is "
                                    "the PERC1 DLL with momentary cessation and a reactive lead-lag; RAMPA and RAMPUA "
                                    "last CON x LFM.")
        self.model_combo.setMinimumWidth(240)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(self.model_id)))
        self.model_combo.currentIndexChanged.connect(self._on_model_combo)
        row.addWidget(field(version_caption, self.model_combo), alignment=Qt.AlignBottom)

        self.extra_fields_row = QHBoxLayout()
        self.extra_fields_row.setSpacing(t.GUTTER)
        row.addLayout(self.extra_fields_row)

        # The PERC1 variants: a preset (or an imported file) and Import; the user-defined variant: its own files.
        self.bar_stack = QStackedWidget()
        self.bar_stack.addWidget(self._build_perc1_bar())
        self.bar_stack.addWidget(self._build_user_bar())
        row.addWidget(self.bar_stack, stretch=1)
        return bar

    def add_model_bar_field(self, widget: QWidget) -> None:
        """A page-specific field after the model version (Screening's "PSS/E record")."""
        self.extra_fields_row.addWidget(widget, alignment=Qt.AlignBottom)

    def _build_perc1_bar(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # Preset field: caption with badge, combo, Preset docs.
        self.preset_field = QWidget()
        pf = QVBoxLayout(self.preset_field)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.setSpacing(4)
        caption_row = QHBoxLayout()
        caption_row.setSpacing(8)
        cap = label("Ride-through preset", "fieldLabel")
        self.status_label = badge("Internal", "internal")
        caption_row.addWidget(cap)
        caption_row.addStretch()
        caption_row.addWidget(self.status_label)
        pf.addLayout(caption_row)
        self.preset_combo = QComboBox()
        self.preset_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.preset_combo.setMinimumContentsLength(22)
        for category, presets in presets_by_category().items():
            if not presets:
                continue
            self.preset_combo.addItem(f"— {category} —")
            self.preset_combo.model().item(self.preset_combo.count() - 1).setEnabled(False)
            self.preset_index_to_id.append(None)
            for preset in presets:
                self.preset_combo.addItem(preset.label)
                self.preset_index_to_id.append(preset.id)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_combo)
        cap.setBuddy(self.preset_combo)
        pf.addWidget(self.preset_combo)
        row.addWidget(self.preset_field, alignment=Qt.AlignBottom)
        self.docs_button = button("Preset docs", lambda: self.window._show_preset_docs(self.key), kind="link",
                                  tooltip="Open this preset's source, tables and CON mapping")
        row.addWidget(self.docs_button, alignment=Qt.AlignBottom)
        row.itemAt(row.count() - 1).widget().setContentsMargins(0, 0, 0, 8)

        # Imported-file field: replaces the preset field while a record from a .dyr is loaded.
        self.imported_box = QWidget()
        ib = QHBoxLayout(self.imported_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib.setSpacing(12)
        self.imported_field = QLineEdit()
        self.imported_field.setReadOnly(True)
        self.imported_field.setProperty("mono", True)
        self.imported_field.setMinimumWidth(240)
        self.imported_field.setAccessibleName("Imported file")
        ib.addWidget(field("Imported file", self.imported_field), alignment=Qt.AlignBottom)
        self.use_preset_link = button("Use a preset instead", self._use_preset_instead, kind="link")
        ib.addWidget(self.use_preset_link, alignment=Qt.AlignBottom)
        self.imported_box.setVisible(False)
        row.addWidget(self.imported_box, alignment=Qt.AlignBottom)

        row.addStretch(1)
        self.start_from_label = label("or start from an existing file", "muted")
        row.addWidget(self.start_from_label, alignment=Qt.AlignBottom)
        self.import_btn = button("Import .dyr…", lambda: self.window._import_dyr(self.key), kind="secondary",
                                 tooltip="Load a record from an existing .dyr file into this block. The model "
                                         "version switches to match the file.")
        row.addWidget(self.import_btn, alignment=Qt.AlignBottom)
        return holder

    def _build_user_bar(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.user_dyr_edit = QLineEdit()
        self.user_dyr_edit.setReadOnly(True)
        self.user_dyr_edit.setPlaceholderText("Choose your model's .dyr file")
        self.user_dyr_edit.setProperty("mono", True)
        self.user_dyr_edit.setMinimumWidth(240)
        row.addWidget(field("Model .dyr file", self.user_dyr_edit), alignment=Qt.AlignBottom)
        row.addWidget(button("Browse…", self.browse_user_dyr, kind="secondary"), alignment=Qt.AlignBottom)
        self.user_dlls_label = label("No DLLs added", "muted")
        row.addWidget(button("Add DLL…", self.add_user_dll, kind="secondary"), alignment=Qt.AlignBottom)
        row.addWidget(self.user_dlls_label, alignment=Qt.AlignBottom)
        row.addStretch(1)
        self.validate_link = button("Validate it in Black-Box Validation ›", self.open_in_blackbox, kind="link")
        row.addWidget(self.validate_link, alignment=Qt.AlignBottom)
        return holder

    def _update_model_bar(self) -> None:
        self.bar_stack.setCurrentIndex(1 if self.is_user_defined else 0)
        imported = self.imported is not None
        self.preset_field.setVisible(not imported)
        self.docs_button.setVisible(not imported)
        self.imported_box.setVisible(imported)
        self.start_from_label.setVisible(not imported)
        self.import_btn.setText("Import another .dyr…" if imported else "Import .dyr…")
        if imported:
            self.imported_field.setText(self.import_source or self.imported.ref.label)
            self.imported_field.setToolTip(self.imported.ref.label)
            self.imported_field.setCursorPosition(0)
            set_badge(self.status_label, "Imported file", "neutral")
        elif self.active_preset is not None:
            text, kind = preset_badge(self.active_preset)
            set_badge(self.status_label, text, kind)
            self.status_label.setToolTip(self.active_preset.status)
            self.preset_combo.setToolTip(f"{self.active_preset.short_source}\n\n{self.active_preset.citation}")
        if self.user_model is not None:
            self.user_dyr_edit.setText(self.user_model.source_file)
            self.user_dyr_edit.setToolTip(self.user_model.label)
        n = len(self.user_model.dlls) if self.user_model else 0
        self.user_dlls_label.setText("No DLLs added" if not n else f"{n} DLL{'s' if n > 1 else ''}")
        if self.user_model and self.user_model.dlls:
            self.user_dlls_label.setToolTip("\n".join(self.user_model.dlls))

    # --- the parameters panel ---------------------------------------------------------------------------

    def _build_parameters_panel(self) -> QWidget:
        self.parameters_stack = QStackedWidget()
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.parameters_label = section_label("Parameters")
        header.addWidget(self.parameters_label)
        self.edited_pill = badge("0 edited", "edited")
        self.edited_pill.setVisible(False)
        header.addWidget(self.edited_pill)
        header.addStretch()
        self.reset_button = button("Reset to preset", self.reset, kind="small",
                                   tooltip="Return every parameter to the values this block started from")
        header.addWidget(self.reset_button)
        layout.addLayout(header)
        self.baseline_note = label("", "muted", wrap=True)
        layout.addWidget(self.baseline_note)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextFormat(Qt.RichText)
        self.notes_label.setObjectName("fieldHint")
        self.notes_label.setVisible(False)
        layout.addWidget(self.notes_label)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 4, 0, 0)
        self.rows_layout.setSpacing(2)
        layout.addWidget(self.rows_host)
        layout.addStretch()
        self.parameters_stack.addWidget(panel)

        user = QWidget()
        ul = QVBoxLayout(user)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(section_label("Parameters"))
        note = label("<b>User-defined model.</b> Its parameters live in your own .dyr and DLLs, so there is nothing "
                     "to edit here. This block is included in the facility export as it is.", "muted", wrap=True)
        note.setTextFormat(Qt.RichText)
        ul.addWidget(note)
        self.user_record_text = QLabel("")
        self.user_record_text.setObjectName("mono")
        self.user_record_text.setWordWrap(True)
        self.user_record_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ul.addWidget(self.user_record_text)
        ul.addStretch()
        self.parameters_stack.addWidget(user)
        return self.parameters_stack

    def set_parameters_title(self, text: str) -> None:
        self.parameters_label.setText(text.upper())

    def _rebuild_fields(self) -> None:
        """(Re)build the parameter rows and their CON fields from the block's model."""
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        spec = self.spec
        self.fields, self.field_labels, self.row_widgets = {}, {}, {}
        self.rows = rows_for(spec)
        for row in self.rows:
            widget = ParameterRowWidget(row)
            if row.note:
                note = label(row.note, "fieldHint", wrap=True)
                widget.editor_layout.addWidget(note)
            for sub_title, names in row.sections:
                form = _form()
                for name in names:
                    editor = _field_widget(spec, name)
                    text = _field_label_in_section(spec.field_labels[name], sub_title)
                    caption = QLabel(text)
                    caption.setToolTip(spec.field_tooltips[name])
                    caption.setWordWrap(True)
                    caption.setProperty("baseText", text)
                    caption.setBuddy(editor)
                    editor.setToolTip(f"{name}: {spec.field_tooltips[name]}")
                    editor.setMinimumWidth(110)
                    form.addRow(caption, editor)
                    self.fields[name] = editor
                    self.field_labels[name] = caption
                    editor.valueChanged.connect(lambda _=None, n=name: self._on_field_changed(n))
                widget.add_section(sub_title, form)
            widget.revert_button = button("Revert this row", lambda _=False, r=row: self.revert_row(r.id), kind="small")
            widget.revert_button.setEnabled(False)
            widget.editor_layout.addWidget(widget.revert_button, alignment=Qt.AlignRight)
            self.rows_layout.addWidget(widget)
            self.row_widgets[row.id] = widget
        self.inner_sections = list(self.row_widgets.values())

    # --- the event card ---------------------------------------------------------------------------------

    def _build_event_card(self) -> QWidget:
        frame, layout = card(margins=(t.GUTTER, 10, t.GUTTER, 10))
        row = QHBoxLayout()
        row.setSpacing(t.GUTTER + 8)
        layout.addLayout(row)
        self.event_switch = SegmentedControl(_EVENT_OPTIONS, self.event_kind())
        self.event_switch.changed.connect(self.set_event_kind)
        self.kind_group = self.event_switch.group
        row.addWidget(self.event_switch, alignment=Qt.AlignVCenter)
        for prefix, handler in (("fault", self._on_fault_slider), ("depth", self._on_depth_slider)):
            col = QVBoxLayout()
            col.setSpacing(2)
            head = QHBoxLayout()
            name = label("", "fieldLabel")
            value = label("", "mono")
            value.setAlignment(Qt.AlignRight)
            head.addWidget(name)
            head.addStretch()
            head.addWidget(value)
            slider = QSlider(Qt.Horizontal)
            slider.setCursor(Qt.PointingHandCursor)
            slider.valueChanged.connect(handler)
            name.setBuddy(slider)
            col.addLayout(head)
            col.addWidget(slider)
            row.addLayout(col, stretch=1)
            setattr(self, f"{prefix}_name_label", name)
            setattr(self, f"{prefix}_value_label", value)
            setattr(self, f"{prefix}_slider", slider)
        self.configure_sliders()
        return frame

    def _build_preview_stack(self) -> QStackedWidget:
        stack = QStackedWidget()
        live = QWidget()
        lv = QVBoxLayout(live)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(t.GUTTER)
        lv.addWidget(self.verdict)
        lv.addWidget(self.preview, stretch=1)
        stack.addWidget(live)
        frame, layout = card(margins=(28, 28, 28, 28))
        layout.addStretch()
        layout.addWidget(label("No live preview for a user-defined model", "panelTitle"))
        layout.addWidget(label("The live response only runs the built-in PERC models. Your own model for this block runs in your "
                               "PSS/E, so check how it rides through in Black-Box Validation.", "muted", wrap=True))
        open_button = button("Open Black-Box Validation", self.open_in_blackbox)
        layout.addWidget(open_button, alignment=Qt.AlignLeft)
        layout.addStretch()
        stack.addWidget(frame)
        return stack

    # --- event settings ----------------------------------------------------------------------------------

    def event_kind(self) -> str:
        return self.state.get(f"{self.key}_event_kind", "voltage")

    def set_event_kind(self, kind: str) -> None:
        if self.event_kind() == kind:
            self.event_switch.set_current(kind)
            return
        self.state[f"{self.key}_event_kind"] = kind
        self.event_switch.set_current(kind)
        self.configure_sliders()
        if kind == "frequency":
            self.reveal_frequency_rows()
        self.schedule_refresh()

    def reveal_frequency_rows(self) -> None:
        """Switching to frequency events opens the frequency rows, so the band the chart shows is one click from
        adjusting."""
        for row_id in ("frequency_ride_through", "frequency_droop"):
            if row_id in self.row_widgets:
                self.row_widgets[row_id].set_expanded(True)

    def configure_sliders(self) -> None:
        """Voltage: duration 1-600 cycles, depth as a signed % of nominal. Frequency: 1-600 s, tenths of a Hz off
        nominal (56.0-64.0 Hz). Each kind keeps its own settings."""
        frequency = self.event_kind() == "frequency"
        for slider, (lo, hi), key in (
            (self.fault_slider, (1, 600), "freq_duration_s" if frequency else "fault_cycles"),
            (self.depth_slider, (-40, 40) if frequency else (-100, 100),
             "freq_offset_tenths" if frequency else "fault_depth_pct"),
        ):
            slider.blockSignals(True)
            slider.setRange(lo, hi)
            slider.setValue(self.state[f"{self.key}_{key}"])
            slider.blockSignals(False)
        self.fault_name_label.setText("Event duration")
        self.depth_name_label.setText("Frequency" if frequency else "Voltage depth")
        self._update_readouts()

    def _update_readouts(self) -> None:
        if self.event_kind() == "frequency":
            self.fault_value_label.setText(f"{self.state[f'{self.key}_freq_duration_s']} s")
            f = self.fault_frequency_hz()
            self.depth_value_label.setText(f"{f:.1f} Hz ({f - NOMINAL_FREQUENCY_HZ:+.1f} Hz)")
            return
        cycles = self.state[f"{self.key}_fault_cycles"]
        self.fault_value_label.setText(f"{cycles} cycles · {cycles / 60.0:.3f} s")
        pct = self.state[f"{self.key}_fault_depth_pct"]
        word = "sag" if pct >= 0 else "swell"
        self.depth_value_label.setText(f"{abs(pct)} % {word} → {self.fault_voltage_pu():.2f} pu")

    def _on_fault_slider(self, value: int) -> None:
        key = "freq_duration_s" if self.event_kind() == "frequency" else "fault_cycles"
        self.state[f"{self.key}_{key}"] = value
        self._update_readouts()
        self.schedule_refresh()

    def _on_depth_slider(self, value: int) -> None:
        key = "freq_offset_tenths" if self.event_kind() == "frequency" else "fault_depth_pct"
        self.state[f"{self.key}_{key}"] = value
        self._update_readouts()
        self.schedule_refresh()

    def fault_duration_s(self) -> float:
        if self.event_kind() == "frequency":
            return float(self.state.get(f"{self.key}_freq_duration_s", FREQUENCY_EVENT_DURATION))
        return self.state.get(f"{self.key}_fault_cycles", round(FAULT_DURATION * 60.0)) / 60.0

    def fault_voltage_pu(self) -> float:
        return 1.0 - self.state.get(f"{self.key}_fault_depth_pct", round((1.0 - V_FAULT) * 100.0)) / 100.0

    def fault_frequency_hz(self) -> float:
        default = round((FREQUENCY_EVENT_HZ - NOMINAL_FREQUENCY_HZ) * 10)
        return NOMINAL_FREQUENCY_HZ + self.state.get(f"{self.key}_freq_offset_tenths", default) / 10.0

    def current_event(self) -> Event:
        return Event(self.event_kind(), self.fault_duration_s(), self.fault_voltage_pu(), self.fault_frequency_hz())

    # --- values -----------------------------------------------------------------------------------------

    def collect_params(self) -> dict:
        """Every CON: the imported record's or the preset's full bundle, with the editor's fields on top. Starting
        from the bundle matters for the CONs that have no field (frequency stages 2-4, ...)."""
        spec = self.spec
        imported = self.imported
        if imported is not None:
            params = dict(imported.cons)
        elif self.active_preset is not None:
            params = spec.preset_params(self.active_preset, self.key)
        else:
            params = spec.default_params()
        for name, widget in self.fields.items():
            if spec.field_kinds[name] in INTEGER_FIELD_RANGES:
                params[name] = int(widget.value())
                continue
            value = float(widget.value())
            # A spin box rounds to its decimals; an untouched imported value keeps the file's exact digits.
            file_value = imported.cons.get(name) if imported is not None else None
            if file_value is not None and abs(value - file_value) <= 0.5 * 10 ** -widget.decimals() + 1e-12:
                value = float(file_value)
            params[name] = value
        return params

    def _field_values(self) -> dict:
        return {name: (int(w.value()) if self.spec.field_kinds[name] in INTEGER_FIELD_RANGES else float(w.value()))
                for name, w in self.fields.items()}

    def _set_field_values(self, values: dict, *, widen: bool = False) -> None:
        self._loading = True
        for name, widget in self.fields.items():
            if name not in values:
                continue
            value = values[name]
            if widen and isinstance(widget, QDoubleSpinBox):
                widget.setRange(min(widget.minimum(), value), max(widget.maximum(), value))
            widget.blockSignals(True)
            widget.setValue(value if isinstance(widget, QDoubleSpinBox) else round(float(value)))
            widget.blockSignals(False)
        self._loading = False

    def _tolerances(self) -> dict:
        return {name: 0.5 * 10 ** -w.decimals() + 1e-12 for name, w in self.fields.items()
                if isinstance(w, QDoubleSpinBox)}

    def _rebase(self, baseline: Baseline) -> None:
        self.tracker = EditTracker(baseline, self._field_values(), self._tolerances())
        self._refresh_edit_marks()

    # --- presets, imports, resets -------------------------------------------------------------------------

    def _confirm_discard(self, action: str) -> bool:
        if not self.tracker.needs_confirmation():
            return True
        n = self.tracker.edited_count()
        return self.window._confirm(
            "Discard edits?",
            f"{action} replaces {n} edited parameter{'s' if n != 1 else ''} in the {self.title}. Continue?")

    def _on_preset_combo(self, index: int) -> None:
        preset_id = self.preset_index_to_id[index] if 0 <= index < len(self.preset_index_to_id) else None
        if preset_id is None or (self.active_preset is not None and preset_id == self.active_preset.id
                                 and self.imported is None):
            return
        if not self._confirm_discard("Choosing another preset"):
            self._select_preset_in_combo(self.active_preset.id if self.active_preset else None)
            return
        self.apply_preset(preset_id)

    def _select_preset_in_combo(self, preset_id: str | None) -> None:
        self.preset_combo.blockSignals(True)
        if preset_id in self.preset_index_to_id:
            self.preset_combo.setCurrentIndex(self.preset_index_to_id.index(preset_id))
        self.preset_combo.blockSignals(False)

    def apply_preset(self, preset_id: str) -> None:
        """Fill the block from a preset: a fresh baseline, no import, every row closed."""
        preset = RIDE_THROUGH_PRESETS[preset_id]
        self.active_preset = preset
        self.imported = None
        self.import_source = ""
        self.state[f"{self.key}_preset_id"] = preset_id
        self._select_preset_in_combo(preset_id)
        bundle = self.spec.preset_params(preset, self.key)
        self._set_field_values(bundle)
        for row in self.row_widgets.values():
            row.set_expanded(False)
        self._rebase(Baseline.from_preset(preset, self._field_values()))
        self._update_model_bar()
        self.refresh_notes()
        self.schedule_refresh()

    def _use_preset_instead(self) -> None:
        if not self._confirm_discard("Using a preset"):
            return
        self.apply_preset(self.state.get(f"{self.key}_preset_id", DEFAULT_PRESET_ID))

    def apply_imported(self, imported: ImportedRecord, source: str = "") -> None:
        """Show an imported record: switch to the file's model, fill every field from it (widening a field's range
        rather than clamping a value outside it), and preview it with no preset envelope."""
        if imported.model_id != self.model_id:
            self._set_model(imported.model_id, apply_preset=False)
        self.active_preset = None
        self.imported = imported
        self.import_source = source
        self._set_field_values({name: imported.cons[name] for name in self.fields}, widen=True)
        for row in self.row_widgets.values():
            row.set_expanded(False)
        self._rebase(Baseline.from_import(self._field_values(), source, imported.ref.label))
        self._update_model_bar()
        self.refresh_notes()
        self.schedule_refresh()

    def import_dyr(self) -> None:
        if not self._confirm_discard("Importing a file"):
            return
        path = self.window._choose_dyr_file()
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            refs = list_records(text)
            if not refs:
                raise ValueError("No PERC1 (DLL or standard), PERC2 (DLL v2.3 or standard) or CLOD record found in "
                                 "this .dyr file.")
            if not any(r.inspectable for r in refs):
                raise ValueError("This file has no record that can be inspected here:\n"
                                 + "\n".join(r.label for r in refs))
            choice = self.window._choose_dyr_record(refs)
            if choice is None:
                return
            imported = import_record(text, choice)
        except (OSError, ValueError) as exc:
            self.window._show_import_error(str(exc))
            return
        self.apply_imported(imported, source=os.path.basename(path))

    def reset(self) -> None:
        """Back to the baseline: the preset's values, or the imported file's (the block stays imported)."""
        self._set_field_values(self.tracker.reset())
        self._refresh_edit_marks()
        self.refresh_notes()
        self.schedule_refresh()

    def revert_row(self, row_id: str) -> None:
        row = next(r for r in self.rows if r.id == row_id)
        self._set_field_values({c: self.tracker.baseline.values[c] for c in row.cons if c in self.tracker.baseline.values})
        for con in row.cons:
            if con in self.fields:
                self.tracker.set_value(con, self._field_values()[con])
        self._refresh_edit_marks()
        self.refresh_notes()
        self.schedule_refresh()

    def _on_field_changed(self, name: str) -> None:
        if self._loading:
            return
        widget = self.fields[name]
        integer = self.spec.field_kinds[name] in INTEGER_FIELD_RANGES
        self.tracker.set_value(name, int(widget.value()) if integer else float(widget.value()))
        self._refresh_edit_marks()
        self.refresh_notes()
        self.schedule_refresh()

    def _refresh_edit_marks(self) -> None:
        edited = self.tracker.edited_cons()
        values = self.collect_params() if self.fields else {}
        for row in self.rows:
            widget = self.row_widgets[row.id]
            widget.set_edited(bool(edited & set(row.cons)))
            widget.set_summary(row.summary(self.spec.model_id, values))
        for name, caption in self.field_labels.items():
            caption.setProperty("edited", name in edited)
            repolish(caption)
        n = len(edited)
        self.edited_pill.setText(self.tracker.edited_pill())
        self.edited_pill.setVisible(n > 0)
        self.reset_button.setText(self.tracker.reset_label())
        self.reset_button.setEnabled(n > 0)
        self.baseline_note.setText(self.tracker.baseline_note())
        self.edits_changed.emit()

    def refresh_notes(self) -> None:
        """What PSS/E would change or reject in the current values, and what the preset specifies that the model
        cannot hold (the standard variant)."""
        if self.is_user_defined:
            self.notes_label.setVisible(False)
            return
        notes = self.spec.notes(self.collect_params(), self.active_preset)
        if self.imported is not None:
            notes = [("warning", text) for text in self.imported.warnings] + notes
        colors = {"error": t.TRIP, "warning": t.WARNING_TEXT, "info": t.TEXT_MUTED}
        self.notes_label.setText("".join(f'<div style="color:{colors[level]};">&bull; {html_escape(text)}</div>'
                                         for level, text in notes))
        self.notes_label.setVisible(bool(notes))

    # --- model changes -----------------------------------------------------------------------------------

    def _on_model_combo(self, _index: int) -> None:
        model_id = self.model_combo.currentData()
        if model_id == self.model_id:
            return
        if not self._confirm_discard("Changing the model"):
            self.model_combo.blockSignals(True)
            self.model_combo.setCurrentIndex(self.model_combo.findData(self.model_id))
            self.model_combo.blockSignals(False)
            return
        self.set_model(model_id)

    def set_model(self, model_id: str) -> None:
        self._set_model(model_id, apply_preset=True)

    def _set_model(self, model_id: str, *, apply_preset: bool) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.setCurrentIndex(self.model_combo.findData(model_id))
        self.model_combo.blockSignals(False)
        previous_spec = self.spec
        self.state[f"{self.key}_model_id"] = model_id
        self.preview.reset()
        self.parameters_stack.setCurrentIndex(1 if self.is_user_defined else 0)
        self.preview_stack.setCurrentIndex(1 if self.is_user_defined else 0)
        if self.spec is not previous_spec or not self.fields:
            self._rebuild_fields()
        self._update_model_bar()
        if self.is_user_defined:
            self.imported = None
            self._update_user_text()
            self.model_changed.emit(model_id)
            self.preview_updated.emit(None)
            return
        if apply_preset:
            self.apply_preset(self.state.get(f"{self.key}_preset_id", DEFAULT_PRESET_ID))
            if self.mode is not None:
                self.on_mode_changed()
        self.model_changed.emit(model_id)

    # --- operating mode ----------------------------------------------------------------------------------

    mode: QComboBox | None = None

    def build_mode_combo(self, current: str) -> QComboBox:
        from ui.widgets import _combo

        self.mode = _combo(self.mode_options, current if current in self.mode_options else self.mode_options[0])
        self.mode.currentTextChanged.connect(lambda _=None: self.on_mode_changed())
        return self.mode

    def on_mode_changed(self) -> None:
        if self.mode is None or self.is_user_defined:
            return
        for name, value in self.spec.mode_updates(self.mode.currentText()).items():
            if name in self.fields:
                self.fields[name].setValue(value)

    # --- user-defined model -------------------------------------------------------------------------------

    def browse_user_dyr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Your model's .dyr file", "",
                                              "DYR Files (*.dyr);;All files (*)")
        if path:
            self.load_user_dyr(path)

    def load_user_dyr(self, path: str, *, target_index: int | None = None) -> bool:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            choices = read_external_model(text, os.path.basename(path), None)
        except (OSError, ValueError) as exc:
            self.window._show_import_error(str(exc))
            return False
        if target_index is None:
            target_index = 0
            if len(choices) > 1:
                item, ok = QInputDialog.getItem(self.window, "Choose a load", "This file has several loads. "
                                                "Which one is this block?", choices, 0, False)
                if not ok:
                    return False
                target_index = choices.index(item)
        dlls = self.user_model.dlls if self.user_model else ()
        self.user_model = read_external_model(text, os.path.basename(path), target_index, dlls=dlls,
                                              source_path=path)
        self._update_model_bar()
        self._update_user_text()
        self.preview_updated.emit(None)
        return True

    def add_user_dll(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Model DLLs", "", "DLL (*.dll);;All files (*)")
        self.add_user_dlls([os.path.normpath(p) for p in paths])

    def add_user_dlls(self, paths: list[str]) -> None:
        if not paths:
            return
        if self.user_model is None:
            self.window._show_import_error("Choose your model's .dyr file first.")
            return
        self.user_model = self.user_model.with_dlls((*self.user_model.dlls, *paths))
        self._update_model_bar()
        self._update_user_text()

    def _update_user_text(self) -> None:
        if self.user_model is None:
            self.user_record_text.setText("No .dyr file chosen yet.")
            return
        dlls = ", ".join(os.path.basename(d) for d in self.user_model.dlls) or "none"
        self.user_record_text.setText(f"{html_escape(self.user_model.label)}<br>DLLs: {html_escape(dlls)}")

    def open_in_blackbox(self) -> None:
        prefill = {}
        if self.user_model is not None and self.user_model.source_path:
            prefill = {"dyr": self.user_model.source_path, "dlls": list(self.user_model.dlls)}
        self.window.navigate("blackbox", **prefill)

    # --- preview -----------------------------------------------------------------------------------------

    def schedule_refresh(self) -> None:
        self._timer.start(150)

    def refresh_preview(self) -> PreviewResult | None:
        self._timer.stop()
        if self.is_user_defined:
            self.last_result = None
            self.preview_updated.emit(None)
            return None
        result = build_preview(self.model_id, self.collect_params(), self.current_event(), preset=self.active_preset,
                               block_mw=self.block_mw(),
                               block_label=self.title if self.key != "screening" else None)
        self.last_result = result
        self.verdict.set_result(result)
        self.preview.show_result(result, self.active_preset)
        self.preview_updated.emit(result)
        return result

    def export_state(self) -> dict:
        """The `{block}_*` keys the report and the .dyr export read."""
        state = {f"{self.key}_model_id": self.model_id}
        if self.is_user_defined:
            if self.user_model is not None:
                state.update(self.user_model.state_keys(self.key))
            return state
        for name, value in self.collect_params().items():
            state[f"{self.key}_adv_{name}"] = value
        return state


__all__ = ["BlockController", "QListWidget", "QMessageBox", "preset_badge"]
