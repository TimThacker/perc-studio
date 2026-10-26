"""What happened in one run, read only from the load's P and Q at the bus.

A black-box model has no trip flag we can rely on, and its power naturally
changes with voltage (a current-limited or constant-impedance load draws much
less in a deep sag without tripping). So the class is decided from what
happens **after the disturbance ends**:

* the load **rode through** if P is back within `RECOVERED_FRACTION` of its
  pre-event value within the prompt window after the bus returns to normal,
  and stays there to the end of the run (a load that trips the moment the
  voltage recovers shows full power for an instant first);
* otherwise it **tripped** (or ceased): the report then gives when P came back
  to that level (reconnect), how long the climb took (ramp), and where it
  settled (full or partial recovery), or that it did not come back.

The prompt window is the model's own normal settling time, measured on a
mild disturbance it certainly rides through (`settle_time`), with a floor.
During the event, a fall to almost nothing while the voltage is still
healthy (≥ 0.5 pu) is reported as **momentary cessation** when the load then
recovers promptly.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import asdict, dataclass, field

RECOVERED_FRACTION = 0.9
CEASED_FRACTION = 0.1
MIN_PROMPT_WINDOW_S = 0.15
UNSTABLE_SPREAD = 0.05  # peak-to-peak P over the last part of the run, as a fraction of pre-event P
HEALTHY_VOLTAGE_PU = 0.5

RIDE_THROUGH = "ride_through"
CESSATION = "momentary_cessation"
TRIP_RECONNECT = "trip_reconnect"
TRIP_PARTIAL = "trip_partial_reconnect"
TRIP_NO_RECONNECT = "trip_no_reconnect"
FAILURE = "numerical_failure"
UNSTABLE = "unstable"

LABELS = {
    RIDE_THROUGH: "rode through",
    CESSATION: "momentary cessation",
    TRIP_RECONNECT: "tripped, reconnected",
    TRIP_PARTIAL: "tripped, partly reconnected",
    TRIP_NO_RECONNECT: "tripped, did not reconnect",
    FAILURE: "numerical failure",
    UNSTABLE: "unstable",
}


@dataclass(frozen=True)
class Outcome:
    cls: str
    p_pre: float | None = None
    min_p_ratio: float | None = None  # lowest P during the event / pre-event P
    trip_time_s: float | None = None  # first time P fell below CEASED_FRACTION while the voltage was healthy
    reconnect_s: float | None = None  # after the bus returned to normal, until P started climbing back
    ramp_s: float | None = None  # how long the climb took, to within 2% of where P settled
    final_ratio: float | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rode_through(self) -> bool:
        return self.cls in (RIDE_THROUGH, CESSATION)

    @property
    def tripped(self) -> bool:
        return self.cls in (TRIP_RECONNECT, TRIP_PARTIAL, TRIP_NO_RECONNECT)

    @property
    def label(self) -> str:
        return LABELS[self.cls]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


def _mean(values):
    vals = [v for v in values if not math.isnan(v)]
    return sum(vals) / len(vals) if vals else float("nan")


def _window(time, values, t0, t1):
    return [v for t, v in zip(time, values, strict=True) if t0 <= t <= t1]


def _interp_at(time, values, at):
    i = bisect.bisect_left(time, at)
    if i <= 0:
        return values[0]
    if i >= len(time):
        return values[-1]
    t0, t1 = time[i - 1], time[i]
    w = 0.0 if t1 == t0 else (at - t0) / (t1 - t0)
    return values[i - 1] + w * (values[i] - values[i - 1])


def classify(result, event_start: float, event_end: float, *, prompt_window_s: float = MIN_PROMPT_WINDOW_S
             ) -> Outcome:
    """`result` is a supervisor.CaseResult; the disturbance is [event_start, event_end)."""
    if not result.ok or not result.time:
        return Outcome(FAILURE, notes=(f"run status: {result.status}",))
    t, p, v = result.time, result.p, result.v
    if any(math.isnan(x) or math.isinf(x) for x in p):
        return Outcome(FAILURE, notes=("P is not a number in part of the run",))

    pre = _window(t, p, max(0.0, event_start - 0.2), event_start - 1e-6) or [p[0]]
    p_pre = _mean(pre)
    if abs(p_pre) < 1e-9:
        return Outcome(FAILURE, notes=("the load draws no power before the event",))
    ratio = [x / p_pre for x in p]

    during = [(ti, r, vi) for ti, r, vi in zip(t, ratio, v, strict=True) if event_start <= ti < event_end]
    min_ratio = min((r for _, r, _ in during), default=None)
    trip_time = next((ti for ti, r, vi in during if r < CEASED_FRACTION and vi >= HEALTHY_VOLTAGE_PU), None)

    # The trace keeps a row only where something changes, so P at the moment the event ends is interpolated:
    # a load whose power never moved has no row there, and the next stored row can be seconds later.
    after = [(event_end, _interp_at(t, ratio, event_end))] if t[0] <= event_end <= t[-1] else []
    after += [(ti, r) for ti, r in zip(t, ratio, strict=True) if ti > event_end]
    window = max(prompt_window_s, MIN_PROMPT_WINDOW_S)
    t_end = t[-1]
    if after and t_end - event_end >= window and _oscillating(after):
        return Outcome(UNSTABLE, p_pre, min_ratio, trip_time, final_ratio=after[-1][1],
                       notes=("P keeps swinging after the event",))

    last_low = max((i for i, (_ti, r) in enumerate(after) if r < RECOVERED_FRACTION), default=-1)
    recovered_at = after[last_low + 1][0] if last_low + 1 < len(after) else None
    final_ratio = after[-1][1] if after else ratio[-1]
    if recovered_at is not None and recovered_at - event_end <= window:
        if trip_time is not None and min_ratio is not None and min_ratio < CEASED_FRACTION:
            return Outcome(CESSATION, p_pre, min_ratio, trip_time, recovered_at - event_end, None, final_ratio)
        return Outcome(RIDE_THROUGH, p_pre, min_ratio, None, None, None, final_ratio)

    # Tripped. When did the climb back start and end?
    if recovered_at is None:
        settled = _settled(after)
        if settled is not None and CEASED_FRACTION < settled < RECOVERED_FRACTION:
            return Outcome(TRIP_PARTIAL, p_pre, min_ratio, trip_time, None, None, final_ratio,
                           (f"settled at {settled:.0%} of the pre-event power",))
        return Outcome(TRIP_NO_RECONNECT, p_pre, min_ratio, trip_time, None, None, final_ratio)
    back = reconnection(after, event_end)
    return Outcome(TRIP_RECONNECT, p_pre, min_ratio, trip_time, back.get("delay_s"), back.get("ramp_s"), final_ratio)


RECONNECTED_RATIO = 0.25


def reconnection(after: list[tuple[float, float]], event_end: float) -> dict:
    """From (time, P / pre-event P) samples after the bus returned: did the load come back (to at least
    RECONNECTED_RATIO), when did the climb start (the last moment P was still at its off level) and how long did
    the climb take to get within 2% of where P settled."""
    if not after:
        return {"reconnected": False}
    final = after[-1][1]
    if final < RECONNECTED_RATIO:
        return {"reconnected": False, "final_ratio": round(final, 4)}
    off = min(r for _, r in after)
    reach_t = next((t for t, r in after if r >= 0.98 * final), None)
    start = None
    for t, r in after:
        if reach_t is not None and t > reach_t:
            break
        if r <= off + 0.02:
            start = t
    if off > 0.9 * final:  # never really dropped after the bus came back
        start = None
    return {"reconnected": True, "final_ratio": round(final, 4),
            "delay_s": None if start is None else round(start - event_end, 4),
            "ramp_s": None if start is None or reach_t is None else round(reach_t - start, 4)}


def _oscillating(after):
    """P swings up and down (at least four reversals bigger than UNSTABLE_SPREAD / 4) over the second half of the
    observation, and the swings in its last quarter are not dying out. A ramp or a single step is not a swing."""
    t_end = after[-1][0]
    half = [r for ti, r in after if ti >= after[0][0] + 0.5 * (t_end - after[0][0])]
    if len(half) < 9 or max(half) - min(half) <= UNSTABLE_SPREAD:
        return False
    step = UNSTABLE_SPREAD / 4
    reversals, direction, anchor = 0, 0, half[0]
    for r in half[1:]:
        if direction >= 0 and r < anchor - step:
            reversals += direction > 0
            direction, anchor = -1, r
        elif direction <= 0 and r > anchor + step:
            reversals += direction < 0
            direction, anchor = 1, r
        elif (direction > 0 and r > anchor) or (direction < 0 and r < anchor):
            anchor = r
    if reversals < 4:
        return False
    quarter = half[len(half) // 2:]
    return max(quarter) - min(quarter) >= 0.5 * (max(half) - min(half))


def _settled(after):
    if len(after) < 2:
        return None
    t_end = after[-1][0]
    tail = [r for ti, r in after if ti >= t_end - 1.0]
    if tail and max(tail) - min(tail) < 0.02:
        return _mean(tail)
    return None


def settle_time(result, event_end: float, tolerance: float = 0.02) -> float | None:
    """How long after `event_end` P stays within `tolerance` of its final value: the model's own settling time,
    used to size the prompt window. None if the run never settles."""
    if not result.ok or not result.time:
        return None
    final = result.p[-1]
    if abs(final) < 1e-9:
        return None
    last_out = None
    for ti, pi in zip(result.time, result.p, strict=True):
        if ti >= event_end and abs(pi - final) > tolerance * abs(final):
            last_out = ti
    return 0.0 if last_out is None else last_out - event_end


def flat_run_findings(result, *, drift_limit: float = 0.01) -> dict:
    """Stage 1 checks on a run with no disturbance: did P and Q stay put, and did the load stay connected?"""
    if not result.ok or not result.time:
        return {"ok": False, "reason": f"run status: {result.status}"}
    p0, q0 = result.p[0], result.q[0]
    if abs(p0) < 1e-9:
        return {"ok": False, "reason": "the load draws no power at t = 0"}
    drift_p = max(abs(x - p0) for x in result.p) / abs(p0)
    drift_q = max(abs(x - q0) for x in result.q) / max(abs(p0), abs(q0))
    tripped = min(result.p) < 0.5 * p0
    ok = drift_p <= drift_limit and drift_q <= drift_limit and not tripped
    reason = ("steady" if ok else "tripped with no disturbance" if tripped
              else f"P drifted {drift_p:.1%} and Q {drift_q:.1%} with no disturbance")
    return {"ok": ok, "reason": reason, "p0": p0, "q0": q0, "drift_p": drift_p, "drift_q": drift_q,
            "tripped": tripped}


def traces_match(a, b, *, p_tol: float = 0.02) -> tuple[bool, float]:
    """Whether two runs of the same case agree (time-step and repeatability checks): the RMS difference of P,
    on `a`'s time grid, relative to the pre-event power."""
    if not (a.ok and b.ok and a.time and b.time):
        return False, float("inf")
    def at(res, ti):
        return _interp_at(res.time, res.p, ti)

    grid = [i * a.time[-1] / 400 for i in range(401)]
    scale = abs(a.p[0]) or 1.0
    rms = math.sqrt(sum((at(a, ti) - at(b, ti)) ** 2 for ti in grid) / len(grid)) / scale
    return rms <= p_tol, rms
