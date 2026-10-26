"""Small shared widgets and layout helpers used by every screen: scroll areas, forms,
combo boxes, the record-settings group, the collapsible section and the CON field
widget factory. Moved out of ui/main_window.py unchanged."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor.model_ui import DLL_MODEL_ID, INTEGER_FIELD_RANGES, UI_SPECS, ModelUiSpec
from load_models.base import RECORD_SCOPES


def _make_scroll_area(inner: QWidget) -> QScrollArea:
    """Wrap a step page/stack so it scrolls instead of compressing its rows
    into overlap when the window is shorter than the content needs."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(inner)
    return scroll


def _combo(items: list[str], current: str | None = None) -> QComboBox:
    """QComboBox with a bounded closed-box width.

    Several option lists carry long descriptive text (e.g. "Extended (rated
    for deep/long sags, e.g. ITI/CBEMA-plus)"). QComboBox's default size
    policy sizes the closed box to fit its widest item, which forced whole
    step pages - and, once wrapped in a scroll area, the window itself - far
    wider than needed. The policy must be set before the combo box is added
    to a layout: applying it afterwards leaves the parent layout's cached
    size hint stale. The full option text still shows in the open dropdown.
    """
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(24)
    combo.addItems(items)
    if current is not None:
        combo.setCurrentText(current)
    return combo


def _form(parent: QWidget | None = None) -> QFormLayout:
    """A form with labels vertically centred on their fields and consistent
    spacing - Qt's default top-aligns labels, which looks misaligned beside
    the taller input boxes."""
    form = QFormLayout(parent) if parent is not None else QFormLayout()
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(8)
    return form


class RecordSettingsGroup(QGroupBox):
    """How the exported .dyr records attach to the power-flow case: the record
    format (Bus/Owner/Zone/Area/All - the vendor's PERC**/IT codes), the
    owner/zone/area number those formats need, and each block's load ID."""

    changed = Signal()

    def __init__(self, load_ids: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        """`load_ids` is [(state key, row label, default ID)]."""
        super().__init__("PSS/E records", parent)
        form = _form(self)
        self.scope_combo = QComboBox()
        for scope in RECORD_SCOPES.values():
            self.scope_combo.addItem(f"{scope.label} ({scope.model_name('PERC')}, IT = {scope.it})", scope.id)
        self.number_label = QLabel("")
        self.number_spin = QSpinBox()
        self.number_spin.setRange(1, 999999)
        self.number_spin.setValue(1)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("fieldHint")
        form.addRow("Record format", self.scope_combo)
        form.addRow(self.number_label, self.number_spin)
        form.addRow("", self.hint)
        self.load_id_edits: dict[str, QLineEdit] = {}
        self._load_id_defaults = {key: default for key, _label, default in load_ids}
        for key, label, default in load_ids:
            edit = QLineEdit(default)
            edit.setMaxLength(2)  # PSS/E's load identifier is character*2
            edit.setToolTip("PSS/E load ID (1-2 characters) of the static load this record attaches to")
            form.addRow(label, edit)
            edit.textChanged.connect(self.changed)
            self.load_id_edits[key] = edit
        self.scope_combo.currentIndexChanged.connect(self._sync)
        self.number_spin.valueChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        scope = RECORD_SCOPES[self.scope_combo.currentData()]
        needs_number = scope.id not in ("bus", "all")
        self.number_label.setVisible(needs_number)
        self.number_spin.setVisible(needs_number)
        if needs_number:
            self.number_label.setText(scope.number_label)
        self.hint.setVisible(scope.id != "bus")
        self.hint.setText(
            "Applies to every load with these IDs across the whole case."
            if scope.id == "all" else
            f"Applies to every load with these IDs in {scope.label.lower()} {self.number_spin.value()}."
        )
        self.changed.emit()

    def state(self) -> dict:
        """The export-state keys build_dyr_text()/build_html_report() read."""
        state = {"record_scope": self.scope_combo.currentData(), "subsystem_number": int(self.number_spin.value())}
        for key, edit in self.load_id_edits.items():
            state[key] = edit.text().strip() or self._load_id_defaults[key]
        return state


def _style_review_table(table: QTableWidget, first_column_width: int) -> None:
    """Compact, read-only two-column review table."""
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels(["Parameter", "Value"])
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.setColumnWidth(0, first_column_width)
    table.verticalHeader().setVisible(False)  # row numbers add nothing here
    table.verticalHeader().setDefaultSectionSize(28)
    table.setWordWrap(True)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setMinimumHeight(240)


class _ClickableLabel(QLabel):
    """A QLabel that also emits a click, so CollapsibleSection's title can wrap onto
    multiple lines (QToolButton's own text elides/truncates instead of wrapping when
    the header is narrower than the title - the "ZIP exponent & current limits"
    header cut off as "ZIP exponent ...urrent limits" was exactly this)."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class CollapsibleSection(QWidget):
    """A minimal Qt "spoiler" widget: a checkable header that shows/hides a content
    pane. PySide6 has no built-in accordion/expander widget - this is the standard
    recipe for one. Used two levels deep: an outer
    "Advanced adjustments" section per block, gating whether per-CON overrides apply
    at all, containing several independently-collapsible named sub-groups that are
    purely visual organization (multiple may be open at once).

    The header is a small icon-only arrow button plus a word-wrapping label (not a
    single QToolButton with a text property) specifically so the title is never
    truncated regardless of how narrow the column is - it wraps to a second line
    instead.

    `toggled` is the underlying arrow button's `toggled` signal, exposed here so
    callers can bind the outer section's expand state to `it_advanced`/`vfd_advanced`.
    """

    def __init__(self, title: str, expanded: bool = False, parent: QWidget | None = None,
                 nested: bool = False) -> None:
        super().__init__(parent)
        self.toggle_button = QToolButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.setObjectName("collapsibleArrow")
        self.toggle_button.setFixedSize(22, 22)

        self.title_label = _ClickableLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setCursor(Qt.PointingHandCursor)
        self.title_label.setObjectName("collapsibleSubHeaderLabel" if nested else "collapsibleHeaderLabel")
        self.title_label.clicked.connect(lambda: self.toggle_button.setChecked(not self.toggle_button.isChecked()))

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(6)
        header_layout.addWidget(self.toggle_button, alignment=Qt.AlignTop)
        header_layout.addWidget(self.title_label, stretch=1)
        # A nested section (e.g. "Undervoltage reconnect" inside "Voltage
        # ride-through") gets a lighter, borderless header so the hierarchy
        # reads at a glance instead of every level looking the same.
        header.setObjectName("collapsibleSubHeader" if nested else "collapsibleHeader")

        self.content_area = QWidget()
        self.content_area.setVisible(expanded)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(16, 4, 4, 8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(header)
        layout.addWidget(self.content_area)

        self.toggle_button.toggled.connect(self._on_toggled)
        self.toggled = self.toggle_button.toggled

    def _on_toggled(self, checked: bool) -> None:
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.content_area.setVisible(checked)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def set_content_layout(self, layout) -> None:
        wrapper = QWidget()
        wrapper.setLayout(layout)
        self.content_layout.addWidget(wrapper)


def _field_label_in_section(label: str, section_title: str | None) -> str:
    """A field's label inside a titled subsection, without the direction the
    title already states: "Undervoltage stage 2 trip (pu)" under "Undervoltage
    trip stages" reads "Stage 2 trip (pu)". Review tables and reports keep the
    full label, since they have no such heading."""
    if section_title:
        lead = section_title.split()[0] + " "
        if label.startswith(lead):
            rest = label[len(lead):]
            return rest[:1].upper() + rest[1:]
    return label


def _field_widget(spec: ModelUiSpec, field_name: str, value=0.0):
    """The spin box for one CON of the model `spec` describes (a ZIP selector or 0/1 flag, or a bounded decimal)."""
    kind = spec.field_kinds[field_name]
    if kind in INTEGER_FIELD_RANGES:
        widget = QSpinBox()
        widget.setRange(*INTEGER_FIELD_RANGES[kind])
        widget.setValue(int(value))
    else:
        widget = QDoubleSpinBox()
        lo, hi = spec.field_ranges.get(field_name, (-1000.0, 1000.0))
        widget.setRange(lo, hi)
        widget.setDecimals(spec.field_decimals.get(field_name, 4))
        widget.setValue(float(value))
    return widget


def _perc1_advanced_widget(kind: str, value, field_name: str | None = None):
    """The DLL variant's field widget (kept for callers that build one directly)."""
    spec = UI_SPECS[DLL_MODEL_ID]
    return _field_widget(spec, field_name, value)
