"""Black-box validation end to end, against the fake PSS/E's FAKETRIP model, whose behavior is known exactly:
it trips when V < 0.7 pu for 0.2 s, V > 1.2 pu for 1.0 s, or f outside 57-63 Hz for 0.5 s, and reconnects once
0.9 < V < 1.2 has held for 1 s, ramping over 2 s."""

import pytest

from blackbox.protocol import Validation, ValidationSetup
from blackbox.scoring import FAILS, MEETS, required_duration
from presets.ridethrough import RIDE_THROUGH_PRESETS

# VUV TUV VOV TOV FLO FHI TF VREC TREC TRAMP NP DELTMAX CADENCE CYCLEMAX
BASE = [0.7, 0.2, 1.2, 1.0, 57.0, 63.0, 0.5, 0.9, 1.0, 2.0, 0, 0, 0, 0]


def dyr(name="FAKETRIP", cons=BASE, bus=4021):
    body = " ".join(f"{c:g}" for c in cons)
    return f"@! a model we know nothing about\n{bus} 'USRLOD' '1' '{name}' 12 1 0 {len(cons)} 0 0\n {body} /\n"


def validate(sel, tmp_path, *, cons=BASE, name="FAKETRIP", level="quick", presets=("ercot_nogrr282",), **kw):
    setup = ValidationSetup(sel, dyr(name, cons), preset_ids=presets, level=level, workers=4, **kw)
    return Validation(setup, tmp_path / "work").run()


def searches(doc, fam):
    return {s["tag"]: s for s in doc["families"][fam]["searches"]}


def test_quick_validation_finds_the_known_boundaries(fake_psse_install, tmp_path):
    doc = validate(fake_psse_install, tmp_path)
    assert doc["stopped"] is None, doc["stopped"]
    assert doc["stages"]["time_step"]["chosen"] == pytest.approx(1 / 240)
    assert not doc["stages"]["time_step"]["sensitive"]

    uv = searches(doc, "undervoltage")
    (below, above, good_below) = uv[0.5]["transitions"][0]
    assert good_below and below < 0.2 <= above and above <= below * 1.1 + 1 / 240
    assert uv[0.8]["all_good"] is True  # 0.8 pu is above the 0.7 pu trip level: never trips
    ov = searches(doc, "overvoltage")
    assert ov[1.1]["all_good"] is True
    assert ov[1.2]["all_good"] is True  # 1.2 pu is not above VOV = 1.2: never trips
    freq = searches(doc, "frequency")
    assert freq[58.0]["all_good"] is True

    # Every case was classified, and the ride-through runs really did ride through
    statuses = {p["status"] for p in doc["points"]}
    assert statuses == {"ok"}


def test_comparison_with_a_preset(fake_psse_install, tmp_path):
    doc = validate(fake_psse_install, tmp_path)
    ercot = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    uv = doc["comparison"]["ercot_nogrr282"]["families"]["undervoltage"]
    by_value = {p["value"]: p for p in uv["points"]}
    # At 0.5 pu ERCOT requires riding through longer than the model's 0.2 s timer: fail.
    if required_duration(ercot, "undervoltage", 0.5) > 0.2:
        assert by_value[0.5]["verdict"] == FAILS
    # 0.8 pu never trips, so whatever ERCOT requires there is met (or beyond the tested range).
    assert by_value[0.8]["verdict"] in (MEETS, "beyond tested range", "no requirement")
    assert doc["comparison"]["ercot_nogrr282"]["overall"] in (FAILS, "at the edge", MEETS, "beyond tested range")


def test_preset_breakpoints_are_added_to_the_grid(fake_psse_install, tmp_path):
    doc = validate(fake_psse_install, tmp_path)
    ercot = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    marks = {round(s.voltage_pu, 4) for s in ercot.envelope if s.min_duration_s is not None}
    tags = set(searches(doc, "undervoltage"))
    assert marks <= tags


def test_standard_level_maps_reconnection_repeats_and_ramps(fake_psse_install, tmp_path):
    doc = validate(fake_psse_install, tmp_path, level="standard", presets=())
    rec = doc["families"]["recovery"]
    (s,) = rec["searches"]
    (below, above, good_below) = s["transitions"][0]
    assert not good_below and below <= 0.9 < above  # reconnects only above VREC = 0.9 pu
    fast = [r for r in rec["reconnections"] if r["reconnected"]]
    assert fast and all(r["delay_s"] == pytest.approx(1.0, abs=0.05) for r in fast)
    assert all(r["ramp_s"] == pytest.approx(2.0 * 0.98, abs=0.05) for r in fast)  # to within 2% of a 2 s ramp
    assert all(s["all_good"] for s in doc["families"]["repeat"]["searches"])  # timers reset between sags
    assert doc["stages"]["robustness"]["repeatability"][0]["match"]
    assert all(h["match"] for h in doc["stages"]["robustness"]["half_step"])
    assert doc["stages"]["robustness"]["cadence"]["match"]


def test_cadence_dependence_is_flagged(fake_psse_install, tmp_path):
    cons = list(BASE)
    cons[12] = 1  # each run() call advances the ramp one extra step
    doc = validate(fake_psse_install, tmp_path, cons=cons, level="standard", presets=())
    cad = doc["stages"]["robustness"]["cadence"]
    assert not cad["match"] and "warning" in cad


def test_time_step_sensitivity_picks_a_smaller_step(fake_psse_install, tmp_path):
    cons = list(BASE)
    cons[11] = 1 / 300  # oscillates when DELT > 1/300 s
    doc = validate(fake_psse_install, tmp_path, cons=cons)
    stage = doc["stages"]["time_step"]
    assert stage["chosen"] == pytest.approx(1 / 480)
    assert any("time step" in d["action"] for d in doc["diagnosis"])


def test_non_monotonic_boundary_is_mapped(fake_psse_install, tmp_path):
    cons = list(BASE)
    cons[13] = 1.0  # FAKECYCLE: trips only on sags lasting 0.2 s to 1.0 s
    doc = validate(fake_psse_install, tmp_path, cons=cons, name="FAKECYCLE")
    s = searches(doc, "undervoltage")[0.5]
    assert not s["monotonic"]
    edges = [(b, a) for b, a, _ in s["transitions"]]
    assert len(edges) == 2
    assert edges[0][0] < 0.2 <= edges[0][1] and edges[1][0] <= 1.0 < edges[1][1]


@pytest.mark.parametrize("name, stopped", [
    ("NOSUCH", "could not read the model"),
    ("IGNOREDMD", "could not read the model"),  # real PSS/E 35.6: RECORD IGNORED and return code 0
    ("NOACCESSMD", "could not read the model"),  # real PSS/E 35.6 and 36.7: a user model with no DLL is NOT ACCESSIBLE
    ("FAKECRASH", "first run failed"),
])
def test_input_and_crash_problems_stop_with_findings(fake_psse_install, tmp_path, name, stopped):
    doc = validate(fake_psse_install, tmp_path, name=name)
    assert stopped in doc["stopped"]
    assert doc["stages"]["initialization"]["failure"]["status"] in ("dyre_error", "crashed")


def test_a_dll_that_does_not_load_names_the_dll(fake_psse_install, tmp_path):
    """A DLL built for another PSS/E version fails in addmodellibrary (B4): say which DLL, not just "the model"."""
    from test_blackbox_intake import _tiny_dll

    dll = tmp_path / "PERC2_wrongversion.dll"
    dll.write_bytes(_tiny_dll(imports=("kernel32.dll",)))
    doc = validate(fake_psse_install, tmp_path, dlls=(str(dll),))
    assert "PERC2_wrongversion.dll" in doc["stopped"] and "could not load" in doc["stopped"], doc["stopped"]


def test_reconnection_window_above_nominal_is_still_mapped(fake_psse_install, tmp_path):
    cons = list(BASE)
    cons[7] = 1.0  # reconnects only while 1.0 < V < 1.2, like a preset with VRPA = 1.00
    doc = validate(fake_psse_install, tmp_path, cons=cons, level="standard", presets=())
    rec = doc["families"]["recovery"]
    assert "skipped" not in rec, rec.get("skipped")
    (below, above, good_below) = rec["searches"][0]["transitions"][0]
    assert not good_below and below <= 1.0 < above
