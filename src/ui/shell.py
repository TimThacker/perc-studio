"""The app shell: the top app bar (logo, workflow tabs, closable run tabs, version pill),
the page stack under it, and the footer.

The workflow tabs are fixed; run tabs are added at run time (one per black-box
validation run) and can be closed. Pages are created once and kept, so their state
survives switching tabs. `go()` is the one way a screen sends the user to another
one (with optional prefill), instead of reaching into the shell's widgets.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import tokens as t
from app.build_info import __version__
from app.config import (
    CURENT_ICON_PATH,
    CURENT_LOGO_PATH,
    ENGINEERING_TOOL_NOTICE,
    TVA_LOGO_PATH,
)
from ui.theme import repolish

APP_TITLE = "PERC Studio"
APP_SUBTITLE = "PSS/E dynamic load models for large data center loads"
FOOTER_CREDIT = "Developed by CURENT, University of Tennessee, Knoxville, with the Tennessee Valley Authority"


def version_pill_text() -> str:
    return f"App v{__version__}"


class _RunTabButton(QWidget):
    """A closable run tab: blue dot, label, close cross."""

    clicked = Signal()
    close_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runTab")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 2, 0)
        layout.setSpacing(0)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {t.PARTNER_BLUE}; font-size: 9px;")
        self.label = QPushButton(title)
        self.label.setObjectName("runTabLabel")
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.clicked.connect(self.clicked)
        self.close_button = QToolButton()
        self.close_button.setObjectName("runTabClose")
        self.close_button.setText("×")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setAccessibleName("Close run tab")
        self.close_button.setToolTip("Close run tab")
        self.close_button.clicked.connect(self.close_requested)
        layout.addWidget(dot)
        layout.addWidget(self.label)
        layout.addWidget(self.close_button)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        repolish(self)


class AppShell(QWidget):
    """App bar + page stack + footer. Pages are keyed by a short id ("screening", ...)."""

    current_changed = Signal(str)
    run_tab_closed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: dict[str, QWidget] = {}
        self._titles: dict[str, str] = {}
        self._nav: dict[str, QPushButton] = {}
        self._run_tabs: dict[str, _RunTabButton] = {}
        self._order: list[str] = []
        self._current: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_app_bar())
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)
        layout.addWidget(self._build_footer())

    # --- building ----------------------------------------------------------------------------------

    def _build_app_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("appBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setFixedHeight(t.APP_BAR_HEIGHT)
        row = QHBoxLayout(bar)
        row.setContentsMargins(t.GUTTER + 4, 0, t.GUTTER, 0)
        row.setSpacing(0)

        logo = QLabel()
        pixmap = QPixmap(CURENT_ICON_PATH)
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(30, Qt.SmoothTransformation))
        row.addWidget(logo)
        row.addSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.setContentsMargins(0, 0, 0, 0)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setObjectName("appSubtitle")
        titles.addStretch()
        titles.addWidget(title)
        titles.addWidget(subtitle)
        titles.addStretch()
        row.addLayout(titles)
        row.addSpacing(28)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_row = QHBoxLayout()
        self._nav_row.setSpacing(4)
        row.addLayout(self._nav_row)

        self._divider = QFrame()
        self._divider.setObjectName("appBarDivider")
        self._divider.setFixedSize(1, 24)
        self._divider.setVisible(False)
        row.addSpacing(10)
        row.addWidget(self._divider)
        row.addSpacing(6)
        self._run_row = QHBoxLayout()
        self._run_row.setSpacing(2)
        row.addLayout(self._run_row)
        row.addStretch(1)

        self.version_pill = QLabel(version_pill_text())
        self.version_pill.setObjectName("versionPill")
        self.version_pill.setFixedHeight(24)
        row.addWidget(self.version_pill, alignment=Qt.AlignVCenter)
        return bar

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("appFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        footer.setMinimumHeight(t.FOOTER_MIN_HEIGHT)
        row = QHBoxLayout(footer)
        row.setContentsMargins(t.GUTTER + 4, 6, t.GUTTER, 6)
        row.setSpacing(16)
        notice = QLabel(f"<b>Engineering tool notice:</b> {ENGINEERING_TOOL_NOTICE}")
        notice.setObjectName("footerNotice")
        notice.setWordWrap(True)
        row.addWidget(notice, stretch=3)
        credit = QLabel(FOOTER_CREDIT)
        credit.setObjectName("footerBrandText")
        credit.setWordWrap(True)
        credit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(credit, stretch=2)
        for path, alt in ((CURENT_LOGO_PATH, "CURENT"), (TVA_LOGO_PATH, "TVA")):
            logo = QLabel()
            pixmap = QPixmap(path)
            if pixmap.isNull():
                logo.setText(alt)
            else:
                logo.setPixmap(pixmap.scaledToHeight(24, Qt.SmoothTransformation))
            row.addWidget(logo)
        self.footer = footer
        return footer

    # --- workflow pages ----------------------------------------------------------------------------

    def add_page(self, key: str, title: str, widget: QWidget) -> None:
        button = QPushButton(title)
        button.setObjectName("navTab")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _=False, k=key: self.set_current(k))
        bold = QFont(button.font())
        bold.setWeight(QFont.DemiBold)
        button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(title) + 32)  # the active tab is semibold
        self._nav_group.addButton(button)
        self._nav_row.addWidget(button)
        self._nav[key] = button
        self._pages[key] = widget
        self._titles[key] = title
        self._order.append(key)
        self.stack.addWidget(widget)
        if self._current is None:
            self.set_current(key)

    def page(self, key: str) -> QWidget:
        return self._pages[key]

    def page_keys(self) -> list[str]:
        """Workflow pages, in tab order (run tabs excluded)."""
        return [k for k in self._order if k not in self._run_tabs]

    def title(self, key: str) -> str:
        return self._titles[key]

    def current_key(self) -> str | None:
        return self._current

    def set_current(self, key: str) -> None:
        widget = self._pages[key]
        self.stack.setCurrentWidget(widget)
        self._current = key
        for k, button in self._nav.items():
            button.setChecked(k == key)
        for k, tab in self._run_tabs.items():
            tab.set_active(k == key)
        self.current_changed.emit(key)

    def go(self, key: str, **prefill) -> QWidget:
        """Switch to a page, handing it `prefill` (its `prefill(**kwargs)` method) when given."""
        self.set_current(key)
        page = self._pages[key]
        if prefill and hasattr(page, "prefill"):
            page.prefill(**prefill)
        return page

    # --- run tabs ----------------------------------------------------------------------------------

    def open_run_tab(self, key: str, title: str, widget_factory) -> QWidget:
        """Focus the run tab `key`, creating it with `widget_factory()` if it is not open yet."""
        if key not in self._run_tabs:
            widget = widget_factory()
            tab = _RunTabButton(title)
            tab.clicked.connect(lambda k=key: self.set_current(k))
            tab.close_requested.connect(lambda k=key: self.close_run_tab(k))
            self._run_tabs[key] = tab
            self._run_row.addWidget(tab)
            self._pages[key] = widget
            self._titles[key] = title
            self._order.append(key)
            self.stack.addWidget(widget)
            self._divider.setVisible(True)
        self.set_current(key)
        return self._pages[key]

    def run_tab_keys(self) -> list[str]:
        return list(self._run_tabs)

    def run_tab_button(self, key: str) -> _RunTabButton:
        return self._run_tabs[key]

    def close_run_tab(self, key: str) -> None:
        tab = self._run_tabs.pop(key, None)
        if tab is None:
            return
        widget = self._pages.pop(key)
        self._titles.pop(key, None)
        self._order.remove(key)
        if hasattr(widget, "shutdown"):
            widget.shutdown()
        self.stack.removeWidget(widget)
        widget.deleteLater()
        tab.deleteLater()
        self._divider.setVisible(bool(self._run_tabs))
        if self._current == key:
            self.set_current(self.page_keys()[0] if "blackbox" not in self._pages else "blackbox")
        self.run_tab_closed.emit(key)

    def shutdown(self) -> None:
        for key in list(self._run_tabs):
            self.close_run_tab(key)


class TabsCompat:
    """The few `QTabWidget` calls older code and tests make on `MainWindow.tabs`, over the shell's
    workflow pages."""

    def __init__(self, shell: AppShell) -> None:
        self._shell = shell

    def count(self) -> int:
        return len(self._shell.page_keys())

    def tabText(self, index: int) -> str:
        return self._shell.title(self._shell.page_keys()[index])

    def widget(self, index: int) -> QWidget:
        return self._shell.page(self._shell.page_keys()[index])

    def currentWidget(self) -> QWidget:
        return self._shell.page(self._shell.current_key())

    def currentIndex(self) -> int:
        keys = self._shell.page_keys()
        return keys.index(self._shell.current_key()) if self._shell.current_key() in keys else -1

    def setCurrentIndex(self, index: int) -> None:
        self._shell.set_current(self._shell.page_keys()[index])

    def setCurrentWidget(self, widget: QWidget) -> None:
        for key in self._shell.page_keys() + self._shell.run_tab_keys():
            if self._shell.page(key) is widget:
                self._shell.set_current(key)
                return
        raise ValueError("not a page of this window")
