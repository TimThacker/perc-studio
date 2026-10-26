"""The app's look: the QSS stylesheet and light palette, generated from `app.tokens`, and
the bundled IBM Plex fonts.

Object names and dynamic properties the stylesheet keys on (set them with
`setObjectName` / `setProperty`):

* `#card` - a white panel with a 1 px border and 8 px corners.
* `#modelBar` - the subtle strip under the app bar that holds the model controls.
* `QLabel#sectionLabel` - 11 px caps section heading in brand green.
* `QLabel#panelTitle`, `QLabel#emptyTitle`, `QLabel#muted`, `QLabel#fieldHint`, `QLabel#mono`.
* `QPushButton#secondaryButton`, `#linkButton`, `#smallButton`; `QPushButton[segment="true"]`
  for a segmented control.
* `QLineEdit[error="true"]` (and the spin boxes) - the error border.
* `QLabel[badge="..."]` - `internal`, `published`, `edited`, `trips`, `rides`, `fails`, `meets`,
  `warning`, `neutral`, `ready`.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from app import tokens as t
from app.resources import resource_path

FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)
FONTS_DIR = resource_path("assets", "fonts")

_fonts_loaded: list[str] | None = None


def load_fonts() -> list[str]:
    """Register the bundled IBM Plex files with Qt once; returns the families that loaded."""
    global _fonts_loaded
    if _fonts_loaded is None:
        families: set[str] = set()
        for name in FONT_FILES:
            path = FONTS_DIR / name
            if path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    families.update(QFontDatabase.applicationFontFamilies(font_id))
        _fonts_loaded = sorted(families)
    return _fonts_loaded


def mono_font(point_size: int | None = None) -> QFont:
    font = QFont(t.FONT_MONO)
    font.setStyleHint(QFont.Monospace)
    if point_size:
        font.setPixelSize(point_size)
    return font


def build_palette() -> QPalette:
    """A light palette so no gap falls back to a dark OS theme behind the stylesheet."""
    palette = QPalette()
    for role, color in (
        (QPalette.Window, t.GROUND), (QPalette.WindowText, t.TEXT), (QPalette.Base, t.SURFACE),
        (QPalette.AlternateBase, t.SURFACE_SUBTLE), (QPalette.Text, t.TEXT), (QPalette.Button, t.SURFACE),
        (QPalette.ButtonText, t.TEXT), (QPalette.ToolTipBase, t.SURFACE), (QPalette.ToolTipText, t.TEXT),
        (QPalette.Highlight, t.BRAND_TINT), (QPalette.HighlightedText, t.BRAND_DARK),
        (QPalette.PlaceholderText, t.TEXT_MUTED), (QPalette.Link, t.BRAND_TEXT),
        (QPalette.LinkVisited, t.BRAND_TEXT),
    ):
        palette.setColor(role, QColor(color))
    return palette


def build_qss() -> str:
    h = t.CONTROL_HEIGHT - 2  # inside the 1 px border
    hs = t.CONTROL_HEIGHT_SMALL - 2
    return f"""
    QMainWindow, QDialog {{ background: {t.GROUND}; color: {t.TEXT}; }}
    QWidget {{ color: {t.TEXT}; font-family: "{t.FONT_SANS}", "Segoe UI", Arial; font-size: {t.SIZE_BODY}px; }}
    QToolTip {{ background: {t.SURFACE}; color: {t.TEXT}; border: 1px solid {t.CARD_BORDER}; padding: 4px 6px; }}

    /* --- shell ------------------------------------------------------------------------------- */
    #appBar {{ background: {t.SURFACE}; border-bottom: 1px solid {t.CARD_BORDER}; }}
    QLabel#appTitle {{ font-size: 15px; font-weight: 600; color: {t.TEXT}; }}
    QLabel#appSubtitle {{ font-size: 11px; color: {t.TEXT_MUTED}; }}
    QPushButton#navTab {{
        background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
        color: {t.TEXT_MUTED}; font-size: 13px; font-weight: 500; padding: 0 14px; min-height: {t.APP_BAR_HEIGHT - 2}px;
    }}
    QPushButton#navTab:hover {{ color: {t.TEXT}; background: transparent; }}
    QPushButton#navTab:checked {{ color: {t.BRAND_TEXT}; font-weight: 600; border-bottom: 2px solid {t.BRAND}; }}
    QWidget#runTab {{ border-bottom: 2px solid transparent; }}
    QWidget#runTab[active="true"] {{ border-bottom: 2px solid {t.PARTNER_BLUE}; }}
    QPushButton#runTabLabel {{
        background: transparent; border: none; color: {t.PARTNER_BLUE}; font-size: 12px; font-weight: 500;
        padding: 0 4px 0 6px; min-height: {t.APP_BAR_HEIGHT - 4}px;
    }}
    QPushButton#runTabLabel:hover {{ background: transparent; text-decoration: underline; }}
    QToolButton#runTabClose {{ background: transparent; border: none; color: {t.TEXT_MUTED}; font-size: 14px; padding: 0 4px; }}
    QToolButton#runTabClose:hover {{ color: {t.TRIP}; }}
    QFrame#appBarDivider {{ background: {t.CARD_BORDER}; }}
    QLabel#versionPill {{
        border: 1px solid {t.CONTROL_BORDER}; border-radius: 11px; padding: 2px 10px;
        color: {t.TEXT_MUTED}; font-size: 11px; background: {t.SURFACE};
    }}
    #appFooter {{ background: {t.SURFACE}; border-top: 1px solid {t.CARD_BORDER}; }}
    QLabel#footerNotice, QLabel#footerBrandText {{ color: {t.TEXT_MUTED}; font-size: 11px; }}

    /* --- surfaces ---------------------------------------------------------------------------- */
    #card, QFrame#card {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CARD}px; }}
    #modelBar {{ background: {t.SURFACE_SUBTLE}; border-bottom: 1px solid {t.CARD_BORDER}; }}
    #stepperBar {{ background: {t.SURFACE}; border-bottom: 1px solid {t.CARD_BORDER}; }}
    #cardFooter {{ border-top: 1px solid {t.HAIRLINE}; background: transparent; }}
    #subtleBox {{ background: {t.SURFACE_SUBTLE}; border: 1px solid {t.HAIRLINE}; border-radius: {t.RADIUS_CONTROL}px; }}
    #dashedBox {{ background: {t.SURFACE_SUBTLE}; border: 1px dashed {t.CONTROL_BORDER}; border-radius: {t.RADIUS_CONTROL}px; }}
    #warningBox {{ background: {t.WARNING_BG}; border-radius: {t.RADIUS_CONTROL}px; }}
    #verdictTrips {{ background: {t.TRIP_BANNER}; border: 1px solid {t.TRIP_BANNER_BORDER}; border-radius: {t.RADIUS_CARD}px; }}
    #verdictRides {{ background: {t.RIDE_BANNER}; border: 1px solid {t.RIDE_BANNER_BORDER}; border-radius: {t.RADIUS_CARD}px; }}
    #verdictNeutral {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CARD}px; }}
    #tile {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CONTROL}px; }}
    #tile[state="trips"] {{ background: {t.TRIP_BANNER}; border-color: {t.TRIP_BANNER_BORDER}; }}
    #tile[state="rides"] {{ background: {t.RIDE_BANNER}; border-color: {t.RIDE_BANNER_BORDER}; }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ border: none; background: transparent; }}

    /* --- text -------------------------------------------------------------------------------- */
    QLabel#sectionLabel {{ color: {t.BRAND_TEXT}; font-size: {t.SIZE_SECTION_LABEL}px; font-weight: 600;
                           letter-spacing: 1px; text-transform: uppercase; }}
    QLabel#panelTitle {{ font-size: {t.SIZE_PANEL_TITLE}px; font-weight: 600; }}
    QLabel#emptyTitle {{ font-size: {t.SIZE_EMPTY_TITLE}px; font-weight: 600; }}
    QLabel#cardTitle {{ font-size: 13px; font-weight: 600; }}
    QLabel#muted, QLabel#fieldHint, QLabel#presetSource {{ color: {t.TEXT_MUTED}; font-size: {t.SIZE_SMALL}px; }}
    QLabel#fieldLabel {{ color: {t.TEXT}; font-size: {t.SIZE_SMALL}px; }}
    QLabel#mono {{ font-family: "{t.FONT_MONO}", Consolas; }}
    QLabel#errorText {{ color: {t.TRIP}; font-size: {t.SIZE_SMALL}px; }}
    QLabel#bigFigure {{ font-family: "{t.FONT_MONO}", Consolas; font-size: 15px; font-weight: 500; }}
    QLabel {{ background: transparent; }}

    QLabel[badge] {{ border-radius: {t.RADIUS_TAG}px; padding: 1px 6px; font-size: 11px; font-weight: 600; }}
    QLabel[badge="internal"], QLabel[badge="ready"], QLabel[badge="meets"] {{ background: {t.BRAND_TINT}; color: {t.BRAND_DARK}; }}
    QLabel[badge="published"], QLabel[badge="edited"] {{ background: {t.EDITED_TINT}; color: {t.EDITED_TEXT}; }}
    QLabel[badge="edited"] {{ border: 1px solid {t.EDITED_BORDER}; border-radius: 10px; padding: 1px 8px; }}
    QLabel[badge="fails"] {{ background: {t.TRIP_TINT}; color: {t.TRIP_TEXT}; }}
    QLabel[badge="warning"] {{ background: {t.WARNING_BG}; color: {t.WARNING_TEXT}; }}
    QLabel[badge="neutral"] {{ background: {t.HAIRLINE}; color: {t.TEXT_MUTED}; }}
    QLabel[badge="trips"] {{ background: {t.TRIP}; color: {t.WHITE}; padding: 4px 10px; font-size: 12px; letter-spacing: 1px; }}
    QLabel[badge="rides"] {{ background: {t.BRAND}; color: {t.WHITE}; padding: 4px 10px; font-size: 12px; letter-spacing: 1px; }}

    /* --- controls ---------------------------------------------------------------------------- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t.SURFACE}; border: 1px solid {t.CONTROL_BORDER}; border-radius: {t.RADIUS_CONTROL}px;
        padding: 0 10px; min-height: {h}px; color: {t.TEXT}; selection-background-color: {t.BRAND_TINT};
        selection-color: {t.BRAND_DARK};
    }}
    QSpinBox, QDoubleSpinBox {{ font-family: "{t.FONT_MONO}", Consolas; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {t.BRAND}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        background: {t.SURFACE_SUBTLE}; color: {t.TEXT_MUTED}; }}
    QLineEdit:read-only {{ background: {t.SURFACE_SUBTLE}; }}
    QLineEdit[error="true"], QSpinBox[error="true"], QDoubleSpinBox[error="true"] {{ border: 1px solid {t.TRIP}; }}
    QLineEdit[mono="true"] {{ font-family: "{t.FONT_MONO}", Consolas; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER};
                                   selection-background-color: {t.BRAND_TINT}; selection-color: {t.BRAND_DARK}; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0px; height: 0px; border: none; }}
    QPlainTextEdit, QTextBrowser {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER};
                                    border-radius: {t.RADIUS_CONTROL}px; padding: 6px; }}
    QPlainTextEdit#monoText {{ font-family: "{t.FONT_MONO}", Consolas; font-size: 12px; background: {t.SURFACE_SUBTLE}; }}
    QListWidget, QTreeWidget, QTableWidget {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER};
                                             border-radius: {t.RADIUS_CONTROL}px; alternate-background-color: {t.SURFACE_SUBTLE}; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background: {t.SELECTED}; color: {t.TEXT}; }}
    QHeaderView::section {{ background: {t.SURFACE_SUBTLE}; color: {t.TEXT_MUTED}; padding: 6px 8px; font-weight: 600;
                            border: none; border-bottom: 1px solid {t.CARD_BORDER}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}

    QPushButton {{
        background: {t.BRAND}; border: 1px solid {t.BRAND}; border-radius: {t.RADIUS_CONTROL}px; color: {t.WHITE};
        padding: 0 16px; min-height: {h}px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {t.BRAND_DARK}; border-color: {t.BRAND_DARK}; }}
    QPushButton:pressed {{ background: {t.BRAND_DARK}; }}
    QPushButton:disabled {{ background: {t.BRAND_DISABLED}; border-color: {t.BRAND_DISABLED}; color: {t.WHITE}; }}
    QPushButton#secondaryButton, QPushButton#smallButton {{ background: {t.SURFACE}; color: {t.TEXT};
                                                          border: 1px solid {t.CONTROL_BORDER}; font-weight: 500; }}
    QPushButton#secondaryButton:hover, QPushButton#smallButton:hover {{ background: {t.SURFACE_SUBTLE}; border-color: {t.BRAND}; }}
    QPushButton#secondaryButton:disabled, QPushButton#smallButton:disabled {{ color: {t.NEUTRAL}; background: {t.SURFACE_SUBTLE};
                                                                            border-color: {t.HAIRLINE}; }}
    QPushButton#smallButton {{ min-height: {hs}px; padding: 0 10px; font-size: 12px; }}
    QPushButton#linkButton {{ background: transparent; border: none; color: {t.BRAND_TEXT}; padding: 0 2px;
                              min-height: 18px; text-decoration: underline; font-weight: 400; }}
    QPushButton#linkButton:hover {{ color: {t.BRAND_DARK}; background: transparent; }}
    QPushButton#linkButton:disabled {{ color: {t.NEUTRAL}; background: transparent; }}

    QWidget#segmented {{ background: {t.HAIRLINE}; border-radius: {t.RADIUS_CONTROL}px; }}
    QPushButton[segment="true"] {{ background: transparent; border: 1px solid transparent; color: {t.TEXT_MUTED};
                                   font-weight: 500; min-height: {hs}px; padding: 0 14px; }}
    QPushButton[segment="true"]:hover {{ color: {t.TEXT}; background: transparent; }}
    QPushButton[segment="true"]:checked {{ background: {t.SURFACE}; color: {t.BRAND_TEXT}; font-weight: 600;
                                           border: 1px solid {t.CARD_BORDER}; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.CARD_BORDER}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.BRAND}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.BRAND}; border: 2px solid {t.WHITE}; width: 14px; height: 14px;
                                  margin: -7px 0; border-radius: 9px; }}
    QProgressBar {{ background: {t.HAIRLINE}; border: none; border-radius: 3px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {t.BRAND}; border-radius: 3px; }}

    /* parameter rows */
    QPushButton#paramRow {{ background: transparent; border: none; border-bottom: 1px solid {t.HAIRLINE};
                            border-radius: 0; color: {t.TEXT}; text-align: left; padding: 0 6px; min-height: 44px;
                            font-weight: 400; }}
    QPushButton#paramRow:hover {{ background: {t.SURFACE_SUBTLE}; }}
    QPushButton#paramRow[edited="true"] {{ background: {t.EDITED_TINT}; color: {t.EDITED_TEXT}; font-weight: 600;
                                           border-radius: {t.RADIUS_CONTROL}px; border-bottom-color: transparent; }}
    QLabel[edited="true"] {{ color: {t.EDITED_TEXT}; font-weight: 600; }}
    #rowEditor {{ background: {t.SURFACE_SUBTLE}; border: 1px solid {t.HAIRLINE}; border-radius: {t.RADIUS_CONTROL}px; }}

    /* stepper */
    QPushButton#step {{ background: transparent; border: none; border-radius: {t.RADIUS_CONTROL}px; color: {t.TEXT_MUTED};
                        padding: 0 10px; min-height: 40px; font-weight: 500; text-align: left; }}
    QPushButton#step:hover {{ background: {t.SURFACE_SUBTLE}; }}
    QPushButton#step:checked {{ background: {t.BRAND_TINT}; color: {t.BRAND_DARK}; font-weight: 600; }}

    /* collapsible sections */
    #collapsibleHeader {{ background: transparent; border: none; border-bottom: 1px solid {t.HAIRLINE}; }}
    #collapsibleSubHeader {{ background: transparent; border: none; border-bottom: 1px solid {t.HAIRLINE}; }}
    QLabel#collapsibleHeaderLabel {{ font-weight: 600; }}
    QLabel#collapsibleSubHeaderLabel {{ color: {t.TEXT_MUTED}; font-weight: 600; }}
    QToolButton#collapsibleArrow {{ background: transparent; border: none; }}
    QGroupBox {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CARD}px;
                 margin-top: 20px; padding: 10px 8px 8px 8px; font-weight: 600; color: {t.BRAND_TEXT}; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; }}
    #advancedGroup {{ background: {t.SURFACE_SUBTLE}; }}

    /* documentation */
    QTreeWidget#docsTree {{ padding: 6px 4px; }}
    QTreeWidget#docsTree::item {{ padding: 4px 2px; }}
    QTreeWidget#docsTree::item:selected {{ background: {t.BRAND_TINT}; color: {t.BRAND_DARK}; }}
    QTextBrowser#docsBrowser {{ padding: 8px 12px; }}
    QLabel#docsTitle {{ color: {t.TEXT}; font-size: 15px; font-weight: 600; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t.CONTROL_BORDER}; border-radius: 5px; min-height: 24px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t.CONTROL_BORDER}; border-radius: 5px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QMessageBox {{ background: {t.SURFACE}; }}
    """


def apply_app_theme() -> None:
    app = QApplication.instance()
    families = load_fonts()
    app.setPalette(build_palette())
    if t.FONT_SANS in families:
        font = QFont(t.FONT_SANS)
        font.setPixelSize(t.SIZE_BODY)
        app.setFont(font)
    app.setStyleSheet(build_qss())


def repolish(widget) -> None:
    """Re-apply the stylesheet after a dynamic property the QSS keys on changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
