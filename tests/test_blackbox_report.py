"""Scoring rules, the classifier on hand-made traces, and the report and bundle written from a real (fake-PSS/E) run."""

import json
import math
import zipfile

import pytest

from blackbox import classify as cl
from blackbox.protocol import Validation, ValidationSetup
from blackbox.report import write_outputs
from blackbox.scoring import (
    BEYOND,
    EDGE,
    FAILS,
    MEETS,
    NO_REQUIREMENT,
    point_verdict,
    required_duration,
)
from blackbox.supervisor import CaseResult, CaseSpec
from presets.ridethrough import RIDE_THROUGH_PRESETS

ERCOT = RIDE_THROUGH_PRESETS["ercot_nogrr282"]


@pytest.mark.parametrize("kind, value, expected", [
    ("undervoltage", 0.0, 0.15),
    ("undervoltage", 0.1, 0.15),
    ("undervoltage", 0.2, 0.25),
    ("undervoltage", 0.5, 0.5),
    ("undervoltage", 0.85, 2.0),
    ("undervoltage", 0.9, math.inf),
    ("overvoltage", 1.1, math.inf),
    ("overvoltage", 1.15, 2.0),
    ("overvoltage", 1.25, 0.0),
    ("frequency", 58.0, 0.0),  # ERCOT's preset has no frequency table
])
def test_required_duration_reads_the_preset_envelope(kind, value, expected):
    assert required_duration(ERCOT, kind, value) == expected


def test_required_duration_for_a_frequency_table():
    preset = next(p for p in RIDE_THROUGH_PRESETS.values() if p.frequency_ride_through)
    table = preset.frequency_ride_through
    assert required_duration(preset, "frequency", (table.continuous_low_hz + table.continuous_high_hz) / 2) == math.inf
    band = table.underfrequency[0]
    assert required_duration(preset, "frequency", band.limit_hz) >= band.min_duration_s


@pytest.mark.parametrize("required, points, verdict", [
    (0.5, [(0.6, True), (0.7, False)], MEETS),
    (0.5, [(0.3, True), (0.4, False)], FAILS),
    (0.5, [(0.45, True), (0.55, False)], EDGE),
    (math.inf, [(20.0, True)], BEYOND),
    (30.0, [(20.0, True)], BEYOND),
    (0.0, [(0.1, False)], NO_REQUIREMENT),
])
def test_point_verdicts(required, points, verdict):
    assert point_verdict(required, points, tested_max=20.0)[0] == verdict


def _result(t, p, v=None):
    v = v or [1.0] * len(t)
    spec = CaseSpec(records=(), segments=(), t_end=t[-1])
    return CaseResult(spec, "k", "ok", {}, time=t, v=v, f_hz=[60.0] * len(t), p=p, q=[0.0] * len(t))


def test_classifier_on_hand_made_traces():
    t = [0.0, 0.99, 1.0, 1.2, 1.21, 1.3, 3.0]
    # constant-current-like: P falls with V during the sag and comes straight back
    ride = _result(t, [1, 1, 0.3, 0.3, 1, 1, 1], v=[1, 1, 0.3, 0.3, 1, 1, 1])
    assert cl.classify(ride, 1.0, 1.2).cls == cl.RIDE_THROUGH
    # stays off after the sag
    off = _result(t, [1, 1, 0.3, 0.0, 0.0, 0.0, 0.0])
    assert cl.classify(off, 1.0, 1.2).cls == cl.TRIP_NO_RECONNECT
    # back to full power for an instant, then off: not a ride-through
    blip = _result(t, [1, 1, 1, 1, 1, 0.0, 0.0])
    assert cl.classify(blip, 1.0, 1.2).cls == cl.TRIP_NO_RECONNECT
    # trips, reconnects 1 s later over a 1 s ramp
    t2 = [0.0, 0.99, 1.0, 1.1, 1.2, 2.2, 3.2, 5.0]
    rec = cl.classify(_result(t2, [1, 1, 1, 0, 0, 0, 1, 1]), 1.0, 1.2)
    assert rec.cls == cl.TRIP_RECONNECT and rec.reconnect_s == pytest.approx(1.0) and rec.ramp_s == pytest.approx(1.0)
    # stops at 40%
    part = cl.classify(_result(t2 + [6.5], [1, 1, 1, 0, 0, 0, 0.4, 0.4, 0.4]), 1.0, 1.2)
    assert part.cls == cl.TRIP_PARTIAL
    # NaN
    assert cl.classify(_result(t, [1, 1, float("nan"), 1, 1, 1, 1]), 1.0, 1.2).cls == cl.FAILURE
    # a flat trace stores no row at the event's end (and times are rounded): the next row is seconds later
    flat = _result([0.0, 1.0001, 9.962143, 11.96214], [1, 1, 1, 1])
    assert cl.classify(flat, 1.0, 9.962143411).cls == cl.RIDE_THROUGH


def test_oscillation_is_unstable_but_a_ramp_is_not():
    t = [i * 0.01 for i in range(600)]
    swing = [1.0 if ti < 1.2 else 1.0 + 0.1 * math.sin(2 * math.pi * 3 * ti) for ti in t]
    assert cl.classify(_result(t, swing), 1.0, 1.2).cls == cl.UNSTABLE
    ramp = [1.0 if ti < 1.0 else 0.0 if ti < 2.0 else min(1.0, (ti - 2.0) / 3.0) for ti in t]
    assert cl.classify(_result(t, ramp), 1.0, 1.2).cls != cl.UNSTABLE


def test_report_and_bundle(fake_psse_install, tmp_path):
    text = ("4021 'USRLOD' '1' 'FAKETRIP' 12 1 0 14 0 0\n"
            " 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n")
    setup = ValidationSetup(fake_psse_install, text, preset_ids=("ercot_nogrr282", "pjm_lcl"), level="quick",
                            dyr_name="fake.dyr")
    work = tmp_path / "work"
    doc = Validation(setup, work).run()
    paths = write_outputs(doc, work, tmp_path / "out", dyr_text=text)
    page = paths["html"].read_text(encoding="utf-8")
    for heading in ("Summary", "Environment", "The model", "Time step", "Characterization", "Comparison with presets",
                    "Robustness of the results", "Method"):
        assert f"<h2>{heading}</h2>" in page
    assert page.count("bbv-fig-") >= 3
    assert "<script src=\"https://cdn.plot.ly" not in page  # plotly.js is embedded: the report opens offline
    assert json.loads(paths["json"].read_text())["comparison"]["ercot_nogrr282"]["overall"]
    with zipfile.ZipFile(paths["bundle"]) as z:
        names = z.namelist()
    assert {"validation.json", "report.html", "fake.dyr", "psse_worker.py", "outx.py", "rerun.py"} <= set(names)
    assert any(n.endswith("/case.outx") for n in names)  # every channel travels with the bundle
    case_dirs = {n.split("/")[1] for n in names if n.startswith("cases/")}
    assert len(case_dirs) >= len({p["key"] for p in doc["points"]})


def test_report_of_a_stopped_validation(fake_psse_install, tmp_path):
    text = "4021 'USRLOD' '1' 'NOSUCH' 12 1 0 1 0 0 1.0 /\n"
    doc = Validation(ValidationSetup(fake_psse_install, text, level="quick"), tmp_path / "w").run()
    page = write_outputs(doc, tmp_path / "w", tmp_path / "out")["html"].read_text(encoding="utf-8")
    assert "The validation stopped" in page and "model_not_found" in page
