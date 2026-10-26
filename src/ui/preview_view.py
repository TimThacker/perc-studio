"""The live response charts: a QWebEngineView showing `preview.page`'s three cards,
loaded once and then updated in place."""

from __future__ import annotations

from pathlib import Path

import plotly
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app import tokens as t
from preview.page import live_update_js, render_page

# plotly.js as shipped inside the `plotly` package (bundled with it by
# PyInstaller too) - see ResponsePreviewPanel.
_PLOTLY_JS = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"


class ResponsePreviewPanel(QWidget):
    """The page is loaded once, with plotly.js from the copy installed with the `plotly` package (never a CDN:
    the app must work on offline or firewalled machines). Every later result is pushed into the running page
    through `Plotly.react(...)`, which keeps the viewer's zoom and pan. A result that arrives while the page is
    still loading replaces the page instead (a script run before plotly.js loads would be lost)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView()
        # Two rows of cards stay legible down to about this height; the page scrolls rather than squashing them.
        self.view.setMinimumHeight(520)
        self.view.page().setBackgroundColor(QColor(t.GROUND))
        self.view.loadFinished.connect(self._on_load_finished)
        layout.addWidget(self.view)
        self._loaded = False
        self._ready = False
        self.last_html = ""
        self.last_js = ""

    def reset(self) -> None:
        """Forget the loaded page (the next result reloads it)."""
        self._loaded = False
        self._ready = False

    def _on_load_finished(self, ok: bool) -> None:
        self._ready = bool(ok)

    def show_result(self, result, preset) -> None:
        if self._loaded and self._ready:
            self.last_js = live_update_js(result, preset)
            self.view.page().runJavaScript(self.last_js)
            return
        self.last_html = render_page(result, preset, plotly_src=_PLOTLY_JS.name)
        # The file:// base URL lets the page's relative <script src> load the local plotly.min.js.
        self._ready = False
        self.view.setHtml(self.last_html, QUrl.fromLocalFile(str(_PLOTLY_JS.parent) + "/"))
        self._loaded = True
