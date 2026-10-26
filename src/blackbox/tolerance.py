"""The tolerance curve: how long the model rides through each voltage and frequency, drawn from a
run's measured boundaries, with an optional standard laid over it.

Qt-free. Everything comes from one `validation.json` document:

* **Measured.** For each tested value (a sag depth, a swell level, a held frequency) the
  boundary search gives a bracket: the longest event seen riding through and the shortest
  seen tripping. The curve is stepped and never interpolated: a *band* runs from one
  tested value to the next and uses the boundary measured at its end farther from nominal
  (for undervoltage, its lower voltage), which is the harder of the two.
* **Required.** A standard's ride-through requirement at each value
  (`scoring.required_duration`; infinite means "never trip"). Frequency has none when the
  standard publishes no frequency table, and the curve says so instead of drawing one.
* **Short of the standard.** Within a band, wherever the standard requires ride-through
  longer than the model was seen to trip (the same rule as the comparison's "fails").

The overlay needs no new simulation: the standard is a curve and the model's curve is measured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import plotly.graph_objects as go

from app import tokens as t

from .scoring import required_duration

NOMINAL = {"undervoltage": 1.0, "overvoltage": 1.0, "frequency": 60.0}
UNITS = {"undervoltage": "pu", "overvoltage": "pu", "frequency": "Hz"}
X_MIN = {"voltage": 0.01, "frequency": 0.1}


@dataclass(frozen=True)
class Band:
    kind: str  # undervoltage | overvoltage | frequency
    lo: float  # the band's value range
    hi: float
    tag: float  # the tested value whose boundary the band uses
    longest_ok_s: float | None  # the longest event seen riding through at `tag`
    shortest_trip_s: float | None  # the shortest seen tripping (None: rode through everything run)
    tested_max_s: float

    @property
    def rides_all(self) -> bool:
        return self.shortest_trip_s is None

    @property
    def ride_through_s(self) -> float:
        """How far right the model's region reaches: the longest ride-through seen (the tested maximum when it
        never tripped)."""
        if self.rides_all:
            return self.tested_max_s
        return self.longest_ok_s or 0.0


@dataclass(frozen=True)
class Requirement:
    kind: str
    lo: float
    hi: float
    required_s: float  # inf: must never trip


@dataclass(frozen=True)
class Shortfall:
    kind: str
    lo: float
    hi: float
    model_s: float  # how long the model rode through (or tripped after) in the band
    required_s: float
    tripped_after_s: float

    def label(self) -> str:
        if math.isinf(self.required_s):
            return f"trips after {self.tripped_after_s:.3g} s"
        return f"{self.model_s:.2g} s vs {self.required_s:.2g} s"


def _searches(doc: dict, kind: str) -> list[dict]:
    fam = doc.get("families", {}).get(kind) or {}
    return sorted(fam.get("searches", []), key=lambda s: s["tag"])


def _tested_max(doc: dict, kind: str) -> float:
    fam = doc.get("families", {}).get(kind) or {}
    return float(fam.get("inner", {}).get("hi") or max((d for s in _searches(doc, kind) for d, _ in s["points"]),
                                                       default=1.0))


def _bracket(search: dict) -> tuple[float | None, float | None]:
    trips = [d for d, rode in search["points"] if not rode]
    first_trip = min(trips) if trips else None
    oks = [d for d, rode in search["points"] if rode and (first_trip is None or d < first_trip)]
    return (max(oks) if oks else None), first_trip


def measured_boundary(doc: dict, kind: str) -> list[Band]:
    """The stepped measured boundary of one family, as bands from the most severe tested value towards nominal.
    Undervoltage/under-frequency bands run up from each tested value to the next (the last to nominal);
    overvoltage/over-frequency bands run down from each tested value to the previous (the first from nominal)."""
    nominal = NOMINAL[kind]
    tested_max = _tested_max(doc, kind)
    bands = []
    searches = _searches(doc, kind)
    below = [s for s in searches if s["tag"] < nominal]
    above = [s for s in searches if s["tag"] > nominal]
    for i, s in enumerate(below):
        hi = below[i + 1]["tag"] if i + 1 < len(below) else nominal
        ok, trip = _bracket(s)
        bands.append(Band(kind, s["tag"], hi, s["tag"], ok, trip, tested_max))
    for i, s in enumerate(above):
        lo = above[i - 1]["tag"] if i else nominal
        ok, trip = _bracket(s)
        bands.append(Band(kind, lo, s["tag"], s["tag"], ok, trip, tested_max))
    return bands


def tested_range(doc: dict, kind: str) -> tuple[float, float] | None:
    tags = [s["tag"] for s in _searches(doc, kind)]
    return (min(tags), max(tags)) if tags else None


def has_table(preset, kind: str) -> bool:
    return kind != "frequency" or preset.frequency_ride_through is not None


def required_boundary(preset, kind: str, band: Band) -> list[Requirement] | None:
    """The preset's requirement across one band, split where the requirement changes. None for frequency when the
    preset has no frequency table."""
    if not has_table(preset, kind):
        return None
    breaks = {band.lo, band.hi}
    if kind == "undervoltage":
        breaks |= {s.voltage_pu for s in preset.envelope}
    elif kind == "overvoltage":
        breaks |= {s.voltage_pu for s in preset.overvoltage_envelope}
    else:
        table = preset.frequency_ride_through
        breaks |= {table.continuous_low_hz, table.continuous_high_hz}
        breaks |= {b.limit_hz for b in (*table.underfrequency, *table.overfrequency)}
    edges = sorted(v for v in breaks if band.lo <= v <= band.hi)
    out = []
    for a, b in pairwise(edges):
        if b - a < 1e-9:
            continue
        # No breakpoint lies inside a piece, so the requirement there is the one at its midpoint.
        out.append(Requirement(kind, a, b, required_duration(preset, kind, (a + b) / 2)))
    return out


def shortfalls(bands: list[Band], preset) -> list[Shortfall]:
    """Where the preset requires ride-through for longer than the model was seen to trip: within each band, the
    pieces whose requirement exceeds the band's shortest trip."""
    out: list[Shortfall] = []
    for band in bands:
        if band.rides_all:
            continue
        for req in required_boundary(preset, band.kind, band) or []:
            if req.required_s > band.shortest_trip_s + 1e-9:
                if out and out[-1].kind == band.kind and abs(out[-1].hi - req.lo) < 1e-9 and \
                        out[-1].required_s == req.required_s and out[-1].tripped_after_s == band.shortest_trip_s:
                    prev = out.pop()
                    out.append(Shortfall(band.kind, prev.lo, req.hi, prev.model_s, prev.required_s, prev.tripped_after_s))
                    continue
                out.append(Shortfall(band.kind, req.lo, req.hi, band.ride_through_s, req.required_s,
                                     band.shortest_trip_s))
    return out


# --- caption -------------------------------------------------------------------------------------------------

_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def stage_voltages(doc: dict) -> list[float]:
    """The trip-stage voltages of the run's model when it is a PERC1 record (read from the placed record); else []."""
    records = doc.get("stages", {}).get("intake", {}).get("placed_records") or []
    try:
        from editor.dyr_import import import_record
    except ImportError:  # pragma: no cover
        return []
    values = set()
    for text in records:
        try:
            rec = import_record(text.replace("{BUS}", "1"))
        except (ValueError, KeyError, IndexError):
            continue
        cons = rec.cons
        for name in ("VDPA", "VDPA1", "VDPA2", "VDPA3", "Vcease", "VDUA", "VDUA1", "VDUA2", "VDUA3"):
            if name in cons:
                values.add(round(float(cons[name]), 4))
    return sorted(values)


def caption(doc: dict, preset, falls: list[Shortfall]) -> str:
    """One generated sentence (or a few) about where the model falls short of the preset, never fixed text."""
    if preset is None:
        return "Choose a standard to overlay. Wherever it requires ride-through and the model trips is marked in red."
    parts = []
    by_kind = {k: [f for f in falls if f.kind == k] for k in ("undervoltage", "overvoltage", "frequency")}
    for kind, items in by_kind.items():
        if not items:
            continue
        n = len(items)
        count = _NUMBER_WORDS.get(n, str(n))
        starts = [f.lo if kind == "undervoltage" or (kind == "frequency" and f.hi <= NOMINAL[kind]) else f.hi
                  for f in items]
        unit = UNITS[kind]
        sentence = f"Short of {preset.label} at {count} {kind} band{'s' if n > 1 else ''}"
        stages = stage_voltages(doc) if kind != "frequency" else []
        on_stage = [v for v in starts if any(abs(v - s) < 1e-6 for s in stages)]
        listed = ", ".join(f"{v:g}" for v in starts)
        if stages and len(on_stage) == n:
            sentence += (f", {'each starting' if n > 1 else 'starting'} at one of the model's own stage voltages "
                         f"({listed} {unit}), where the test holds the sag just below the threshold")
        else:
            sentence += f" ({', '.join(f'{f.lo:g}–{f.hi:g}' for f in items)} {unit})"
        parts.append(sentence + ".")
    if by_kind["undervoltage"]:
        parts.append("Each band uses the boundary measured at its lower voltage.")
    met = [k for k in ("undervoltage", "overvoltage", "frequency")
           if not by_kind[k] and doc.get("families", {}).get(k, {}).get("searches") and has_table(preset, k)]
    if met:
        names = [k.capitalize() if i == 0 else k for i, k in enumerate(met)]
        parts.append(f"{' and '.join(names)} {'meets' if len(met) == 1 else 'meet'} it.")
    if not any(by_kind.values()):
        parts.insert(0, f"The model rides through everything {preset.label} requires in the tested range.")
    parts.append("The overlay needs no re-run.")
    return " ".join(parts)


def frequency_note(preset) -> str | None:
    if preset is not None and preset.frequency_ride_through is None:
        return f"{preset.label} has no frequency table in this app, so there is nothing to overlay here."
    return None


def overlay_presets(presets) -> list:
    """The presets that can be laid over a run: those with data for at least one quantity (every preset has a
    voltage envelope)."""
    return [p for p in presets if p.envelope or p.overvoltage_envelope or p.frequency_ride_through is not None]


# --- figures ---------------------------------------------------------------------------------------------------


def _quantity_kinds(quantity: str) -> tuple[str, ...]:
    return ("undervoltage", "overvoltage") if quantity == "voltage" else ("frequency",)


def tolerance_figure(doc: dict, quantity: str, preset=None) -> go.Figure:
    """The model's ride-through region for "voltage" or "frequency" (duration on a log axis, value up), with the
    preset's requirement dashed and the shortfalls hatched red when a preset is given."""
    kinds = _quantity_kinds(quantity)
    bands = [b for k in kinds for b in measured_boundary(doc, k)]
    fig = go.Figure()
    x_min = X_MIN[quantity]
    x_max = max([b.tested_max_s for b in bands] + [1.0])
    if not bands:
        fig.add_annotation(text="Not tested in this run", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                           font={"color": t.TEXT_MUTED})
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return _layout(fig, quantity, x_min, x_max)

    # The model's region: one rectangle per band, filled as one trace.
    xs, ys = [], []
    for b in bands:
        right = max(b.ride_through_s, x_min)
        xs += [x_min, right, right, x_min, x_min, None]
        ys += [b.lo, b.lo, b.hi, b.hi, b.lo, None]
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor=t.MODEL_REGION, mode="lines",
                             line={"width": 0}, name="Model rides through (measured)", hoverinfo="skip"))
    # The measured boundary: the stepped right-hand edge of the region, one line per side of nominal.
    for kind in kinds:
        ordered = sorted((b for b in bands if b.kind == kind), key=lambda b: b.lo)
        for side in (ordered[: sum(1 for b in ordered if b.hi <= NOMINAL[kind])],
                     ordered[sum(1 for b in ordered if b.hi <= NOMINAL[kind]):]):
            ex, ey = [], []
            for b in side:
                right = max(b.ride_through_s, x_min)
                ex += [right, right]
                ey += [b.lo, b.hi]
            if ex:
                fig.add_trace(go.Scatter(x=[x_min, *ex, x_min], y=[ey[0], *ey, ey[-1]], mode="lines",
                                         line={"color": t.MODEL_OUTLINE, "width": 1.4}, hoverinfo="skip",
                                         showlegend=False))
    hover_x = [b.ride_through_s for b in bands]
    hover_y = [(b.lo + b.hi) / 2 for b in bands]
    hover_text = [(f"{b.lo:g}–{b.hi:g} {UNITS[b.kind]}: " + ("rides through the whole tested range" if b.rides_all
                   else f"rides through {b.longest_ok_s or 0:.3g} s, trips by {b.shortest_trip_s:.3g} s"))
                  for b in bands]
    fig.add_trace(go.Scatter(x=hover_x, y=hover_y, mode="markers", marker={"size": 6, "color": t.MODEL_OUTLINE,
                                                                           "opacity": 0.0},
                             hovertext=hover_text, hoverinfo="text", showlegend=False))

    note = frequency_note(preset) if quantity == "frequency" else None
    if preset is not None and note is None:
        falls = []
        for kind in kinds:
            kind_bands = [b for b in bands if b.kind == kind]
            rx, ry = [], []
            for b in kind_bands:
                for req in required_boundary(preset, kind, b) or []:
                    x = min(req.required_s, x_max) if req.required_s > 0 else x_min
                    rx += [max(x, x_min), max(x, x_min)]
                    ry += [req.lo, req.hi]
            if rx:
                fig.add_trace(go.Scatter(x=rx, y=ry, mode="lines", line={"color": t.TEXT, "width": 1.6, "dash": "dash"},
                                         name=f"{preset.label} requires ride-through", legendgroup="req",
                                         showlegend=kind == kinds[0], hoverinfo="skip"))
            falls += shortfalls(kind_bands, preset)
        sx, sy = [], []
        for f in falls:
            left, right = max(f.model_s, x_min), min(f.required_s, x_max)
            sx += [left, right, right, left, left, None]
            sy += [f.lo, f.lo, f.hi, f.hi, f.lo, None]
            fig.add_annotation(x=math.log10(math.sqrt(left * right)), y=(f.lo + f.hi) / 2, text=f.label(),
                               showarrow=False, font={"size": 10, "color": t.TRIP_TEXT}, bgcolor=t.WHITE)
        if sx:
            fig.add_trace(go.Scatter(x=sx, y=sy, fill="toself", fillcolor=t.SHORTFALL, mode="lines",
                                     line={"color": t.SHORTFALL_HATCH, "width": 1},
                                     fillpattern={"shape": "/", "fgcolor": t.SHORTFALL_HATCH, "bgcolor": t.SHORTFALL,
                                                  "size": 6, "solidity": 0.25},
                                     name="Short of the standard", hoverinfo="skip"))

    lo = min(b.lo for b in bands)
    hi = max(b.hi for b in bands)
    tested = [tested_range(doc, k) for k in kinds if tested_range(doc, k)]
    if quantity == "frequency" and tested:
        fmin, fmax = min(r[0] for r in tested), max(r[1] for r in tested)
        for y, text, anchor in ((fmax, f"above {fmax:g} Hz not tested", "bottom"),
                                (fmin, f"below {fmin:g} Hz not tested", "top")):
            fig.add_annotation(x=0.5, xref="paper", y=y, text=text, showarrow=False, yanchor=anchor,
                               font={"size": 10, "color": t.TEXT_MUTED})
    pad = (hi - lo) * 0.08 or 0.1
    fig.update_yaxes(range=[lo - pad * (quantity == "frequency"), hi + pad], ticksuffix="")
    return _layout(fig, quantity, x_min, x_max)


def _layout(fig: go.Figure, quantity: str, x_min: float, x_max: float) -> go.Figure:
    axis = {"gridcolor": t.HAIRLINE, "linecolor": t.CARD_BORDER, "zeroline": False,
            "tickfont": {"family": t.CSS_FONT_MONO, "size": 10, "color": t.TEXT_MUTED}}
    fig.update_layout(autosize=True, height=None, plot_bgcolor=t.SURFACE, paper_bgcolor=t.SURFACE,
                      margin={"l": 46, "r": 12, "t": 10, "b": 36}, showlegend=False,
                      font={"family": t.CSS_FONT_SANS, "size": 11, "color": t.TEXT})
    fig.update_xaxes(type="log", range=[math.log10(x_min), math.log10(x_max * 1.05)], ticksuffix=" s",
                     title={"text": "duration (log scale)", "font": {"size": 10, "color": t.TEXT_MUTED}}, **axis)
    fig.update_yaxes(title={"text": "pu" if quantity == "voltage" else "Hz", "font": {"size": 10, "color": t.TEXT_MUTED}},
                     **axis)
    return fig
