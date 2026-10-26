"""The Documentation tab: the documentation library browser, the in-app PERC1
reference page and the About page. Moved out of ui/main_window.py unchanged."""

from __future__ import annotations

from html import escape as html_escape
from pathlib import Path

import PySide6.QtSvg  # noqa: F401 - registers the "svg" QImageReader plugin so
import yaml

# QTextDocument/QTextBrowser can rasterize the .svg envelope plots the preset
# pages in the Documentation tab embed (DocumentationPanel); without this import the plugin
# never loads and those images silently fail to render.
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.build_info import BUILD_COMMIT, __version__
from app.config import CURENT_GREEN, ENGINEERING_TOOL_NOTICE
from app.resources import resource_path
from load_models.perc1_dll.cons import PERC1_CON_ORDER, PERC1_DISPLAY_FIELDS
from presets.ridethrough import RIDE_THROUGH_PRESETS


def _heading_slug(text: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    kept = "".join(ch for ch in text.strip().lower() if ch.isalnum() or ch in " -_")
    return kept.replace(" ", "-")


class _DocumentBrowser(QTextBrowser):
    """Renders the documentation library's markdown pages; the pages generated
    in-app (the PERC1 quick reference and About - HTML, not files) are served
    from the "app:" scheme so they take part in the same Back/Forward history
    as every file."""

    APP_REFERENCE = QUrl("app:reference")
    APP_ABOUT = QUrl("app:about")

    def loadResource(self, resource_type, url):  # Qt override (camelCase by necessity)
        if url.scheme() == "app":
            return _about_html() if url.path() == "about" else _documentation_html()
        return super().loadResource(resource_type, url)


class DocumentationPanel(QWidget):
    """The Documentation tab: a navigable list of every user- and developer-
    facing document on the left, the selected document on the right. Links
    between documents open in place (and the list follows); web links open in
    the system browser; other files open in their default application."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.tree = QTreeWidget()
        self.tree.setObjectName("docsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(260)
        self.tree.setIndentation(14)
        self._items: dict[str, QTreeWidgetItem] = {}
        for group, entries in self._contents():
            group_item = QTreeWidgetItem([group])
            group_item.setFlags(Qt.ItemIsEnabled)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            self.tree.addTopLevelItem(group_item)
            for title, url in entries:
                item = QTreeWidgetItem([title])
                item.setToolTip(0, title)  # long preset names are elided in the list
                item.setData(0, Qt.UserRole, url)
                group_item.addChild(item)
                self._items[self._key(url)] = item
        self.tree.expandAll()
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

        reader = QWidget()
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        reader_layout.setSpacing(6)
        nav = QHBoxLayout()
        self.back_button = QPushButton("‹ Back")
        self.forward_button = QPushButton("Forward ›")
        for button in (self.back_button, self.forward_button):
            button.setObjectName("secondaryButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setEnabled(False)
            nav.addWidget(button)
        self.title_label = QLabel("")
        self.title_label.setObjectName("docsTitle")
        nav.addSpacing(8)
        nav.addWidget(self.title_label, stretch=1)
        reader_layout.addLayout(nav)

        self.browser = _DocumentBrowser()
        self.browser.setObjectName("docsBrowser")
        self.browser.setOpenLinks(False)  # every link goes through _on_link
        self.browser.anchorClicked.connect(self._on_link)
        self.browser.sourceChanged.connect(self._on_source_changed)
        self.browser.backwardAvailable.connect(self.back_button.setEnabled)
        self.browser.forwardAvailable.connect(self.forward_button.setEnabled)
        self.back_button.clicked.connect(self.browser.backward)
        self.forward_button.clicked.connect(self.browser.forward)
        reader_layout.addWidget(self.browser)
        layout.addWidget(reader, stretch=1)

        first_group = self._contents()[0][1]
        self._open(first_group[0][1])

    @staticmethod
    def _contents() -> list[tuple[str, list[tuple[str, QUrl]]]]:
        """The library as listed in `docs/user/library.yaml`. A group marked
        `source_only: true` (the contributor docs, which the release build does
        not ship) lists only the pages that exist, and is left out when none do."""
        library = yaml.safe_load(DOC_LIBRARY_FILE.read_text(encoding="utf-8"))
        contents = []
        for group in library["groups"]:
            entries: list[tuple[str, QUrl]] = []
            for page in group["pages"]:
                if page.get("presets"):
                    entries += [(preset.label, QUrl.fromLocalFile(str(PRESET_DOCS_DIR / f"{preset.id}.md")))
                                for preset in RIDE_THROUGH_PRESETS.values()]
                elif "app" in page:
                    entries.append((page["title"], QUrl(f"app:{page['app']}")))
                else:
                    path = (DOC_LIBRARY_FILE.parent / page["path"]).resolve()
                    if group.get("source_only") and not path.is_file():
                        continue
                    entries.append((page["title"], QUrl.fromLocalFile(str(path))))
            if entries:
                contents.append((group["title"], entries))
        return contents

    @staticmethod
    def _key(url: QUrl) -> str:
        """History/list key: the document itself, ignoring any #fragment."""
        if url.scheme() == "app":
            return url.toString()
        return str(Path(url.toLocalFile()).resolve()).lower()

    def open_document(self, path) -> None:
        self._open(QUrl.fromLocalFile(str(path)))

    def _open(self, url: QUrl) -> None:
        kind = QTextDocument.HtmlResource if url.scheme() == "app" else QTextDocument.MarkdownResource
        self.browser.setSource(url, kind)

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        url = item.data(0, Qt.UserRole)
        if url is not None:
            self._open(url)

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if url.isRelative() and not url.path():  # an in-page #anchor
            self._scroll_to_heading(url.fragment())
            return
        target = self.browser.source().resolved(url) if url.isRelative() else url
        if target.isLocalFile() and target.toLocalFile().lower().endswith(".md"):
            self._open(QUrl.fromLocalFile(target.toLocalFile()))  # history keys ignore the #fragment
            if url.hasFragment():
                self._scroll_to_heading(url.fragment())
        elif target.isLocalFile():
            QDesktopServices.openUrl(target)  # a script, figure or data file

    def _scroll_to_heading(self, fragment: str) -> bool:
        """Scroll to the heading whose GitHub-style slug is `fragment` (Qt's
        markdown import gives headings no anchor names of their own)."""
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() and _heading_slug(block.text()) == fragment:
                cursor = self.browser.textCursor()
                cursor.setPosition(block.position())
                self.browser.setTextCursor(cursor)
                # Put the heading at the top, not just somewhere on screen.
                bar = self.browser.verticalScrollBar()
                bar.setValue(bar.maximum())
                self.browser.ensureCursorVisible()
                return True
            block = block.next()
        return False

    def _on_source_changed(self, url: QUrl) -> None:
        item = self._items.get(self._key(url))
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(item) if item else self.tree.clearSelection()
        self.tree.blockSignals(False)
        self.title_label.setText(item.text(0) if item else Path(url.toLocalFile()).name)


def _table_rows(fields) -> str:
    # Accepts both PERC1_DISPLAY_FIELDS' (name, label, tooltip) rows and
    # CLOD_DISPLAY_FIELDS' plain (name, label) rows - the CON name is already
    # its own visible column here, so a tooltip (present or not) is unused.
    return "".join(
        f'<tr><td style="padding:6px 10px;border:1px solid #d5e1ee;"><code>{name}</code></td>'
        f'<td style="padding:6px 10px;border:1px solid #d5e1ee;">{label}</td></tr>'
        for name, label, *_rest in fields
    )


_PERC1_CORE_FIELD_COUNT = 10

# The user documentation library (shipped with the app) - see
# docs/user/library.yaml. Resolved through `app.resources` so it works frozen too.
USER_DOCS_DIR = resource_path("docs", "user")
DOC_LIBRARY_FILE = USER_DOCS_DIR / "library.yaml"

# Each preset also has its own dedicated write-up here, named by preset id
# (e.g. `ercot_nogrr282.md`) - see docs/user/presets/README.md.
PRESET_DOCS_DIR = USER_DOCS_DIR / "presets"

def _about_html() -> str:
    """The Documentation tab's About page: version/build, attribution,
    the engineering-tool notice and the license texts shipped with the app."""
    def read(name: str) -> str:
        path = resource_path(name)
        return html_escape(path.read_text(encoding="utf-8")) if path.is_file() else f"({name} not found)"

    build = f" &middot; build <code>{BUILD_COMMIT}</code>" if BUILD_COMMIT else ""
    pre = 'style="background:#f4f8fc;border:1px solid #c9dced;border-radius:8px;padding:12px;white-space:pre-wrap;"'
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1d2b36;">
    <h1 style="color:{CURENT_GREEN};">PERC Studio</h1>
    <p><b>Version {__version__}</b>{build}</p>
    <p>Accelerates data center modeling for transmission planning engineers. Builds documented PSS/E
    dynamic load models (currently the PERC1 and PERC2 family) for large data-center-class loads, with a live preview of each block's ride-through response against
    published grid-operator ride-through standards.</p>
    <p><b>Feedback and support:</b> report bugs and ask questions on the project's GitHub Issues page,
    <a href="https://github.com/TimThacker/perc-studio/issues">https://github.com/TimThacker/perc-studio/issues</a>. Please include this version number.</p>
    <p>Developed by CURENT (Center for Ultra-Wide-Area Resilient Electric Energy Transmission Networks,
    University of Tennessee, Knoxville) in partnership with the Tennessee Valley Authority.</p>
    <p><b>Engineering tool notice:</b> {ENGINEERING_TOOL_NOTICE}</p>
    <p>This app writes <code>.dyr</code> records for its supported load models. It does not include
    PSS/E or the model DLLs; obtain those separately.</p>
    <h2 style="color:{CURENT_GREEN};">License</h2>
    <pre {pre}>{read("LICENSE")}</pre>
    <h2 style="color:{CURENT_GREEN};">Third-party software</h2>
    <pre {pre}>{read("THIRD_PARTY_NOTICES.md")}</pre>
    </div>
    """


def _documentation_html() -> str:
    core_rows = _table_rows(PERC1_DISPLAY_FIELDS[:_PERC1_CORE_FIELD_COUNT])
    secondary_rows = _table_rows(PERC1_DISPLAY_FIELDS[_PERC1_CORE_FIELD_COUNT:])
    total_cons = len(PERC1_CON_ORDER)
    th = f'style="background:{CURENT_GREEN};color:#ffffff;padding:8px 10px;text-align:left;"'

    return f"""
    <div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1d2b36;">
    <h1 style="color:{CURENT_GREEN};">PSS/E PERC1 Load Model Reference</h1>
    <p>PERC1 ("Power Electronic Load Model") is the PSS/E v34/v35 user-defined
    model used to represent power-electronics-interfaced load - UPS/IT load,
    VFD-driven cooling, and similar - in bulk power system dynamic
    simulations. It is based on an Electric Vehicle (EV) charging load model
    jointly developed by EPRI and LBNL, built around two symmetric control
    loops (active and reactive power) plus a "cease and reconnect" state
    machine that governs the block's behavior during and after a voltage
    disturbance.</p>

    <h2 style="color:{CURENT_GREEN};">Model structure</h2>
    <p>Each power loop (active and reactive) is built from the same chain of blocks:</p>
    <ol>
    <li><b>Washout block</b> - optional high-pass filter on terminal voltage, used
    to shape the transient response. Bypassed by setting its gain/time constant to 0.</li>
    <li><b>Droop</b> (active power loop only) - makes real power responsive to
    system frequency. Bypassed by setting <code>DROOPA</code> to 0.</li>
    <li><b>Lead-lag block</b> - shapes the transient response further. Bypassed
    by setting both time constants to 0.</li>
    <li><b>ZIP exponent</b> (<code>NPA</code>/<code>NQA</code>) - selects whether
    the block behaves as constant power (0), constant current (1), or constant
    impedance (2) as terminal voltage moves away from 1.0 pu.</li>
    <li><b>Current limits</b> (<code>IPMAXA</code>/<code>IPMINA</code>/<code>IQMAXA</code>/<code>IQMINA</code>)
    - bound the per-unit current the block can draw.</li>
    <li><b>Numerical filter</b> (<code>TRA</code> / Tt) - a small filter time
    constant included purely to help simulation numerical stability
    (recommended: ~4x the simulation time step).</li>
    <li><b>FracOn cease/reconnect logic</b> - a state machine determining what
    fraction of the block's load is "on" at any instant, based on measured
    terminal voltage (and, for the frequency-protection CONs, system frequency).</li>
    </ol>

    <h2 style="color:{CURENT_GREEN};">Cease / reconnect options</h2>
    <p>The vendor model ships three alternative ways to drive the FracOn logic:</p>
    <table width="100%" cellspacing="0" style="border-collapse:collapse;">
    <tr><th {th}>Option</th><th {th}>What it represents</th><th {th}>Used by this app?</th></tr>
    <tr><td style="padding:6px 10px;border:1px solid #d5e1ee;"><b>1 - Undervoltage cease/reconnect</b></td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;">A single trip voltage/delay and a single reconnect
    voltage/delay/ramp - the load fully or partially "ceases" below a threshold and ramps back in after
    voltage recovers.</td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;"><b style="color:#1a7a3c;">Yes</b> - every
    preset and generic tier in this app sets this option's point.</td></tr>
    <tr><td style="padding:6px 10px;border:1px solid #d5e1ee;"><b>2 - Momentary cessation</b></td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;">The block rides through a brief sag/swell window
    (<code>VLBLK</code>/<code>VUBLK</code>) and resumes after a fixed delay, independent of a discrete
    trip/reconnect voltage.</td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;">No - CONs are present in every exported record at
    documented standard values, but this app does not enable it (<code>ICON(M+1)=0</code>).</td></tr>
    <tr><td style="padding:6px 10px;border:1px solid #d5e1ee;"><b>3 - Stepped multi-level trip/reconnect</b></td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;">Four voltage stages per direction, each with its
    own threshold and delay, plus one frequency trip/reconnect point per direction.</td>
    <td style="padding:6px 10px;border:1px solid #d5e1ee;"><b style="color:#1a7a3c;">Yes</b> - the compiled
    model always evaluates every voltage stage (confirmed in PSS/E), so presets fill all four from their
    published tables. Frequency has one trip point per direction (the vendor marks stages 2-4 NOT USED),
    set where a standard publishes a frequency table.</td></tr>
    </table>
    <p>Option 1's point is stage 1 of the Option 3 table, so the two are driven together. Option 2 stays off,
    but its CONs are still written at vendor-documented values so every record is complete.</p>

    <h2 style="color:{CURENT_GREEN};">Key parameters (set by the selected preset or tier)</h2>
    <p>Every field name below is the model's actual PSS/E CON mnemonic - not a simplified alias - so a value
    shown in the Advanced editor or the HTML report maps directly onto a specific position in the exported
    <code>.dyr</code> record.</p>
    <table width="100%" cellspacing="0" style="border-collapse:collapse;">
    <tr><th {th}>CON</th><th {th}>What it does</th></tr>
    {core_rows}
    </table>

    <h2 style="color:{CURENT_GREEN};">Secondary parameters (Advanced editor)</h2>
    <p>Held at vendor-documented standard defaults but still exposed for direct editing, since they are
    meaningful engineering settings even though a preset doesn't set them directly.</p>
    <table width="100%" cellspacing="0" style="border-collapse:collapse;">
    <tr><th {th}>CON</th><th {th}>What it does</th></tr>
    {secondary_rows}
    </table>
    <p style="color:#4a4a4a;font-size:0.9em;">The remaining CONs (Option 2, the unused frequency stages 2-4,
    and the unused B/C/D repeated channel blocks) are not exposed for editing here;
    they are still written to every exported record (all {total_cons}, in exact model order) at the
    vendor-documented values. The "PERC1 model reference" page describes what they hold.</p>

    <h2 style="color:{CURENT_GREEN};">The exported .dyr record</h2>
    <p>Both the IT/UPS and Cooling VFD blocks are written as PSS/E <code>USRLOD</code> records matching the
    vendor's exact PERC1 data sheet:</p>
    <pre style="background:#f4f8fc;border:1px solid #c9dced;border-radius:8px;padding:12px;">IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 173 33 250 0
ICON(M) ICON(M+1)
CON(J) ... CON(J+172)   / {total_cons} values, in exact model order</pre>
    <ul>
    <li>The <b>Record format</b> setting picks the vendor's <code>'PERC**'</code> suffix and matching
    <code>IT</code> code: Bus <code>PERCBL</code>/1, Owner <code>PERCOW</code>/2, Zone <code>PERCZN</code>/3,
    Area <code>PERCAR</code>/4, All <code>PERCAL</code>/5. The first field is the bus number for Bus, the
    owner/zone/area number for those formats, and 0 for All.</li>
    <li><b>PERC1 carries no MW/Mvar of its own</b> - it is a <code>USRLOD</code> model that
    attaches to an existing static Load record in the power flow (<code>.raw</code> case), matched by bus
    number and load ID.</li>
    <li>The exported file uses the same <code>@!</code>-commented, grouped-row layout as the vendor's own
    example <code>.dyr</code> file, so each row of numbers is self-labeled with its CON names directly
    above it.</li>
    </ul>
    </div>
    """
