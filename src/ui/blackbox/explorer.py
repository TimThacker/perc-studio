"""The test explorer of a black-box run: tick the cases (benchmark tests) you want, tick the
channels, and read them on an interactive plot; the channel files behind the ticked cases are
listed underneath with their full paths.

Widgets only. The reading and the figure are in `blackbox/explorer.py`, the channel
file parser in `blackbox/outx.py`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import tokens as t
from blackbox.explorer import (
    PLOT_COLORS,
    CaseEntry,
    ResultsError,
    ResultsSet,
    build_figure,
    channel_names,
    load_case,
    open_results,
)
from ui.components import FileLocationRow, label

CHANNEL_HELP = {
    "V": "bus voltage (pu)",
    "F": "bus frequency deviation (pu of 60 Hz)",
    "F (Hz)": "bus frequency (Hz)",
    "P": "load active power (pu of the rig's base)",
    "Q": "load reactive power (pu of the rig's base)",
}
CHANNEL_CHIP = {"V": "V · bus voltage", "P": "P · active power", "Q": "Q · reactive power",
                "F": "F · frequency deviation", "F (Hz)": "F · frequency (Hz)"}
DEFAULT_CHANNELS = ("V", "P")
MAX_CASES_ON_PLOT = 12
VERDICT_COLORS = {"rode through": (t.BRAND_TINT, t.BRAND_DARK), "tripped": (t.TRIP_TINT, t.TRIP_TEXT)}


class ResultsExplorer(QWidget):
    cases_changed = Signal()

    def __init__(self, parent=None, *, show_open: bool = True):
        super().__init__(parent)
        self._results: ResultsSet | None = None
        self._loaded: dict[str, object] = {}  # case key -> ChannelFile or None, read once
        self._plot_dir = tempfile.TemporaryDirectory(prefix="bbv_plot_", ignore_cleanup_errors=True)
        self._plot_count = 0
        self._busy = False
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(150)
        self._refresh.timeout.connect(self._draw)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_choices(show_open))
        split.addWidget(self._build_plot_side())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([360, 840])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

    # --- building ----------------------------------------------------------------------------------------------

    def _build_choices(self, show_open: bool) -> QWidget:
        pane = QFrame()
        pane.setObjectName("card")
        pane.setAttribute(Qt.WA_StyledBackground, True)
        pane.setMinimumWidth(300)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.open_button = QPushButton("Open results…")
        self.open_button.setObjectName("smallButton")
        self.open_button.setToolTip("A run folder, its validation.json, or a bundle.zip from another machine.")
        self.open_button.clicked.connect(self._browse)
        self.open_button.setVisible(show_open)
        self.source_label = QLabel("No results loaded.")
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(True)
        top.addWidget(self.source_label, stretch=1)
        top.addWidget(self.open_button)
        layout.addLayout(top)

        layout.addWidget(label("Filter cases", "fieldLabel"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("e.g. 0.5 pu or tripped")
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)
        self.count_label = label("", "muted")
        layout.addWidget(self.count_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Case (tick to plot)", "Result"])
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setFrameShape(QFrame.NoFrame)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._tree_changed)
        layout.addWidget(self.tree, stretch=1)
        clear = QPushButton("Untick all cases")
        clear.setObjectName("smallButton")
        clear.clicked.connect(lambda: self._set_all_tests(False))
        layout.addWidget(clear, alignment=Qt.AlignLeft)
        return pane

    def _build_plot_side(self) -> QWidget:
        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(t.GUTTER, 0, 0, 0)
        layout.setSpacing(t.GUTTER)

        bar = QFrame()
        bar.setObjectName("card")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.addWidget(label("Channels", "fieldLabel"))
        self.channels = QListWidget()
        self.channels.setFlow(QListView.LeftToRight)
        self.channels.setWrapping(True)
        self.channels.setSpacing(4)
        self.channels.setFrameShape(QFrame.NoFrame)
        self.channels.setFixedHeight(38)
        self.channels.setStyleSheet(f"QListWidget {{ background: transparent; border: none; }} QListWidget::item {{ "
                                    f"border: 1px solid {t.CONTROL_BORDER}; border-radius: 13px; padding: 2px 8px; }}")
        self.channels.itemChanged.connect(lambda _: self._refresh.start())
        bl.addWidget(self.channels, stretch=1)
        bl.addWidget(label("Drag to zoom · double-click to reset", "muted"))
        layout.addWidget(bar)

        plot_card = QFrame()
        plot_card.setObjectName("card")
        plot_card.setAttribute(Qt.WA_StyledBackground, True)
        pl = QVBoxLayout(plot_card)
        pl.setContentsMargins(8, 8, 8, 8)
        self.view = QWebEngineView()
        self.view.setMinimumHeight(360)
        pl.addWidget(self.view)
        layout.addWidget(plot_card, stretch=1)

        files = QFrame()
        files.setObjectName("card")
        files.setAttribute(Qt.WA_StyledBackground, True)
        fl = QVBoxLayout(files)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.addWidget(label("Source files for the ticked cases", "cardTitle"))
        self.files_box = QVBoxLayout()
        self.files_box.setSpacing(4)
        fl.addLayout(self.files_box)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        fl.addWidget(self.status)
        layout.addWidget(files)
        return side

    # --- loading -----------------------------------------------------------------------------------------------

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Open a results folder")
        if not folder:
            path, _ = QFileDialog.getOpenFileName(self, "Open validation.json or bundle.zip", "",
                                                  "Results (validation.json *.zip)")
            if not path:
                return
            folder = path
        self.load(folder)

    def load(self, path) -> bool:
        """Show the cases of a run folder, validation.json or bundle.zip. False (and a message) if it is not one."""
        try:
            results = open_results(path)
        except ResultsError as exc:
            self.status.setText(str(exc))
            return False
        if self._results is not None:
            self._results.close()
        self._results = results
        self._loaded.clear()
        self.source_label.setText(f"{Path(path).name}: {len(results.cases)} cases")
        self._fill_tree(results.cases)
        self.channels.clear()
        self.status.setText("Tick a case to plot it.")
        self._draw()
        return True

    def _fill_tree(self, cases: list[CaseEntry]):
        self._busy = True
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for case in cases:
            parent = groups.get(case.group)
            if parent is None:
                parent = QTreeWidgetItem([case.group, ""])
                parent.setFlags(parent.flags() & ~Qt.ItemIsUserCheckable)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                self.tree.addTopLevelItem(parent)
                groups[case.group] = parent
            item = QTreeWidgetItem([case.label, case.verdict])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, case.key)
            colors = VERDICT_COLORS.get(case.verdict)
            if colors:
                item.setBackground(1, QBrush(QColor(colors[0])))
                item.setForeground(1, QBrush(QColor(colors[1])))
            item.setSizeHint(0, QSize(0, 24))
            parent.addChild(item)
        for parent in groups.values():
            parent.setText(0, f"{parent.text(0)} ({parent.childCount()})")
        self._busy = False
        first = next(iter(groups.values()), None)
        if first is not None and first.childCount():
            first.setExpanded(True)
            first.child(0).setCheckState(0, Qt.Checked)  # something on the plot straight away
        self._update_count()

    # --- choosing ----------------------------------------------------------------------------------------------

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            shown = 0
            for c in range(group.childCount()):
                item = group.child(c)
                hide = bool(needle) and needle not in (item.text(0) + " " + item.text(1)).lower()
                item.setHidden(hide)
                shown += not hide
            group.setHidden(shown == 0)
            if needle and shown:
                group.setExpanded(True)
        self._update_count()

    def _update_count(self):
        total = sum(1 for _ in self._case_items())
        shown = sum(1 for item in self._case_items() if not item.isHidden())
        ticked = sum(1 for item in self._case_items() if item.checkState(0) == Qt.Checked)
        self.count_label.setText(f"{shown} of {total} cases · {ticked} ticked")

    def _set_all_tests(self, checked: bool):
        self._busy = True
        for item in self._case_items():
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self._busy = False
        self._tree_changed()

    def _case_items(self):
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            for c in range(group.childCount()):
                yield group.child(c)

    def _checked_cases(self) -> list[CaseEntry]:
        if self._results is None:
            return []
        keys = {item.data(0, Qt.UserRole) for item in self._case_items() if item.checkState(0) == Qt.Checked}
        return [c for c in self._results.cases if c.key in keys][:MAX_CASES_ON_PLOT]

    def checked_cases(self) -> list[CaseEntry]:
        return self._checked_cases()

    def _checked_channels(self) -> list[str]:
        return [self.channels.item(i).data(Qt.UserRole) for i in range(self.channels.count())
                if self.channels.item(i).checkState() == Qt.Checked]

    def _tree_changed(self, *_):
        if not self._busy:
            self._update_count()
            self._refresh.start()

    def _data_for(self, case: CaseEntry):
        if case.key not in self._loaded:
            self._loaded[case.key] = load_case(case)
        return self._loaded[case.key]

    def _sync_channels(self, names: list[str]):
        """Keep ticked channels ticked; list the union of what the chosen cases recorded."""
        ticked = set(self._checked_channels())
        first_time = self.channels.count() == 0
        current = [self.channels.item(i).data(Qt.UserRole) for i in range(self.channels.count())]
        if current == names:
            return
        self.channels.blockSignals(True)
        self.channels.clear()
        for name in names:
            item = QListWidgetItem(CHANNEL_CHIP.get(name, name))
            item.setToolTip(CHANNEL_HELP.get(name, name))
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            keep = name in ticked or (first_time and name in DEFAULT_CHANNELS)
            item.setCheckState(Qt.Checked if keep else Qt.Unchecked)
            self.channels.addItem(item)
        self.channels.blockSignals(False)
        if not self._checked_channels() and names:
            self.channels.item(0).setCheckState(Qt.Checked)

    def _show_files(self, cases: list[CaseEntry]) -> None:
        while self.files_box.count():
            item = self.files_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, case in enumerate(cases):
            path = case.folder / "case.outx"
            if not path.exists():
                path = case.folder / "result.csv"
            row = FileLocationRow("", path, reveal=True, color=PLOT_COLORS[i % len(PLOT_COLORS)])
            row.setToolTip(f"{case.group}: {case.label}")
            self.files_box.addWidget(row)

    # --- drawing -----------------------------------------------------------------------------------------------

    def _draw(self):
        cases = self._checked_cases()
        selected = [(c, d) for c in cases if (d := self._data_for(c)) is not None]
        self._sync_channels(channel_names([d for _, d in selected]))
        chosen = self._checked_channels()
        self._show_files(cases)
        self.cases_changed.emit()
        if not selected:
            self.view.setHtml(f"<body style='font-family:sans-serif;color:{t.TEXT_MUTED};padding:2em'>"
                              "Tick a case on the left to plot it.</body>")
            return
        figure = build_figure(selected, chosen)
        self._plot_count += 1
        path = Path(self._plot_dir.name) / f"plot{self._plot_count}.html"
        # plotly.min.js is written once next to the page; the page itself stays small
        figure.write_html(str(path), include_plotlyjs="directory", config={"displaylogo": False})
        self.view.load(QUrl.fromLocalFile(str(path)))
        ticked = sum(1 for i in self._case_items() if i.checkState(0) == Qt.Checked)
        noted = f" (first {MAX_CASES_ON_PLOT} shown)" if ticked > MAX_CASES_ON_PLOT else ""
        self.status.setText(f"{len(selected)} case(s), {len(chosen)} channel(s){noted}. Each folder also holds "
                            "job.json, meta.json, result.csv and psse.log.")

    def shutdown(self):
        if self._results is not None:
            self._results.close()
        self.view.setUrl(QUrl("about:blank"))  # release the plot file before its folder is removed
        self._plot_dir.cleanup()
