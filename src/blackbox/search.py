"""The boundary search engine: where along one disturbance axis does the
model's outcome change?

A `BoundarySearch` works on one inner axis (for example sag duration) for one
outer value (for example a 0.5 pu sag). It proposes points, is told the
outcome at each (`True` = the "good" side, such as "rode through"), and
narrows down every place the outcome flips:

1. both ends of the axis; if they agree, a few interior points check that the
   outcome really never changes;
2. bisection (geometric on a log axis) until each bracket is within tolerance;
3. a check inside each settled region; if any point disagrees, the axis is
   **not monotonic** (a model that trips at some durations and not at longer
   ones, or that cycles), so it is scanned densely and every flip is bisected.

Searches never change the model: only the disturbance moves. `run_searches`
steps many searches in lockstep so each round's runs can go to PSS/E as one
parallel batch.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Axis:
    name: str
    lo: float
    hi: float
    scale: str = "log"  # "log" | "linear"
    tol: float = 0.05  # relative on a log axis, absolute on a linear one
    unit: str = ""

    def mid(self, a: float, b: float) -> float:
        return math.sqrt(a * b) if self.scale == "log" else 0.5 * (a + b)

    def close(self, a: float, b: float) -> bool:
        if self.scale == "log":
            return b <= a * (1.0 + self.tol)
        return b - a <= self.tol

    def spaced(self, n: int, a: float | None = None, b: float | None = None) -> list[float]:
        a = self.lo if a is None else a
        b = self.hi if b is None else b
        if n <= 1:
            return [self.mid(a, b)]
        if self.scale == "log":
            la, lb = math.log(a), math.log(b)
            return [math.exp(la + (lb - la) * i / (n - 1)) for i in range(n)]
        return [a + (b - a) * i / (n - 1) for i in range(n)]

    def key(self, x: float) -> float:
        return round(x, 9)


@dataclass(frozen=True)
class Transition:
    """The outcome flips between `below` and `above` (the last point with one outcome, the first with the other)."""

    below: float
    above: float
    good_below: bool

    @property
    def estimate(self) -> float:
        return math.sqrt(self.below * self.above) if self.below > 0 else 0.5 * (self.below + self.above)


@dataclass
class BoundarySearch:
    axis: Axis
    tag: Hashable = None
    interior_checks: int = 2
    dense_points: int = 12
    max_points: int = 60
    points: dict = field(default_factory=dict)  # key -> (x, good)
    monotonic: bool = True
    _phase: str = "ends"
    _pending: list = field(default_factory=list)

    # --- public -------------------------------------------------------------------------------------------------

    def next_points(self) -> list[float]:
        """Points to run next; empty when the search is finished."""
        if self._pending:
            return [x for x in self._pending if self.axis.key(x) not in self.points]
        if len(self.points) >= self.max_points:
            self._phase = "done"
            return []
        proposals = self._propose()
        self._pending = [x for x in proposals if self.axis.key(x) not in self.points]
        return list(self._pending)

    def feed(self, x: float, good: bool) -> None:
        self.points[self.axis.key(x)] = (x, bool(good))
        self._pending = [p for p in self._pending if self.axis.key(p) != self.axis.key(x)]

    @property
    def done(self) -> bool:
        return self._phase == "done"

    def ordered(self) -> list[tuple[float, bool]]:
        return sorted(self.points.values())

    def transitions(self) -> list[Transition]:
        pts = self.ordered()
        return [Transition(a[0], b[0], a[1]) for a, b in itertools.pairwise(pts) if a[1] != b[1]]

    def all_good(self) -> bool | None:
        """True/False when every point agrees, None when the outcome flips somewhere."""
        outcomes = {g for _, g in self.points.values()}
        return outcomes.pop() if len(outcomes) == 1 else None

    def summary(self) -> dict:
        return {
            "tag": self.tag,
            "axis": self.axis.name,
            "points": [[x, g] for x, g in self.ordered()],
            "transitions": [[t.below, t.above, t.good_below] for t in self.transitions()],
            "monotonic": self.monotonic,
            "all_good": self.all_good(),
        }

    # --- phases -------------------------------------------------------------------------------------------------

    def _open_brackets(self) -> list[tuple[float, float]]:
        return [(t.below, t.above) for t in self.transitions() if not self.axis.close(t.below, t.above)]

    def _propose(self) -> list[float]:
        while True:
            if self._phase == "ends":
                self._phase = "ends_wait"
                return [self.axis.lo, self.axis.hi]
            if self._phase == "ends_wait":
                if self.all_good() is not None:
                    self._phase = "uniform_check"
                    return self.axis.spaced(self.interior_checks + 2)[1:-1]
                self._phase = "bisect"
                continue
            if self._phase == "uniform_check":
                if self.all_good() is None:
                    self.monotonic = False
                    self._phase = "bisect"
                    continue
                self._phase = "done"
                return []
            if self._phase == "bisect":
                brackets = self._open_brackets()
                if brackets:
                    return [self.axis.mid(a, b) for a, b in brackets]
                self._phase = "region_check" if self.monotonic else "done"
                if self._phase == "region_check":
                    proposals = self._region_points()
                    if proposals:
                        self._phase = "region_wait"
                        return proposals
                    self._phase = "done"
                return []
            if self._phase == "region_wait":
                if len(self.transitions()) > 1:
                    self.monotonic = False
                    self._phase = "dense"
                    continue
                self._phase = "done"
                return []
            if self._phase == "dense":
                self._phase = "bisect"
                return self.axis.spaced(self.dense_points)
            return []

    def _region_points(self) -> list[float]:
        """A few points inside each region either side of the flip(s), away from points already run."""
        pts = self.ordered()
        xs = [x for x, _ in pts]
        regions = []
        for t in self.transitions():
            regions.append((self.axis.lo, t.below))
            regions.append((t.above, self.axis.hi))
        out = []
        for a, b in regions:
            if self.axis.close(a, b):
                continue
            for x in self.axis.spaced(self.interior_checks + 2, a, b)[1:-1]:
                if all(abs(x - y) > 1e-12 for y in xs):
                    out.append(x)
        return out


def run_searches(searches: Sequence[BoundarySearch],
                 evaluate: Callable[[list[tuple[BoundarySearch, float]]], list[bool]],
                 *, max_rounds: int = 40, should_stop: Callable[[], bool] = lambda: False) -> None:
    """Step every search until each is done. `evaluate` gets one batch of (search, x) per round and returns the
    outcome for each (True = good side)."""
    for _ in range(max_rounds):
        if should_stop():
            return
        batch = [(s, x) for s in searches if not s.done for x in s.next_points()]
        if not batch:
            if all(s.done for s in searches):
                return
            continue
        outcomes = evaluate(batch)
        for (s, x), good in zip(batch, outcomes, strict=True):
            s.feed(x, good)
