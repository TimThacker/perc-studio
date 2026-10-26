"""After a black-box run: the summary page shown on the Black-Box Validation tab, and the
tab each run gets of its own (test explorer, report, PSS/E log).

Widgets only. Everything shown is read from the run folder: `validation.json` through
`blackbox.runs` and `blackbox.tolerance`, the cases through `blackbox.explorer`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import tokens as t
from blackbox.runs import RunSummary, case_files, measured_rows, read_run
from blackbox.tolerance import (
    caption,
    frequency_note,
    measured_boundary,
    overlay_presets,
    shortfalls,
    tolerance_figure,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS
from ui.blackbox.explorer import ResultsExplorer
from ui.components import (
    FileLocationRow,
    badge,
    button,
    card,
    label,
    open_folder,
    section_label,
)
from ui.preview_view import _PLOTLY_JS
from ui.widgets import _make_scroll_area

VERDICT_BADGE = {"fails": "fails", "meets": "meets", "at the edge": "warning", "beyond tested range": "neutral",
                 "not solvable": "neutral", "no requirement": "neutral"}
# "Why": the guide's section on how a verdict is reached.
WHY_DOC = ("black_box/BLACK_BOX_VALIDATION.md", "58-comparing-with-a-preset")


def verdict_badge(verdict: str | None) -> QLabel:
    return badge(verdict or "-", VERDICT_BADGE.get(verdict or "", "neutral"))


def plot_page(fig, div_id: str = "plot") -> str:
    """A small page drawing one Plotly figure with the local plotly.js, filling the view."""
    config = {"responsive": True, "displaylogo": False, "displayModeBar": False}
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html, body {{ margin: 0; height: 100%; background: {t.SURFACE}; overflow: hidden; }}
#{div_id} {{ width: 100%; height: 100%; }}</style>
<script src="{_PLOTLY_JS.name}"></script></head><body><div id="{div_id}"></div>
<script>var f = {fig.to_json()}; Plotly.newPlot("{div_id}", f.data, f.layout, {json.dumps(config)});</script>
</body></html>"""


def show_figure(view: QWebEngineView, fig) -> None:
    view.setHtml(plot_page(fig), QUrl.fromLocalFile(str(_PLOTLY_JS.parent) + "/"))


def _web_view(min_height: int) -> QWebEngineView:
    view = QWebEngineView()
    view.setMinimumHeight(min_height)
    view.page().setBackgroundColor(QColor(t.SURFACE))
    return view


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionMode(QTableWidget.NoSelection)
    table.setShowGrid(False)
    table.setFrameShape(QFrame.NoFrame)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.verticalHeader().setDefaultSectionSize(30)
    return table


def _fit_rows(table: QTableWidget) -> None:
    height = table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(table.rowCount())) + 4
    table.setFixedHeight(height)


# --- the tolerance curve ------------------------------------------------------------------------------------------


class ToleranceCard(QFrame):
    """The run's tolerance curve with an optional standard laid over it. It always starts with no standard chosen,
    and the choice is never saved."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.GUTTER, 14, t.GUTTER, 14)
        layout.setSpacing(t.FIELD_GAP)
        self._doc: dict | None = None
        self._summary: RunSummary | None = None

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(section_label("Tolerance curve"))
        titles.addWidget(label("How long the model rides through each voltage and frequency, from the measured "
                               "boundaries.", "muted"))
        head.addLayout(titles, stretch=1)
        head.addWidget(label("Overlay standard", "fieldLabel"))
        self.overlay_combo = QComboBox()
        self.overlay_combo.addItem("Choose a standard…", None)
        for preset in overlay_presets(RIDE_THROUGH_PRESETS.values()):
            self.overlay_combo.addItem(preset.label, preset.id)
        self.overlay_combo.setMinimumWidth(220)
        self.overlay_combo.currentIndexChanged.connect(self._redraw)
        head.addWidget(self.overlay_combo)
        layout.addLayout(head)

        self.legend = label("", "muted")
        self.legend.setTextFormat(Qt.RichText)
        layout.addWidget(self.legend)
        charts = QHBoxLayout()
        charts.setSpacing(t.GUTTER)
        self.views: dict[str, QWebEngineView] = {}
        self.notes: dict[str, QLabel] = {}
        for quantity in ("voltage", "frequency"):
            col = QVBoxLayout()
            col.addWidget(label(quantity.capitalize(), "cardTitle"))
            view = _web_view(300)
            col.addWidget(view)
            note = label("", "muted", wrap=True)
            note.setVisible(False)
            col.addWidget(note)
            charts.addLayout(col, stretch=1)
            self.views[quantity] = view
            self.notes[quantity] = note
        layout.addLayout(charts)
        self.caption = label("", None, wrap=True)
        self.caption.setTextFormat(Qt.RichText)
        layout.addWidget(self.caption)
        self.footnote = label("", "muted", wrap=True)
        layout.addWidget(self.footnote)

    def set_run(self, doc: dict, summary: RunSummary) -> None:
        self._doc, self._summary = doc, summary
        self.overlay_combo.blockSignals(True)
        self.overlay_combo.setCurrentIndex(0)  # no standard until the user picks one
        self.overlay_combo.blockSignals(False)
        self.footnote.setText(f"Drawn from this run ({summary.date_text()}, {summary.cases} cases).")
        self._redraw()

    def overlay_preset(self):
        pid = self.overlay_combo.currentData()
        return RIDE_THROUGH_PRESETS.get(pid) if pid else None

    def shortfall_list(self) -> list:
        preset = self.overlay_preset()
        if self._doc is None or preset is None:
            return []
        return [f for kind in ("undervoltage", "overvoltage", "frequency")
                for f in shortfalls(measured_boundary(self._doc, kind), preset)]

    def _redraw(self, *_args) -> None:
        if self._doc is None:
            return
        preset = self.overlay_preset()
        for quantity, view in self.views.items():
            show_figure(view, tolerance_figure(self._doc, quantity, preset))
        def swatch(color):
            return f"<span style='color:{color};font-size:15px;'>■</span>"

        parts = [f"{swatch(t.MODEL_OUTLINE)} Model rides through (measured)"]
        if preset is not None:
            parts.append(f"<b style='color:{t.TEXT}'>‒ ‒</b> {preset.label} requires ride-through")
            parts.append(f"{swatch(t.SHORTFALL)} Short of the standard")
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join(parts))
        note = frequency_note(preset)
        self.notes["frequency"].setText(note or "")
        self.notes["frequency"].setVisible(bool(note))
        falls = self.shortfall_list()
        text = caption(self._doc, preset, falls)
        if preset is not None and falls:
            text = (f'<span style="background:{t.TRIP_TINT};color:{t.TRIP_TEXT};padding:1px 6px;border-radius:4px;">'
                    f"fails</span> {text}")
        self.caption.setText(text)


# --- the summary page --------------------------------------------------------------------------------------------


class RunSummaryView(QWidget):
    """The Black-Box tab's right-hand page after a run: header, comparison, warnings, tolerance curve, measured
    behaviour and files."""

    open_run_tab = Signal(str)  # run folder
    open_docs = Signal(str, str)  # document under docs/, heading anchor

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary: RunSummary | None = None
        self.doc: dict | None = None
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(t.GUTTER)

        head, hl = card()
        row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.heading = label("", "panelTitle")
        self.subtitle = label("", "muted", wrap=True)
        self.subtitle.setObjectName("mono")
        self.subtitle.setStyleSheet(f"color: {t.TEXT_MUTED};")
        titles.addWidget(self.heading)
        titles.addWidget(self.subtitle)
        row.addLayout(titles, stretch=1)
        self.open_report_button = button("Open report in browser", self._open_report, kind="secondary")
        self.open_tab_button = button("Open run tab ›", lambda: self.summary and self.open_run_tab.emit(
            str(self.summary.folder)))
        row.addWidget(self.open_report_button)
        row.addWidget(self.open_tab_button)
        hl.addLayout(row)
        layout.addWidget(head)

        pair = QHBoxLayout()
        pair.setSpacing(t.GUTTER)
        comp, cl = card()
        cl.addWidget(section_label("Comparison with standards"))
        self.comparison = _table(["Standard", "Overall", "UV", "OV", "Freq."])
        self.comparison.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        cl.addWidget(self.comparison)
        self.comparison_text = label("", "muted", wrap=True)
        cl.addWidget(self.comparison_text)
        self.why_link = button("Why", lambda: self.open_docs.emit(*WHY_DOC), kind="link")
        cl.addWidget(self.why_link, alignment=Qt.AlignLeft)
        cl.addStretch()
        pair.addWidget(comp, stretch=3)
        warn, wl = card()
        wl.addWidget(section_label("Warnings"))
        self.warnings_box = QVBoxLayout()
        self.warnings_box.setSpacing(8)
        wl.addLayout(self.warnings_box)
        wl.addStretch()
        pair.addWidget(warn, stretch=2)
        layout.addLayout(pair)

        self.tolerance = ToleranceCard()
        layout.addWidget(self.tolerance)

        meas, ml = card()
        ml.addWidget(section_label("Measured behaviour"))
        self.measured = _table(["Test", "Result", "Boundary"])
        self.measured.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.measured.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.measured.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        ml.addWidget(self.measured)
        layout.addWidget(meas)

        files, fl = card()
        fl.addWidget(section_label("Files"))
        self.folder_row = FileLocationRow("Run folder")
        fl.addWidget(self.folder_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(t.GUTTER)
        self.file_labels: dict[str, QLabel] = {}
        entries = (("report.html", "written report"), ("validation.json", "every result, machine-readable"),
                   ("bundle.zip", "everything to re-run or share"), (r"work\cache\*\case.outx", ""))
        for col, (name, text) in enumerate(entries):
            box = QVBoxLayout()
            box.setSpacing(0)
            title = label(name, "mono")
            title.setStyleSheet("font-weight: 600;")
            box.addWidget(title)
            line = QHBoxLayout()
            desc = label(text, "muted")
            line.addWidget(desc)
            if name == "bundle.zip":
                self.save_bundle_button = button("Save copy…", self.save_bundle, kind="link")
                line.addWidget(self.save_bundle_button)
            line.addStretch()
            box.addLayout(line)
            grid.addLayout(box, 0, col)
            self.file_labels[name] = desc
        fl.addLayout(grid)
        layout.addWidget(files)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = _make_scroll_area(inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

    def show_run(self, folder: str | Path) -> RunSummary:
        self.doc, self.summary = read_run(folder)
        s = self.summary
        self.heading.setText(s.heading)
        self.subtitle.setText(s.subtitle)
        self.open_report_button.setEnabled((s.folder / "report.html").exists())

        self.comparison.setRowCount(len(s.compared))
        for r, (name, verdict, per) in enumerate(s.compared):
            self.comparison.setItem(r, 0, QTableWidgetItem(name))
            for c, value in enumerate((verdict, per.get("undervoltage"), per.get("overvoltage"),
                                       per.get("frequency")), start=1):
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(4, 0, 4, 0)
                cell_layout.addWidget(verdict_badge(value))
                cell_layout.addStretch()
                self.comparison.setCellWidget(r, c, cell)
        _fit_rows(self.comparison)
        self.comparison_text.setText(self._comparison_text())
        self.why_link.setVisible(bool(s.compared))

        while self.warnings_box.count():
            item = self.warnings_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text in s.warnings or ("No warnings.",):
            row = QHBoxLayout()
            if s.warnings:
                row.addWidget(badge("!", "warning"), alignment=Qt.AlignTop)
            row.addWidget(label(text, None, wrap=True), stretch=1)
            holder = QWidget()
            holder.setLayout(row)
            self.warnings_box.addWidget(holder)

        self.tolerance.set_run(self.doc, s)

        rows = measured_rows(self.doc)
        self.measured.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.measured.setItem(r, c, item)
        _fit_rows(self.measured)

        self.folder_row.set_path(s.folder)
        n = len(case_files(s.folder))
        self.file_labels[r"work\cache\*\case.outx"].setText(f"{n} PSS/E channel files, one per case")
        self.save_bundle_button.setEnabled((s.folder / "bundle.zip").exists())
        return s

    def _comparison_text(self) -> str:
        """Generated where the analysis can say it: the tolerance curve's shortfalls for each failing standard."""
        if not self.summary or not self.summary.compared:
            return "No standards were compared in this run. Use the tolerance curve below to overlay one."
        out = []
        for pid, comp in (self.doc or {}).get("comparison", {}).items():
            if comp.get("overall") != "fails":
                continue
            preset = RIDE_THROUGH_PRESETS.get(pid)
            if preset is None:
                continue
            falls = [f for k in ("undervoltage", "overvoltage", "frequency")
                     for f in shortfalls(measured_boundary(self.doc, k), preset)]
            if falls:
                by_kind = {}
                for f in falls:
                    by_kind.setdefault(f.kind, []).append(f)
                parts = [f"{kind.capitalize()} misses at "
                         + ", ".join(f"{f.lo:g}" for f in items) + (" pu" if kind != "frequency" else " Hz")
                         for kind, items in by_kind.items()]
                out.append(f"{preset.label}: " + "; ".join(parts) + ".")
        if out:
            out.append("Each is a band where the standard requires ride-through and the model was seen to trip; the "
                       "tolerance curve below shows them.")
            return " ".join(out)
        return "Verdicts compare the load with each preset as encoded in this app; they are not a compliance finding."

    def _open_report(self) -> None:
        if self.summary:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.summary.folder / "report.html")))

    def save_bundle(self) -> None:
        if not self.summary:
            return
        src = self.summary.folder / "bundle.zip"
        dest, _ = QFileDialog.getSaveFileName(self, "Save bundle", src.name, "Zip (*.zip)")
        if dest:
            shutil.copyfile(src, dest)


# --- the run tab ------------------------------------------------------------------------------------------------


class RunTab(QWidget):
    """One run in a tab of its own: a header, and Test explorer | Report | PSS/E log. "Summary" goes back to the
    run's summary on the Black-Box Validation tab."""

    show_summary = Signal(str)

    PAGES = ("Summary", "Test explorer", "Report", "PSS/E log")

    def __init__(self, folder: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc, self.summary = read_run(folder)
        s = self.summary
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("modelBar")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(t.GUTTER + 4, 8, t.GUTTER, 8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label(f"{s.model} on PSS/E {s.short_version} · {s.level_title}", "cardTitle"))
        sub = QHBoxLayout()
        compared = ", ".join(name for name, _v, _p in s.compared)
        sub.addWidget(label(f"{s.date_text()} · {s.cases} cases" + (f" · vs {compared}" if compared else ""), "muted"))
        if s.overall:
            sub.addWidget(verdict_badge(s.overall))
        sub.addStretch()
        titles.addLayout(sub)
        hl.addLayout(titles)
        hl.addSpacing(24)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for i, name in enumerate(self.PAGES):
            b = QPushButton(name)
            b.setObjectName("navTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(36)
            b.clicked.connect(lambda _=False, idx=i: self.set_page(idx))
            self.nav.addButton(b)
            hl.addWidget(b)
            self.nav_buttons[name] = b
        hl.addStretch()
        hl.addWidget(button("Open run folder", lambda: open_folder(s.folder), kind="secondary"))
        hl.addWidget(button("Save bundle…", self._save_bundle, kind="secondary"))
        outer.addWidget(header)

        self.stack = QStackedWidget()
        self.explorer = ResultsExplorer()
        self.report_view = _web_view(300)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("monoText")
        self.log_view.setReadOnly(True)
        self.log_caption = label("", "muted")
        log_page = QWidget()
        ll = QVBoxLayout(log_page)
        ll.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        ll.addWidget(self.log_caption)
        ll.addWidget(self.log_view)
        explorer_page = QWidget()
        el = QVBoxLayout(explorer_page)
        el.setContentsMargins(t.GUTTER, t.GUTTER, t.GUTTER, t.GUTTER)
        el.addWidget(self.explorer)
        self.stack.addWidget(explorer_page)
        self.stack.addWidget(self.report_view)
        self.stack.addWidget(log_page)
        outer.addWidget(self.stack, stretch=1)
        self.explorer.load(s.folder)
        self.explorer.cases_changed.connect(self._refresh_log)
        self._report_loaded = False
        self.set_page(1)

    def set_page(self, index: int) -> None:
        if index == 0:
            self.nav_buttons[self.PAGES[self.stack.currentIndex() + 1]].setChecked(True)
            self.show_summary.emit(str(self.summary.folder))
            return
        self.stack.setCurrentIndex(index - 1)
        self.nav_buttons[self.PAGES[index]].setChecked(True)
        if index == 2 and not self._report_loaded:
            report = self.summary.folder / "report.html"
            if report.exists():
                self.report_view.load(QUrl.fromLocalFile(str(report)))
                self._report_loaded = True
        if index == 3:
            self._refresh_log()

    def current_page(self) -> str:
        return self.PAGES[self.stack.currentIndex() + 1]

    def _refresh_log(self) -> None:
        cases = self.explorer.checked_cases()
        if not cases:
            self.log_caption.setText("Tick a case in the Test explorer to read its PSS/E log.")
            self.log_view.setPlainText("")
            return
        case = cases[0]
        log = case.folder / "psse.log"
        self.log_caption.setText(f"{case.group}: {case.label} · {log}")
        self.log_view.setPlainText(log.read_text(errors="replace") if log.exists() else "This case has no psse.log.")

    def _save_bundle(self) -> None:
        src = self.summary.folder / "bundle.zip"
        if not src.exists():
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save bundle", src.name, "Zip (*.zip)")
        if dest:
            shutil.copyfile(src, dest)

    def shutdown(self) -> None:
        self.explorer.shutdown()
        self.report_view.setUrl(QUrl("about:blank"))
