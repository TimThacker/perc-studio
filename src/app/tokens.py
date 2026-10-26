"""Design tokens: the one place the app's colours, sizes and fonts are defined.

Qt-free, so the stylesheet (`ui.theme.build_qss`), the chart pages (`preview.style`,
`preview.standard`, `blackbox`) and the tests all read the same values. They come
from the redesign's style tile: brand green for primary actions, partner blue for
voltage and frequency, red for trips, orange for power.
"""

from __future__ import annotations

# --- colour ---------------------------------------------------------------------------------------

BRAND = "#007800"  # primary buttons, active tab underline, focus
BRAND_DARK = "#004A00"  # hover, text on tint
BRAND_TEXT = "#006400"  # section labels, active tab text, links
BRAND_TINT = "#E6F2E6"  # selected, badges, focus ring fill
BRAND_DISABLED = "#80BB80"  # a primary button at 45 % opacity over white

PARTNER_BLUE = "#164A7E"  # voltage/frequency trace, model line, run tab
PARTNER_TINT = "#E4ECF5"

TRIP = "#B42318"  # errors, trip, TRIPS badge
TRIP_TEXT = "#912018"  # text on the trip tint
TRIP_TINT = "#FBE4E1"  # fails badge, trip-permitted region
TRIP_BANNER = "#FFF8F7"
TRIP_BANNER_BORDER = "#F1C4BE"

RIDE_BANNER = "#F2F8F2"
RIDE_BANNER_BORDER = "#BFE0BF"

POWER = "#C2410C"  # active power trace

TEXT = "#16211B"
TEXT_MUTED = "#4A574F"
CONTROL_BORDER = "#CBD5CF"
CARD_BORDER = "#DCE3DF"
HAIRLINE = "#EEF2EF"
GROUND = "#F3F5F4"
SURFACE = "#FFFFFF"
SURFACE_SUBTLE = "#FAFBFA"

EDITED_TINT = "#EAF1F9"
EDITED_BORDER = "#9DB8D6"
EDITED_TEXT = "#123E6B"
SELECTED = "#EEF4FA"

WARNING_BG = "#FDEBD8"
WARNING_TEXT = "#9A3412"

STATE_ONLINE = "#BFE0BF"
STATE_CEASED = "#F2B8B0"
STATE_RECONNECTING = "#FBE3CC"

NO_DAMAGE = "#E3F1E3"
DEADBAND = "#E4ECF5"

MODEL_REGION = "#DCE7F3"
MODEL_OUTLINE = "#164A7E"
SHORTFALL = "#E8857D"
SHORTFALL_HATCH = "#B42318"

WHITE = "#FFFFFF"
NEUTRAL = "#9AA8A0"  # axes, pending dots, "other" load
RECONNECT = "#1E7B34"  # reconnect thresholds and windows (green, distinct from brand fill)

# The facility's load split: IT, VFD, CLOD motors, other.
SPLIT_COLORS = (BRAND, PARTNER_BLUE, POWER, NEUTRAL)

# --- type -----------------------------------------------------------------------------------------

FONT_SANS = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"
# What the chart pages ask the browser for: the bundled face first, then the system's.
CSS_FONT_SANS = "'IBM Plex Sans', 'Segoe UI', Arial, sans-serif"
CSS_FONT_MONO = "'IBM Plex Mono', Consolas, 'Courier New', monospace"

SIZE_EMPTY_TITLE = 20
SIZE_PANEL_TITLE = 16
SIZE_BODY = 13
SIZE_SECTION_LABEL = 11
SIZE_SMALL = 12

# --- shape and spacing ----------------------------------------------------------------------------

RADIUS_CARD = 8
RADIUS_CONTROL = 6
RADIUS_TAG = 4
GUTTER = 16
FIELD_GAP = 10
SECTION_GAP = 18
APP_BAR_HEIGHT = 56
FOOTER_MIN_HEIGHT = 44
CONTROL_HEIGHT = 34
CONTROL_HEIGHT_SMALL = 26
LEFT_PANEL_MIN = 360
LEFT_PANEL_MAX = 440

# --- chart aliases ---------------------------------------------------------------------------------

PLOT_VOLTAGE = PARTNER_BLUE
PLOT_POWER = POWER
PLOT_TRIP = TRIP
PLOT_RECONNECT = RECONNECT
PLOT_GRID = HAIRLINE
PLOT_AXIS_TEXT = TEXT_MUTED
PLOT_TITLE_TEXT = TEXT


def colors() -> dict[str, str]:
    """Every colour token by name (for the tests and the style gallery)."""
    return {name: value for name, value in globals().items()
            if name.isupper() and isinstance(value, str) and value.startswith("#")}


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"not a #rrggbb colour: {color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgba(color: str, alpha: float) -> str:
    r, g, b = hex_to_rgb(color)
    return f"rgba({r},{g},{b},{alpha:g})"


def relative_luminance(color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2 contrast ratio between two colours (1 to 21)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
