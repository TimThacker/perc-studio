"""Probe families: the disturbances black-box validation plays back.

Each family holds an outer value fixed (a sag depth, a held frequency, ...)
and searches an inner axis (usually how long the disturbance lasts) for where
the model's behavior changes. Only the disturbance moves; the model's CONs are
never touched. The grids for each test level are data in `LEVELS`, and every
voltage or frequency at which a selected preset's requirement changes is added
to the grid, because that is where a model is most likely to fall short.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .search import Axis

EVENT_START = 1.0  # s; leaves the model a second to settle after initialization
NOMINAL_HZ = 60.0


@dataclass(frozen=True)
class Event:
    """A disturbance ready to run: playback segments, run length and the window the classifier judges."""

    segments: tuple[tuple, ...]
    t_end: float
    start: float
    end: float
    label: str


@dataclass(frozen=True)
class Family:
    id: str
    title: str
    kind: str  # undervoltage | overvoltage | frequency | recovery | repeat | rocof
    outer_name: str
    outer_unit: str
    outer_values: tuple[float, ...]
    inner: Axis
    observe_s: float
    description: str
    needs: tuple[str, ...] = ()  # families whose results this one uses

    def event(self, outer: float, inner: float, context: dict) -> Event:
        return _BUILDERS[self.kind](self, outer, inner, context)


def _hold(fam, outer, inner, ctx, *, v=1.0, f=NOMINAL_HZ):
    t0 = EVENT_START
    t1 = t0 + inner
    observe = max(fam.observe_s, ctx.get("observe_s", 0.0))
    segs = ((0.0, 1.0, NOMINAL_HZ), (t0, v, f), (t1, 1.0, NOMINAL_HZ))
    return segs, t1 + observe, t0, t1


def _undervoltage(fam, outer, inner, ctx):
    segs, t_end, t0, t1 = _hold(fam, outer, inner, ctx, v=outer)
    return Event(segs, t_end, t0, t1, f"{outer:.3g} pu for {inner:.4g} s")


def _overvoltage(fam, outer, inner, ctx):
    segs, t_end, t0, t1 = _hold(fam, outer, inner, ctx, v=outer)
    return Event(segs, t_end, t0, t1, f"{outer:.3g} pu for {inner:.4g} s")


def _frequency(fam, outer, inner, ctx):
    segs, t_end, t0, t1 = _hold(fam, outer, inner, ctx, f=outer)
    return Event(segs, t_end, t0, t1, f"{outer:.4g} Hz for {inner:.4g} s")


def _recovery(fam, outer, inner, ctx):
    """A disturbance the model is known to trip on, then the bus held at `inner` pu."""
    depth, duration = ctx["trip_event"]
    t0 = EVENT_START
    t1 = t0 + duration
    segs = ((0.0, 1.0, NOMINAL_HZ), (t0, depth, NOMINAL_HZ), (t1, inner, NOMINAL_HZ))
    return Event(segs, t1 + ctx.get("recovery_observe_s", fam.observe_s), t0, t1, f"trip on {depth:.3g} pu / {duration:.3g} s, recover to {inner:.3g} pu")


def _repeat(fam, outer, inner, ctx):
    """Two identical sags, each short enough to ride through alone, `inner` seconds apart."""
    each = ctx["single_ok"][outer]
    t0 = EVENT_START
    a1, b0 = t0 + each, t0 + each + inner
    b1 = b0 + each
    segs = ((0.0, 1.0, NOMINAL_HZ), (t0, outer, NOMINAL_HZ), (a1, 1.0, NOMINAL_HZ), (b0, outer, NOMINAL_HZ),
            (b1, 1.0, NOMINAL_HZ))
    return Event(segs, b1 + fam.observe_s, t0, b1, f"2 x {outer:.3g} pu / {each:.3g} s, {inner:.3g} s apart")


def _rocof(fam, outer, inner, ctx):
    """Frequency ramps to `outer` Hz at `inner` Hz/s, holds a second, and ramps back."""
    t0 = EVENT_START
    ramp = abs(outer - NOMINAL_HZ) / inner
    t1 = t0 + ramp
    t2 = t1 + 1.0
    t3 = t2 + ramp
    segs = ((0.0, 1.0, NOMINAL_HZ), (t0, 1.0, NOMINAL_HZ), (t1, 1.0, outer, "ramp"), (t2, 1.0, outer),
            (t3, 1.0, NOMINAL_HZ, "ramp"))
    return Event(segs, t3 + fam.observe_s, t0, t3, f"to {outer:.4g} Hz at {inner:.3g} Hz/s")


_BUILDERS = {"undervoltage": _undervoltage, "overvoltage": _overvoltage, "frequency": _frequency,
             "recovery": _recovery, "repeat": _repeat, "rocof": _rocof}


@dataclass(frozen=True)
class Level:
    id: str
    title: str
    uv_depths: tuple[float, ...]
    ov_levels: tuple[float, ...]
    frequencies: tuple[float, ...]
    duration_tol: float
    max_voltage_duration: float
    max_frequency_duration: float
    families: tuple[str, ...]
    interior_checks: int = 4  # points sampled inside each settled region; a narrower trip window can be missed
    repeat_depths: int = 2
    approx_runs: int = 0  # roughly how many PSS/E runs the level takes (an estimate: searches stop early or late)
    extra: dict = field(default_factory=dict)

    @property
    def runs_text(self) -> str:
        return f"about {self.approx_runs} runs"


LEVELS: dict[str, Level] = {
    "quick": Level("quick", "Quick", (0.0, 0.5, 0.8), (1.1, 1.2), (58.0, 62.0), 0.10, 10.0, 30.0,
                   ("undervoltage", "overvoltage", "frequency"), interior_checks=3, approx_runs=150),
    "standard": Level("standard", "Standard", tuple(round(0.1 * i, 2) for i in range(10)),
                      (1.05, 1.10, 1.15, 1.20, 1.25, 1.30),
                      (57.0, 57.5, 58.0, 58.5, 59.0, 59.5, 60.5, 61.0, 61.5, 62.0), 0.05, 20.0, 60.0,
                      ("undervoltage", "overvoltage", "frequency", "recovery", "repeat", "rocof"), approx_runs=400),
    "full": Level("full", "Full", tuple(round(0.05 * i, 2) for i in range(19)),
                  (1.05, 1.075, 1.10, 1.125, 1.15, 1.175, 1.20, 1.25, 1.30),
                  (57.0, 57.25, 57.5, 57.75, 58.0, 58.25, 58.5, 58.75, 59.0, 59.25, 59.5, 59.75,
                   60.25, 60.5, 60.75, 61.0, 61.25, 61.5, 61.75, 62.0), 0.02, 30.0, 300.0,
                  ("undervoltage", "overvoltage", "frequency", "recovery", "repeat", "rocof"), interior_checks=8,
                  repeat_depths=4, approx_runs=1500),
}


RECOVERY_RANGE_PU = (0.80, 1.10)  # the recovery family's axis (build_families)


def _span(values, fmt) -> str:
    lo, hi = min(values), max(values)
    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"


def _g(x: float) -> str:
    return f"{x:g}"


def coverage_lines(level_id: str) -> list[tuple[str, str]]:
    """What a test level runs, as (title, detail) lines for the setup screen, generated from `LEVELS`: e.g.
    ("Undervoltage", "sags to 0–0.9 pu, up to 20 s")."""
    level = LEVELS[level_id]
    lines = []
    if "undervoltage" in level.families:
        lines.append(("Undervoltage", f"sags to {_span(level.uv_depths, _g)} pu, up to {level.max_voltage_duration:g} s"))
    if "overvoltage" in level.families:
        lines.append(("Overvoltage", (f"swells of {_span(level.ov_levels, lambda x: f'{x:.2f}')} pu, "
                                      f"up to {level.max_voltage_duration:g} s")))
    if "frequency" in level.families:
        lines.append(("Frequency", f"held at {_span(level.frequencies, _g)} Hz, up to {level.max_frequency_duration:g} s"))
    if "recovery" in level.families:
        lo, hi = RECOVERY_RANGE_PU
        lines.append(("Reconnection", f"recovery to {lo:.2f}–{hi:.2f} pu after a trip"))
    extra = [name for fid, name in (("repeat", "Repeated sags"), ("rocof", "rate of change of frequency"))
             if fid in level.families]
    if extra:
        lines.append((" and ".join(extra).capitalize() if len(extra) == 1 else " and ".join(extra), ""))
    return lines


def preset_breakpoints(presets) -> dict[str, set[float]]:
    """Every voltage/frequency at which a preset's requirement changes."""
    uv, ov, freq = set(), set(), set()
    for p in presets:
        uv.update(round(s.voltage_pu, 4) for s in p.envelope if s.min_duration_s is not None)
        ov.update(round(s.voltage_pu, 4) for s in p.overvoltage_envelope if s.min_duration_s is not None)
        table = p.frequency_ride_through
        if table:
            freq.update(round(b.limit_hz, 4) for b in (*table.underfrequency, *table.overfrequency))
    return {"undervoltage": uv, "overvoltage": ov, "frequency": freq}


def _merge(base, extra, lo, hi, gap):
    values = sorted({*base, *(x for x in extra if lo <= x <= hi)})
    out = []
    for x in values:
        if out and abs(x - out[-1]) < gap:
            if x in extra:  # keep the preset's own value
                out[-1] = x
            continue
        out.append(x)
    return tuple(out)


def build_families(level_id: str, presets=(), *, observe_s: float = 2.0) -> list[Family]:
    level = LEVELS[level_id]
    marks = preset_breakpoints(presets)
    tol = level.duration_tol
    vdur = Axis("duration", 1.0 / 60.0, level.max_voltage_duration, "log", tol, "s")
    fdur = Axis("duration", 0.1, level.max_frequency_duration, "log", tol, "s")
    fams = {
        "undervoltage": Family(
            "undervoltage", "Undervoltage ride-through", "undervoltage", "sag depth", "pu",
            _merge(level.uv_depths, marks["undervoltage"], 0.0, 0.95, 0.004), vdur, observe_s,
            "For each sag depth, the longest sag the load rides through."),
        "overvoltage": Family(
            "overvoltage", "Overvoltage ride-through", "overvoltage", "swell level", "pu",
            _merge(level.ov_levels, marks["overvoltage"], 1.01, 1.5, 0.004), vdur, observe_s,
            "For each swell level, the longest swell the load rides through."),
        "frequency": Family(
            "frequency", "Frequency ride-through", "frequency", "frequency", "Hz",
            _merge(level.frequencies, marks["frequency"], 55.0, 65.0, 0.02), fdur, observe_s,
            "For each held frequency, the longest excursion the load rides through."),
        "recovery": Family(
            "recovery", "Reconnection window", "recovery", "trip event", "", (0.0,),
            Axis("recovery voltage", *RECOVERY_RANGE_PU, "linear", 0.005, "pu"), 120.0,
            "After a sag the load trips on, the voltages it reconnects at, and how long that takes.",
            needs=("undervoltage",)),
        "repeat": Family(
            "repeat", "Repeated sags", "repeat", "sag depth", "pu", (), Axis("gap", 0.02, 5.0, "log", 0.1, "s"),
            observe_s, "Two sags, each short enough to ride through alone: how close together can they be?",
            needs=("undervoltage",)),
        "rocof": Family(
            "rocof", "Rate of change of frequency", "rocof", "final frequency", "Hz", (59.0, 61.0),
            Axis("rate", 0.1, 10.0, "log", 0.1, "Hz/s"), observe_s,
            "Frequency ramps to a level the load rides through when it is held: the fastest ramp it rides through."),
    }
    return [fams[f] for f in level.families]
