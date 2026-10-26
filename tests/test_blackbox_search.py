"""The boundary search engine, against outcome functions with known answers."""

import pytest

from blackbox.search import Axis, BoundarySearch, run_searches


def run(searches, fn):
    calls = []

    def evaluate(batch):
        calls.append(len(batch))
        return [fn(s.tag, x) for s, x in batch]

    run_searches(searches, evaluate)
    return calls


def test_single_threshold_is_bracketed_within_tolerance():
    axis = Axis("duration", 0.0167, 20.0, "log", tol=0.05)
    s = BoundarySearch(axis, tag="a")
    run([s], lambda _tag, x: x < 0.73)
    (t,) = s.transitions()
    assert t.below < 0.73 <= t.above and t.above <= t.below * 1.05
    assert t.good_below and s.monotonic
    assert len(s.points) <= 20


def test_no_flip_reports_one_outcome_after_interior_checks():
    s = BoundarySearch(Axis("duration", 0.02, 20.0), tag="a")
    run([s], lambda _tag, x: True)
    assert s.all_good() is True and s.transitions() == [] and len(s.points) == 4


def test_a_flip_only_in_the_interior_is_found():
    # good at both ends, bad in the middle: the uniform check must catch it
    s = BoundarySearch(Axis("duration", 0.02, 20.0), tag="a", interior_checks=3)
    run([s], lambda _tag, x: not (0.3 < x < 3.0))
    assert not s.monotonic
    flips = s.transitions()
    assert len(flips) == 2
    assert flips[0].below < 0.3 <= flips[0].above and flips[1].below < 3.0 <= flips[1].above


def test_non_monotonic_region_is_detected_and_mapped():
    # trips for 0.1-0.5 s only (a deliberately odd model): ends both good... use one that differs at the ends
    def fn(_tag, x):
        return x < 0.1 or 0.5 <= x < 2.0

    s = BoundarySearch(Axis("duration", 0.02, 20.0), tag="a")
    run([s], fn)
    assert not s.monotonic
    edges = sorted(round(t.estimate, 1) for t in s.transitions())
    assert edges == pytest.approx([0.1, 0.5, 2.0], abs=0.06)


def test_linear_axis():
    s = BoundarySearch(Axis("recovery voltage", 0.8, 1.1, "linear", tol=0.005), tag="a")
    run([s], lambda _tag, x: x > 0.9)
    (t,) = s.transitions()
    assert t.below <= 0.9 < t.above and t.above - t.below <= 0.005


def test_searches_run_in_lockstep_batches():
    searches = [BoundarySearch(Axis("duration", 0.02, 20.0), tag=d) for d in (0.2, 0.5, 0.8)]
    calls = run(searches, lambda d, x: x < d * 2)
    assert calls[0] == 6  # both ends of all three searches in the first round
    for s in searches:
        (t,) = s.transitions()
        assert t.below < s.tag * 2 <= t.above
