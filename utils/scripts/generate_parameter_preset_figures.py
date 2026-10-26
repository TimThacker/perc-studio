"""Generates the comparison SVGs embedded in docs/user/parameter_tiers.md.

Pure-stdlib SVG generation (no new project dependency), reusing the same
color palette as src/preview/style.py so the doc's charts stay visually
consistent with the app's own HTML report plots. These charts plot the
three *generic* internal tiers (Extended/Standard/Minimal) on a plain
voltage-duration grid with no reference curve - this app stopped comparing
against ITIC/CBEMA app-wide (see docs/user/presets/README.md); a prior revision of this script plotted
these tiers against an ITIC boundary line, which has been removed rather than
reintroduced under a different name.
"""
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from app.config import TVA_NAVY
from load_models.clod.cons import derive_clod_params
from presets.ridethrough import RIDE_THROUGH_PRESETS

OUT_DIR = os.path.join(REPO_ROOT, "docs", "user", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

GRID = "#e3e8ee"
AXIS_TEXT = "#5b6b7c"
TITLE_TEXT = "#22323f"

COLOR_TIER1 = "#1a7a3c"   # most tolerant tier (Extended / Robust)
COLOR_TIER2 = TVA_NAVY    # middle tier (Standard)
COLOR_TIER3 = "#c0392b"   # least tolerant tier (Minimal)


def _write(name, svg):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg.strip() + "\n")
    print("wrote", path)


# ---------------------------------------------------------------------------
# Chart 1: the three generic ride-through tier presets (IT + VFD), plain grid
# ---------------------------------------------------------------------------

def chart_ridethrough_tiers():
    W, H = 720, 366
    left, right, top, bottom = 78, 20, 72, 46
    chart_w = W - left - right
    chart_h = H - top - bottom
    tmin, tmax = 0.001, 100.0

    def xlog(t):
        t = min(max(t, tmin), tmax)
        return left + (math.log10(t) - math.log10(tmin)) / (math.log10(tmax) - math.log10(tmin)) * chart_w

    def y(v):
        return top + chart_h - (max(v, 0.0) / 1.0) * chart_h

    decade_ticks = [0.001, 0.01, 0.1, 1, 10, 100]
    decade_labels = ["1ms", "10ms", "100ms", "1s", "10s", "100s"]
    x_ticks = []
    for dt, dl in zip(decade_ticks, decade_labels):
        xt = xlog(dt)
        x_ticks.append(f'<line x1="{xt:.1f}" y1="{top}" x2="{xt:.1f}" y2="{top+chart_h}" stroke="{GRID}" stroke-width="1"/>')
        x_ticks.append(f'<text x="{xt:.1f}" y="{top+chart_h+16}" font-size="10" text-anchor="middle" fill="{AXIS_TEXT}">{dl}</text>')

    y_ticks = []
    for tv in (0.0, 0.25, 0.5, 0.75, 1.0):
        ty = y(tv)
        y_ticks.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{left+chart_w}" y2="{ty:.1f}" stroke="{GRID}" stroke-width="1"/>')
        y_ticks.append(f'<text x="{left-8}" y="{ty+3:.1f}" font-size="10" text-anchor="end" fill="{AXIS_TEXT}">{tv:.2f}</text>')

    # (label, preset id, block bundle, color, marker shape)
    series = [
        ("IT — Extended", "extended", "it_bundle", COLOR_TIER1, "circle"),
        ("IT — Standard", "standard_itic", "it_bundle", COLOR_TIER2, "circle"),
        ("IT — Minimal", "minimal", "it_bundle", COLOR_TIER3, "circle"),
        ("VFD — Robust", "extended", "vfd_bundle", COLOR_TIER1, "square"),
        ("VFD — Standard mfr.", "standard_itic", "vfd_bundle", COLOR_TIER2, "square"),
        ("VFD — Minimal", "minimal", "vfd_bundle", COLOR_TIER3, "square"),
    ]

    markers = []
    for label, preset_id, bundle, color, shape in series:
        p = getattr(RIDE_THROUGH_PRESETS[preset_id], bundle)
        cx, cy = xlog(p["DMA"]), y(p["VDPA"])
        if shape == "circle":
            markers.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{color}" stroke="white" stroke-width="1.5"/>')
        else:
            markers.append(f'<rect x="{cx-5.5:.1f}" y="{cy-5.5:.1f}" width="11" height="11" fill="{color}" stroke="white" stroke-width="1.5"/>')

    legend_rows = [
        (0, "circle", COLOR_TIER1, "IT/UPS — Extended"), (1, "square", COLOR_TIER1, "VFD — Robust"),
        (2, "circle", COLOR_TIER2, "IT/UPS — Standard"), (3, "square", COLOR_TIER2, "VFD — Standard mfr. default"),
        (4, "circle", COLOR_TIER3, "IT/UPS — Minimal/unknown"), (5, "square", COLOR_TIER3, "VFD — Minimal/unknown"),
    ]
    legend_items = []
    for i, shape, color, label in legend_rows:
        col = i % 2
        row = i // 2
        lx = left + col * 300
        ly = top - 30 + row * 14
        if shape == "circle":
            legend_items.append(f'<circle cx="{lx+5}" cy="{ly}" r="5" fill="{color}"/>')
        else:
            legend_items.append(f'<rect x="{lx}" y="{ly-5}" width="10" height="10" fill="{color}"/>')
        legend_items.append(f'<text x="{lx+14}" y="{ly+3}" font-size="10" fill="{TITLE_TEXT}">{label}</text>')

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,Segoe UI,Arial,sans-serif">
  <text x="{left}" y="18" font-size="13" font-weight="bold" fill="{TITLE_TEXT}">Generic ride-through tiers - trip point (VDPA, DMA)</text>
  {''.join(legend_items)}
  <rect x="{left}" y="{top}" width="{chart_w}" height="{chart_h}" fill="#ffffff" stroke="#c7d2de"/>
  {''.join(y_ticks)}
  {''.join(markers)}
  {''.join(x_ticks)}
  <text x="{left+chart_w/2:.1f}" y="{top+chart_h+34}" font-size="10.5" text-anchor="middle" fill="{AXIS_TEXT}">Trip delay — DMA / Tcease (log scale)</text>
  <text x="{left-56}" y="{top+chart_h/2:.1f}" font-size="10.5" fill="{AXIS_TEXT}" text-anchor="middle" transform="rotate(-90 {left-56} {top+chart_h/2:.1f})">Trip voltage — VDPA / Vcease (pu)</text>
</svg>"""
    _write("ridethrough_tiers.svg", svg)


# ---------------------------------------------------------------------------
# Chart 2: CLOD motor-facility archetype composition (stacked bars)
# ---------------------------------------------------------------------------

def chart_clod_composition():
    W, H = 820, 340
    left, right, top, bottom = 60, 280, 40, 60
    chart_w = W - left - right
    chart_h = H - top - bottom

    archetypes = [
        ("Modern", "Modern - large chillers, mostly VFD elsewhere, some fixed-speed backup", False),
        ("Mixed", "Mixed - moderate mix of large & small motors", False),
        ("Mixed\n+ lighting", "Mixed - moderate mix of large & small motors", True),
        ("Legacy", "Legacy - many small fixed-speed fan/pump motors, older CRAC units", False),
    ]
    fields = [
        ("PC_LM", "Large motors", "#1a5f8a"),
        ("PC_SM", "Small motors", "#4a90c4"),
        ("PC_TX", "Transformer exciting current", "#8ab6d6"),
        ("PC_DL", "Discharge lighting", "#f0ad4e"),
        ("PC_CP", "Constant power", "#c9622a"),
        ("REM", "Remainder (voltage-sensitive Z/I)", "#cfd6dd"),
    ]

    def y(v):
        return top + chart_h - (v / 100.0) * chart_h

    y_ticks = []
    for tv in (0, 20, 40, 60, 80, 100):
        ty = y(tv)
        y_ticks.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{left+chart_w}" y2="{ty:.1f}" stroke="{GRID}" stroke-width="1"/>')
        y_ticks.append(f'<text x="{left-8}" y="{ty+3:.1f}" font-size="10" text-anchor="end" fill="{AXIS_TEXT}">{tv}%</text>')

    n = len(archetypes)
    group_w = chart_w / n
    bar_w = 64
    bars = []
    labels = []
    for i, (label, key, lighting) in enumerate(archetypes):
        p = dict(derive_clod_params(key, lighting))
        p["REM"] = 100.0 - sum(p.values())
        cx = left + i * group_w + group_w / 2
        x1 = cx - bar_w / 2
        cum = 0.0
        for fname, flabel, color in fields:
            v = p[fname]
            y0, y1v = y(cum), y(cum + v)
            bars.append(f'<rect x="{x1:.1f}" y="{y1v:.1f}" width="{bar_w}" height="{(y0-y1v):.1f}" fill="{color}"/>')
            if v >= 6:
                bars.append(f'<text x="{cx:.1f}" y="{(y0+y1v)/2+3:.1f}" font-size="9" text-anchor="middle" fill="white">{v:.0f}%</text>')
            cum += v
        for li, line in enumerate(label.split("\n")):
            labels.append(f'<text x="{cx:.1f}" y="{top+chart_h+18+li*12}" font-size="10" text-anchor="middle" fill="{AXIS_TEXT}">{line}</text>')

    legend_items = []
    lx, ly0 = left + chart_w + 24, top + 6
    for i, (fname, flabel, color) in enumerate(fields):
        ly = ly0 + i * 20
        legend_items.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="{color}"/>')
        legend_items.append(f'<text x="{lx+16}" y="{ly}" font-size="10" fill="{TITLE_TEXT}">{flabel}</text>')

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,Segoe UI,Arial,sans-serif">
  <text x="{left}" y="18" font-size="13" font-weight="bold" fill="{TITLE_TEXT}">CLOD cooling-motor composition by facility archetype</text>
  <rect x="{left}" y="{top}" width="{chart_w}" height="{chart_h}" fill="#ffffff" stroke="#c7d2de"/>
  {''.join(y_ticks)}
  {''.join(bars)}
  {''.join(labels)}
  {''.join(legend_items)}
</svg>"""
    _write("clod_composition.svg", svg)


if __name__ == "__main__":
    chart_ridethrough_tiers()
    chart_clod_composition()
