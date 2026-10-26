"""Generates two figures per preset in ``src/presets/ridethrough.py``, for
embedding in ``docs/user/presets/*.md``:

- ``envelope_<id>.svg`` - the preset's voltage ride-through envelope with
  every exported trip stage (all 4 per direction; stages that share a point
  are labeled together, e.g. "1-4").
- ``frequency_<id>.svg`` - the preset's frequency ride-through table where it
  publishes one, and the block's frequency deadband: PERC1 has one trip point
  per direction (FUFTP1/TUFTP1, FOFTP1/TOFTP1), so its frequency behavior is a
  band it rides through indefinitely, tripping once outside it for the delay.

Pure-stdlib SVG generation (no new project dependency, no browser/kaleido
needed for a static export). Reuses the same geometry helpers and axis
scaling as the live app's tolerance maps (``src/preview/perc1_dll.py``), so a chart
here looks like a static snapshot of those panels. Values come from the
preset's IT bundle - exactly what the app exports - never recomputed. See
``docs/user/presets/README.md`` for why these charts are linear-time,
single-preset, and never compare against ITIC/CBEMA.
"""
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from load_models.perc1_dll.simulation import (
    OVERVOLTAGE_STAGE_CONS,
    UNDERVOLTAGE_STAGE_CONS,
)
from presets.envelope import (
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
    segments_to_points,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS

OUT_DIR = os.path.join(REPO_ROOT, "docs", "user", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

GRID = "#e3e8ee"
AXIS_TEXT = "#5b6b7c"
TITLE_TEXT = "#22323f"
BOUNDARY_LINE = "#3a4552"
TRIP_COLOR = "#c0392b"
OK_COLOR = "#1a7a3c"
DEADBAND_COLOR = "#1558b0"
NEUTRAL_MARKER = "#22323f"
# fill + fill-opacity as two separate attributes, not a single rgba(...) fill
# value - QtSvg (used to rasterize these in the app's Documentation tab) and
# some strict SVG 1.1 renderers don't parse CSS rgba() in `fill` and fall back
# to opaque black.
TRIP_FILL_OPACITY = "0.18"
OK_FILL_OPACITY = "0.14"
FONT = "-apple-system,Segoe UI,Arial,sans-serif"

W, H = 720, 380
LEFT, RIGHT, TOP, BOTTOM = 66, 20, 48, 52
CHART_W = W - LEFT - RIGHT
CHART_H = H - TOP - BOTTOM


def _write(name, svg):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg.strip() + "\n")
    print("wrote", path)


class _Axes:
    """Linear data -> pixel mapping for one chart."""

    def __init__(self, xmax, ylo, yhi):
        self.xmax, self.ylo, self.yhi = xmax, ylo, yhi

    def x(self, t):
        return LEFT + (min(max(t, 0.0), self.xmax) / self.xmax) * CHART_W

    def y(self, v):
        v = min(max(v, self.ylo), self.yhi)
        return TOP + CHART_H - ((v - self.ylo) / (self.yhi - self.ylo)) * CHART_H

    def poly(self, points):
        return " ".join(f"{self.x(t):.1f},{self.y(v):.1f}" for t, v in points)


def _ticks(ax, y_values, y_format, x_unit="s"):
    parts = []
    for i in range(7):
        tv = ax.xmax * i / 6
        xt = ax.x(tv)
        label = f"{tv:.2f}{x_unit}" if ax.xmax < 20 else f"{tv:.0f}{x_unit}"
        parts.append(f'<line x1="{xt:.1f}" y1="{TOP}" x2="{xt:.1f}" y2="{TOP + CHART_H}" stroke="{GRID}"/>')
        parts.append(f'<text x="{xt:.1f}" y="{TOP + CHART_H + 16}" font-size="10" text-anchor="middle" '
                     f'fill="{AXIS_TEXT}">{label}</text>')
    for tv in y_values:
        if not ax.ylo <= tv <= ax.yhi:
            continue
        ty = ax.y(tv)
        parts.append(f'<line x1="{LEFT}" y1="{ty:.1f}" x2="{LEFT + CHART_W}" y2="{ty:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{ty + 3:.1f}" font-size="10" text-anchor="end" '
                     f'fill="{AXIS_TEXT}">{y_format(tv)}</text>')
    return "".join(parts)


def _frame(title, body, x_title, y_title):
    return f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>
  <text x="{LEFT}" y="20" font-size="13" font-weight="bold" fill="{TITLE_TEXT}">{title}</text>
  <rect x="{LEFT}" y="{TOP}" width="{CHART_W}" height="{CHART_H}" fill="#ffffff" stroke="#c7d2de"/>
  {body}
  <text x="{LEFT + CHART_W / 2:.1f}" y="{TOP + CHART_H + 36}" font-size="10.5" text-anchor="middle" fill="{AXIS_TEXT}">{x_title}</text>
  <text x="{LEFT - 50}" y="{TOP + CHART_H / 2:.1f}" font-size="10.5" fill="{AXIS_TEXT}" text-anchor="middle" transform="rotate(-90 {LEFT - 50} {TOP + CHART_H / 2:.1f})">{y_title}</text>
</svg>"""


def _stage_label(numbers):
    """[1, 2, 3, 4] -> "1-4", [2, 3] -> "2-3", [1] -> "1", [1, 3] -> "1, 3"."""
    if len(numbers) > 1 and numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"{numbers[0]}-{numbers[-1]}"
    return ", ".join(str(n) for n in numbers)


def _stage_markers(ax, bundle, stage_cons, shape, label_dy):
    """One marker per distinct (delay, voltage) point, labeled with every
    stage number exported at that point."""
    points = defaultdict(list)
    for number, (v_name, d_name) in enumerate(stage_cons, start=1):
        points[(bundle[d_name], bundle[v_name])].append(number)
    parts = []
    for (d, v), numbers in points.items():
        cx, cy = ax.x(d), ax.y(v)
        if shape == "circle":
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6.5" fill="{TRIP_COLOR}" stroke="white" stroke-width="1.5"/>')
        else:
            parts.append(f'<rect x="{cx - 5.5:.1f}" y="{cy - 5.5:.1f}" width="11" height="11" fill="{TRIP_COLOR}" '
                         f'stroke="white" stroke-width="1.5" transform="rotate(45 {cx:.1f} {cy:.1f})"/>')
        parts.append(f'<text x="{cx + 9:.1f}" y="{cy + label_dy:.1f}" font-size="10" font-weight="bold" '
                     f'fill="{TITLE_TEXT}">{_stage_label(numbers)}</text>')
    return "".join(parts)


def chart_voltage_envelope(preset):
    bundle = preset.it_bundle
    under_points = segments_to_points(envelope_segments_from_steps(preset.envelope))
    over_points = segments_to_points(overvoltage_segments_from_steps(preset.overvoltage_envelope))

    durations = [bundle[d] for _, d in UNDERVOLTAGE_STAGE_CONS + OVERVOLTAGE_STAGE_CONS]
    durations += [s.min_duration_s for s in preset.envelope + preset.overvoltage_envelope if s.min_duration_s]
    over_voltages = [bundle[v] for v, _ in OVERVOLTAGE_STAGE_CONS]
    ax = _Axes(max(2.5, max(durations) * 1.25), 0.0,
               max(1.4, max(v for _, v in over_points) + 0.25, max(over_voltages) + 0.25))

    body = [
        (
            f'<polygon points="{ax.x(0):.1f},{ax.y(0):.1f} {ax.poly(under_points)} {ax.x(ax.xmax):.1f},{ax.y(0):.1f}" '
            f'fill="{TRIP_COLOR}" fill-opacity="{TRIP_FILL_OPACITY}"/>'
        ),
        (
            f'<polygon points="{ax.poly(under_points)} {ax.poly(list(reversed(over_points)))}" '
            f'fill="{OK_COLOR}" fill-opacity="{OK_FILL_OPACITY}"/>'
        ),
        (
            f'<polygon points="{ax.x(0):.1f},{ax.y(ax.yhi):.1f} {ax.poly(over_points)} {ax.x(ax.xmax):.1f},{ax.y(ax.yhi):.1f}" '
            f'fill="{TRIP_COLOR}" fill-opacity="{TRIP_FILL_OPACITY}"/>'
        ),
        _ticks(ax, [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0], lambda v: f"{v:.2f}"),
        f'<polyline points="{ax.poly(under_points)}" fill="none" stroke="{BOUNDARY_LINE}" stroke-width="2.2"/>',
        f'<polyline points="{ax.poly(over_points)}" fill="none" stroke="{BOUNDARY_LINE}" stroke-width="2.2"/>',
        _stage_markers(ax, bundle, UNDERVOLTAGE_STAGE_CONS, "circle", 14),
        _stage_markers(ax, bundle, OVERVOLTAGE_STAGE_CONS, "diamond", -7),
        f'<text x="{LEFT + 10}" y="{TOP + 16}" font-size="10" fill="{TRIP_COLOR}" font-weight="bold">Trip permitted (overvoltage)</text>',
        f'<text x="{LEFT + 10}" y="{TOP + CHART_H * 0.55:.1f}" font-size="10" fill="{OK_COLOR}" font-weight="bold">Must ride through</text>',
        f'<text x="{LEFT + 10}" y="{TOP + CHART_H - 8}" font-size="10" fill="{TRIP_COLOR}" font-weight="bold">Trip permitted (undervoltage)</text>',
        (
            f'<text x="{LEFT + CHART_W - 8:.1f}" y="{TOP + 16}" font-size="9.5" text-anchor="end" fill="{TITLE_TEXT}">'
            '● undervoltage / ◆ overvoltage trip stages (numbers = stage), as exported</text>'
        ),
    ]
    return _frame(f"{preset.label} - voltage ride-through",
                  "".join(body), "Duration (s) - linear, auto-scaled to this preset's breakpoints", "Voltage (pu)")


def chart_frequency(preset):
    """The preset's frequency table (if it publishes one) and the block's
    deadband: rides through indefinitely between FUFTP1 and FOFTP1, trips
    once below/above it for TUFTP1/TOFTP1."""
    bundle, table = preset.it_bundle, preset.frequency_ride_through
    low_hz, low_delay = bundle["FUFTP1"], bundle["TUFTP1"]
    high_hz, high_delay = bundle["FOFTP1"], bundle["TOFTP1"]

    durations = [low_delay, high_delay]
    levels = [low_hz, high_hz]
    if table:
        durations += [b.min_duration_s for b in table.underfrequency + table.overfrequency]
        levels += [b.limit_hz for b in table.underfrequency + table.overfrequency]
    ax = _Axes(max(450.0, max(durations) * 1.25), min([56.0] + [f - 1.0 for f in levels]),
               max([64.0] + [f + 1.0 for f in levels]))

    body = []
    if table:
        floor = segments_to_points(table.segments("under", ax.xmax))
        ceiling = segments_to_points(table.segments("over", ax.xmax))
        body += [
            (
                f'<polygon points="{ax.x(0):.1f},{ax.y(ax.ylo):.1f} {ax.poly(floor)} {ax.x(ax.xmax):.1f},{ax.y(ax.ylo):.1f}" '
                f'fill="{TRIP_COLOR}" fill-opacity="{TRIP_FILL_OPACITY}"/>'
            ),
            f'<polygon points="{ax.poly(floor)} {ax.poly(list(reversed(ceiling)))}" fill="{OK_COLOR}" fill-opacity="{OK_FILL_OPACITY}"/>',
            (
                f'<polygon points="{ax.x(0):.1f},{ax.y(ax.yhi):.1f} {ax.poly(ceiling)} {ax.x(ax.xmax):.1f},{ax.y(ax.yhi):.1f}" '
                f'fill="{TRIP_COLOR}" fill-opacity="{TRIP_FILL_OPACITY}"/>'
            ),
        ]
    body.append(_ticks(ax, list(range(int(ax.ylo), int(ax.yhi) + 1)), lambda v: f"{v:.0f}"))
    if table:
        body += [
            f'<polyline points="{ax.poly(floor)}" fill="none" stroke="{BOUNDARY_LINE}" stroke-width="2.2"/>',
            f'<polyline points="{ax.poly(ceiling)}" fill="none" stroke="{BOUNDARY_LINE}" stroke-width="2.2"/>',
            f'<text x="{LEFT + 10}" y="{TOP + 16}" font-size="10" fill="{TRIP_COLOR}" font-weight="bold">Trip permitted (over-frequency)</text>',
            f'<text x="{LEFT + 10}" y="{TOP + CHART_H - 8}" font-size="10" fill="{TRIP_COLOR}" font-weight="bold">Trip permitted (under-frequency)</text>',
        ]
    else:
        body.append(f'<text x="{LEFT + 10}" y="{TOP + 16}" font-size="10" fill="{AXIS_TEXT}">'
                    f'{preset.label} publishes no frequency ride-through table - vendor-typical settings shown</text>')

    # The block's deadband: shaded band between the two trip frequencies, with
    # the trip region beyond each edge marked from its delay onward.
    y_low, y_high = ax.y(low_hz), ax.y(high_hz)
    body += [
        (
            f'<rect x="{LEFT}" y="{y_high:.1f}" width="{CHART_W}" height="{y_low - y_high:.1f}" '
            f'fill="{DEADBAND_COLOR}" fill-opacity="0.07"/>'
        ),
        (
            f'<polyline points="{ax.x(low_delay):.1f},{ax.y(ax.ylo):.1f} {ax.x(low_delay):.1f},{y_low:.1f} '
            f'{ax.x(ax.xmax):.1f},{y_low:.1f}" fill="none" stroke="{DEADBAND_COLOR}" stroke-width="1.8" stroke-dasharray="6 4"/>'
        ),
        (
            f'<polyline points="{ax.x(high_delay):.1f},{ax.y(ax.yhi):.1f} {ax.x(high_delay):.1f},{y_high:.1f} '
            f'{ax.x(ax.xmax):.1f},{y_high:.1f}" fill="none" stroke="{DEADBAND_COLOR}" stroke-width="1.8" stroke-dasharray="6 4"/>'
        ),
        f'<circle cx="{ax.x(low_delay):.1f}" cy="{y_low:.1f}" r="6.5" fill="{DEADBAND_COLOR}" stroke="white" stroke-width="1.5"/>',
        (
            f'<rect x="{ax.x(high_delay) - 5.5:.1f}" y="{y_high - 5.5:.1f}" width="11" height="11" fill="{DEADBAND_COLOR}" '
            f'stroke="white" stroke-width="1.5" transform="rotate(45 {ax.x(high_delay):.1f} {y_high:.1f})"/>'
        ),
        (
            f'<text x="{LEFT + CHART_W - 8:.1f}" y="{(y_low + y_high) / 2 + 4:.1f}" font-size="10.5" font-weight="bold" '
            f'text-anchor="end" fill="{DEADBAND_COLOR}">Block deadband {low_hz:.2f}-{high_hz:.2f} Hz</text>'
        ),
        (
            f'<text x="{LEFT + CHART_W - 8:.1f}" y="{y_low + 15:.1f}" font-size="9.5" text-anchor="end" '
            f'fill="{DEADBAND_COLOR}">trips below {low_hz:.2f} Hz after {low_delay:g} s (FUFTP1/TUFTP1)</text>'
        ),
        (
            f'<text x="{LEFT + CHART_W - 8:.1f}" y="{y_high - 7:.1f}" font-size="9.5" text-anchor="end" '
            f'fill="{DEADBAND_COLOR}">trips above {high_hz:.2f} Hz after {high_delay:g} s (FOFTP1/TOFTP1)</text>'
        ),
    ]
    return _frame(f"{preset.label} - frequency ride-through", "".join(body),
                  "Duration (s) - linear", "Frequency (Hz)")


if __name__ == "__main__":
    for preset_id, preset in RIDE_THROUGH_PRESETS.items():
        _write(f"envelope_{preset_id}.svg", chart_voltage_envelope(preset))
        _write(f"frequency_{preset_id}.svg", chart_frequency(preset))
