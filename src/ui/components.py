"""The redesign's building blocks: cards, labels, badges, the segmented control, the
verdict strip, parameter rows, the stepper, the load split bar and file-location rows.

Widgets only; their look comes from the object names and properties `ui.theme`
styles. Nothing here knows about a particular screen.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import tokens as t
from ui.theme import repolish

# --- small pieces ------------------------------------------------------------------------------------------


def card(parent: QWidget | None = None, *, margins=(t.GUTTER, 14, t.GUTTER, 14), spacing: int = t.FIELD_GAP
         ) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("card")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return frame, layout


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionLabel")
    return label


def label(text: str = "", name: str | None = None, *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def badge(text: str, kind: str) -> QLabel:
    widget = QLabel(text)
    widget.setProperty("badge", kind)
    widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return widget


def set_badge(widget: QLabel, text: str, kind: str) -> None:
    widget.setText(text)
    widget.setProperty("badge", kind)
    repolish(widget)


def button(text: str, handler=None, *, kind: str = "primary", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if kind != "primary":
        widget.setObjectName({"secondary": "secondaryButton", "link": "linkButton", "small": "smallButton"}[kind])
    if tooltip:
        widget.setToolTip(tooltip)
    if handler is not None:
        widget.clicked.connect(handler)
    return widget


def field(caption: str, widget: QWidget, *, hint: str | None = None) -> QWidget:
    """A caption above a control (the design's field layout), with an optional hint below."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    cap = QLabel(caption)
    cap.setObjectName("fieldLabel")
    cap.setBuddy(widget)
    layout.addWidget(cap)
    layout.addWidget(widget)
    if hint:
        h = QLabel(hint)
        h.setObjectName("fieldHint")
        h.setWordWrap(True)
        layout.addWidget(h)
    box.caption = cap
    return box


def hline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {t.HAIRLINE};")
    return line


def set_error(widget: QWidget, error: bool) -> None:
    widget.setProperty("error", error)
    repolish(widget)


# --- segmented control -------------------------------------------------------------------------------------


class SegmentedControl(QWidget):
    """Two or more mutually exclusive buttons in a tinted track. `group` is the QButtonGroup."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._keys: list[str] = []
        for key, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("segment", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(key == current)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            layout.addWidget(b)
            self._keys.append(key)

    def set_current(self, key: str) -> None:
        for k, b in zip(self._keys, self.group.buttons()):
            b.setChecked(k == key)


# --- verdict strip -----------------------------------------------------------------------------------------


class VerdictStrip(QFrame):
    """TRIPS / RIDES THROUGH, the event and what happens, and three figures."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("verdictNeutral")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(t.GUTTER, 10, t.GUTTER, 10)
        row.setSpacing(t.GUTTER)
        self.badge = badge("…", "neutral")
        row.addWidget(self.badge, alignment=Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label("", "cardTitle")
        self.title.setStyleSheet("font-size: 14px;")
        self.detail = label("", "muted", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        row.addLayout(text, stretch=1)
        self.figures: dict[str, QLabel] = {}
        for key, caption in (("load_tripped", "Load tripped"), ("reconnects", "Reconnects"), ("ramp", "Ramp")):
            col = QVBoxLayout()
            col.setSpacing(0)
            cap = label(caption, "muted")
            value = label("–", "bigFigure")
            col.addWidget(cap)
            col.addWidget(value)
            row.addLayout(col)
            self.figures[key] = value

    def set_result(self, result) -> None:
        trips = result.trips
        self.setObjectName("verdictTrips" if trips else "verdictRides")
        repolish(self)
        set_badge(self.badge, result.verdict, "trips" if trips else "rides")
        self.title.setText(result.title)
        self.detail.setText(result.detail)
        for key in self.figures:
            self.figures[key].setText(getattr(result, key))
        self.figures["load_tripped"].setStyleSheet(f"color: {t.TRIP};" if trips else "")
        self.figures["reconnects"].setStyleSheet(f"color: {t.BRAND};" if trips and result.reconnects != "none" else "")

    def figure_texts(self) -> dict[str, str]:
        return {k: v.text() for k, v in self.figures.items()}


# --- parameter rows ----------------------------------------------------------------------------------------


class ParameterRowWidget(QWidget):
    """One parameter row: title and chevron (the current values are the tooltip, so the header never crowds);
    clicking opens its editor underneath, which holds the row's CON fields grouped as the model describes them."""

    toggled = Signal(bool)

    def __init__(self, row, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.header = QPushButton()
        self.header.setObjectName("paramRow")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setAccessibleName(row.title)
        inner = QHBoxLayout(self.header)
        inner.setContentsMargins(8, 0, 8, 0)
        self.title_label = QLabel(row.title)
        self.chevron = QLabel("›")
        self.chevron.setObjectName("muted")
        for w in (self.title_label, self.chevron):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        inner.addWidget(self.title_label, stretch=1)
        inner.addWidget(self.chevron)
        layout.addWidget(self.header)

        self.editor = QFrame()
        self.editor.setObjectName("rowEditor")
        self.editor.setAttribute(Qt.WA_StyledBackground, True)
        self.editor_layout = QVBoxLayout(self.editor)
        self.editor_layout.setContentsMargins(12, 10, 12, 10)
        self.editor_layout.setSpacing(8)
        self.editor.setVisible(False)
        layout.addWidget(self.editor)
        self.header.toggled.connect(self._on_toggled)
        self.revert_button: QPushButton | None = None

    def _on_toggled(self, checked: bool) -> None:
        self.editor.setVisible(checked)
        self.chevron.setText("⌄" if checked else "›")
        self.toggled.emit(checked)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_summary(self, text: str) -> None:
        self.header.setToolTip(text)

    def set_edited(self, edited: bool) -> None:
        for w in (self.header, self.title_label):
            w.setProperty("edited", edited)
            repolish(w)
        if self.revert_button is not None:
            self.revert_button.setEnabled(edited)

    def is_edited(self) -> bool:
        return bool(self.header.property("edited"))

    def add_section(self, title: str | None, form: QFormLayout) -> None:
        if title:
            heading = QLabel(title)
            heading.setObjectName("cardTitle")
            heading.setStyleSheet(f"color: {t.TEXT_MUTED}; font-size: 12px;")
            self.editor_layout.addWidget(heading)
        holder = QWidget()
        holder.setLayout(form)
        self.editor_layout.addWidget(holder)


# --- stepper and split bar ---------------------------------------------------------------------------------


class LoadSplitBar(QWidget):
    """A thin bar split by share: IT, VFD, CLOD motors, other."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shares: list[float] = []
        self._colors = list(t.SPLIT_COLORS)
        self.setFixedHeight(10)
        self.setMinimumWidth(180)

    def set_shares(self, shares: list[float]) -> None:
        self._shares = [max(0.0, s) for s in shares]
        self.setToolTip(" · ".join(f"{name} {s:.0f} %" for name, s in
                                   zip(("IT / UPS", "VFD", "Motors", "Other"), self._shares)))
        self.update()

    def shares(self) -> list[float]:
        return list(self._shares)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.HAIRLINE))
        painter.drawRoundedRect(rect, 3, 3)
        total = sum(self._shares) or 1.0
        x = float(rect.x())
        for share, color in zip(self._shares, self._colors):
            w = rect.width() * share / max(total, 100.0)
            painter.setBrush(QColor(color))
            painter.drawRect(int(x), rect.y(), round(w), rect.height())
            x += w


class Stepper(QWidget):
    """Numbered workflow steps with an optional MW figure each; the current step is tinted."""

    step_clicked = Signal(int)

    def __init__(self, titles: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.buttons: list[QPushButton] = []
        self._titles = titles
        self._mw: list[str] = [""] * len(titles)
        self._done: set[int] = set()
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, _title in enumerate(titles):
            if i:
                sep = QLabel("›")
                sep.setObjectName("muted")
                row.addWidget(sep)
            b = QPushButton()
            b.setObjectName("step")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.step_clicked.emit(idx))
            group.addButton(b)
            row.addWidget(b)
            self.buttons.append(b)
        self._render()

    def set_mw(self, index: int, text: str) -> None:
        self._mw[index] = text
        self._render()

    def set_done(self, done: set[int]) -> None:
        self._done = set(done)
        self._render()

    def set_current(self, index: int) -> None:
        for i, b in enumerate(self.buttons):
            b.setChecked(i == index)

    def _render(self) -> None:
        for i, (b, title) in enumerate(zip(self.buttons, self._titles)):
            mark = "✓" if i in self._done else f"{i + 1}"
            text = f"{self._circle(mark)}  {title}" + (f"   {self._mw[i]}" if self._mw[i] else "")
            b.setText(text.replace("&", "&&"))
            b.setAccessibleName(title)
            bold = QFont(b.font())
            bold.setWeight(QFont.DemiBold)
            b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 28)  # the current step is semibold

    @staticmethod
    def _circle(mark: str) -> str:
        circled = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤", "6": "⑥", "✓": "✓"}
        return circled.get(mark, mark)


# --- file locations ----------------------------------------------------------------------------------------


def reveal_in_folder(path: str | Path) -> None:
    """Show a file selected in Explorer on Windows; elsewhere open the folder that holds it."""
    path = Path(path)
    if sys.platform.startswith("win") and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)])
        return
    folder = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_folder(path: str | Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


class FileLocationRow(QFrame):
    """A path shown in full (selectable, monospace) with Copy path and Open folder / Show in folder."""

    def __init__(self, caption: str = "", path: str | Path = "", *, reveal: bool = False, color: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("subtleBox")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        if color:
            key = QLabel("━")
            key.setStyleSheet(f"color: {color}; font-weight: 700;")
            row.addWidget(key)
        if caption:
            row.addWidget(label(caption, "muted"))
        self.path_edit = QLineEdit(str(path))
        self.path_edit.setReadOnly(True)
        self.path_edit.setProperty("mono", True)
        self.path_edit.setFrame(False)
        self.path_edit.setStyleSheet("background: transparent; border: none;")
        self.path_edit.setCursorPosition(0)
        row.addWidget(self.path_edit, stretch=1)
        self.copy_button = button("Copy path", lambda: copy_text(self.path()), kind="small")
        self.open_button = button("Show in folder" if reveal else "Open folder",
                                  lambda: (reveal_in_folder if reveal else open_folder)(self.path()), kind="small")
        row.addWidget(self.copy_button)
        row.addWidget(self.open_button)

    def path(self) -> str:
        return self.path_edit.text()

    def set_path(self, path: str | Path) -> None:
        self.path_edit.setText(str(path))
        self.path_edit.setCursorPosition(0)
        exists = bool(str(path)) and os.path.exists(str(path))
        self.open_button.setEnabled(exists)


def grid(columns: int = 2, spacing: int = t.FIELD_GAP) -> QGridLayout:
    layout = QGridLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(spacing)
    layout.setVerticalSpacing(spacing)
    for c in range(columns):
        layout.setColumnStretch(c, 1)
    return layout


__all__ = [
    "FileLocationRow", "LoadSplitBar", "ParameterRowWidget", "SegmentedControl", "Stepper", "VerdictStrip",
    "badge", "button", "card", "copy_text", "field", "grid", "hline", "label", "open_folder", "reveal_in_folder",
    "section_label", "set_badge", "set_error",
]
