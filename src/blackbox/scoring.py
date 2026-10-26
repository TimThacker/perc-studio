"""Comparing measured ride-through boundaries with each preset.

For every outer value the search ran (a sag depth, a swell level, a held
frequency), a preset requires the load to ride through disturbances up to
some duration (possibly forever). The search gives the measured boundary as a
bracket: the longest disturbance seen riding through and the shortest seen
tripping. The verdict at that point:

* **meets**: the load was seen riding through at least the required duration;
* **fails**: the load was seen tripping on a disturbance shorter than required;
* **at the edge**: the requirement falls inside the bracket, so the answer is
  within the search tolerance;
* **not solvable**: a case at this value failed to solve in PSS/E (not a trip), so there is no boundary to compare;
* **beyond tested range**: the requirement is longer than the longest
  disturbance run, and the load rode through everything run.

Only the ride-through requirement is checked. Tripping where a preset permits
it is never a failure. The wording everywhere is "compared with the preset as
encoded in this app", never "compliant".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from presets.envelope import (
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
)

MEETS, FAILS, EDGE, BEYOND, NO_REQUIREMENT = "meets", "fails", "at the edge", "beyond tested range", "no requirement"
UNSOLVABLE = "not solvable"  # a case at this value did not solve (for example a bus at exactly 0 pu): no boundary


def required_duration(preset, kind: str, value: float) -> float:
    """How long the preset requires the load to ride through `value` (0 when it may trip at once, inf when it
    must never trip)."""
    if kind == "undervoltage":
        segments = envelope_segments_from_steps(preset.envelope, t_min=0.0, t_max=math.inf)
        # The floor rises with duration; ride-through is required while value >= floor(t).
        for t0, _t1, floor in segments:
            if floor > value + 1e-9:
                return t0
        return math.inf
    if kind == "overvoltage":
        segments = overvoltage_segments_from_steps(preset.overvoltage_envelope, t_min=0.0, t_max=math.inf)
        for t0, _t1, ceiling in segments:
            if ceiling < value - 1e-9:
                return t0
        return math.inf
    if kind == "frequency":
        table = preset.frequency_ride_through
        if table is None:
            return 0.0
        if table.continuous_low_hz <= value <= table.continuous_high_hz:
            return math.inf
        bands = table.underfrequency if value < table.continuous_low_hz else table.overfrequency
        inside = [b.min_duration_s for b in bands
                  if (b.limit_hz <= value + 1e-9 if value < table.continuous_low_hz else b.limit_hz >= value - 1e-9)]
        return max(inside, default=0.0)
    raise ValueError(f"no preset requirement for {kind!r}")


@dataclass(frozen=True)
class PointVerdict:
    value: float
    required_s: float
    longest_ok_s: float | None
    shortest_trip_s: float | None
    verdict: str

    def to_dict(self) -> dict:
        return {"value": self.value, "required_s": None if math.isinf(self.required_s) else self.required_s,
                "required_forever": math.isinf(self.required_s), "longest_ok_s": self.longest_ok_s,
                "shortest_trip_s": self.shortest_trip_s, "verdict": self.verdict}


def point_verdict(required: float, points: list[tuple[float, bool]], tested_max: float) -> tuple[str, float | None,
                                                                                                   float | None]:
    """`points` are (duration, rode_through) from the search at one outer value."""
    if required <= 0:
        return NO_REQUIREMENT, None, None
    longest_ok = max((x for x, ok in points if ok), default=None)
    trips_short = [x for x, ok in points if not ok and x < required - 1e-9]
    shortest_trip = min((x for x, ok in points if not ok), default=None)
    if trips_short:
        return FAILS, longest_ok, shortest_trip
    if longest_ok is not None and longest_ok >= required - 1e-9:
        return MEETS, longest_ok, shortest_trip
    if required > tested_max and longest_ok is not None and longest_ok >= tested_max - 1e-9:
        return BEYOND, longest_ok, shortest_trip
    return EDGE, longest_ok, shortest_trip


def compare_family(preset, kind: str, searches: list[dict], tested_max: float,
                   unsolvable: frozenset[float] = frozenset()) -> list[PointVerdict]:
    """`searches` are BoundarySearch.summary() dicts, tagged with their outer value. `unsolvable` holds the outer
    values where a case failed to solve: a failure looks like a trip to the search, so those rows have no boundary."""
    out = []
    for s in searches:
        value = s["tag"]
        required = required_duration(preset, kind, value)
        if value in unsolvable and required > 0:
            out.append(PointVerdict(value, required, None, None, UNSOLVABLE))
            continue
        points = [(x, ok) for x, ok in s["points"]]
        verdict, ok_s, trip_s = point_verdict(required, points, tested_max)
        out.append(PointVerdict(value, required, ok_s, trip_s, verdict))
    return out


def overall(verdicts: list[PointVerdict]) -> str:
    kinds = {v.verdict for v in verdicts}
    if FAILS in kinds:
        return FAILS
    if EDGE in kinds:
        return EDGE
    if UNSOLVABLE in kinds:
        return UNSOLVABLE
    if BEYOND in kinds:
        return BEYOND
    if MEETS in kinds:
        return MEETS
    return NO_REQUIREMENT
