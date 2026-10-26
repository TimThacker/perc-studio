from blackbox.scoring import FAILS, MEETS, UNSOLVABLE, compare_family, overall
from presets.ridethrough import RIDE_THROUGH_PRESETS

PRESET = RIDE_THROUGH_PRESETS["ercot_nogrr282"]


def search(tag, points):
    return {"tag": tag, "points": points}


def test_a_row_with_unsolved_cases_is_not_solvable_not_a_failure():
    """0 pu cannot be solved; the search reads the failure as a trip, which must not score as `fails` (B6)."""
    searches = [search(0.0, [(0.0167, True), (0.05, False), (10.0, False)]),
                search(0.9, [(0.0167, True), (20.0, True)])]
    verdicts = compare_family(PRESET, "undervoltage", searches, 20.0, frozenset({0.0}))
    by_value = {v.value: v for v in verdicts}
    assert by_value[0.0].verdict == UNSOLVABLE
    assert by_value[0.0].longest_ok_s is None and by_value[0.0].shortest_trip_s is None
    assert overall([by_value[0.0]]) == UNSOLVABLE


def test_without_unsolved_cases_the_same_row_fails():
    searches = [search(0.0, [(0.0167, True), (0.05, False), (10.0, False)])]
    assert compare_family(PRESET, "undervoltage", searches, 20.0)[0].verdict == FAILS


def test_a_solvable_failure_elsewhere_still_wins_the_overall():
    searches = [search(0.0, [(0.0167, True), (0.05, False)]),
                search(0.5, [(0.0167, True), (0.1, False)])]
    verdicts = compare_family(PRESET, "undervoltage", searches, 20.0, frozenset({0.0}))
    assert overall(verdicts) == FAILS
    assert MEETS not in {v.verdict for v in verdicts}
