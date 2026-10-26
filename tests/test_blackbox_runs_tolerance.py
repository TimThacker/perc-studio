"""Black-box results without Qt: the coverage list of each test level, run summaries, the measured-behaviour
table, and the tolerance curve with a standard laid over it (the documented PERC1 DLL 35.6 run vs ERCOT)."""

import json
import math

import pytest
from fixtures.blackbox_doc import documented_doc, write_run

from blackbox.families import LEVELS, coverage_lines
from blackbox.runs import (
    list_runs,
    measured_rows,
    read_run,
    summarize,
    summary_warnings,
)
from blackbox.tolerance import (
    caption,
    frequency_note,
    measured_boundary,
    overlay_presets,
    shortfalls,
    stage_voltages,
    tolerance_figure,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS

ERCOT = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
PJM = RIDE_THROUGH_PRESETS["pjm_lcl"]


# --- coverage --------------------------------------------------------------------------------------------------


def test_the_standard_level_lists_the_designed_coverage():
    assert coverage_lines("standard") == [
        ("Undervoltage", "sags to 0–0.9 pu, up to 20 s"),
        ("Overvoltage", "swells of 1.05–1.30 pu, up to 20 s"),
        ("Frequency", "held at 57–62 Hz, up to 60 s"),
        ("Reconnection", "recovery to 0.80–1.10 pu after a trip"),
        ("Repeated sags and rate of change of frequency", ""),
    ]
    assert LEVELS["standard"].runs_text == "about 400 runs"


def test_quick_and_full_levels_give_their_own_numbers():
    assert coverage_lines("quick") == [("Undervoltage", "sags to 0–0.8 pu, up to 10 s"),
                                       ("Overvoltage", "swells of 1.10–1.20 pu, up to 10 s"),
                                       ("Frequency", "held at 58–62 Hz, up to 30 s")]
    assert coverage_lines("full")[2] == ("Frequency", "held at 57–62 Hz, up to 300 s")
    assert (LEVELS["quick"].approx_runs, LEVELS["full"].approx_runs) == (150, 1500)


# --- run summaries --------------------------------------------------------------------------------------------


def test_a_run_summary_reads_only_the_document(tmp_path):
    _doc, run = read_run(write_run(tmp_path / "20261012-094100"))
    assert run.title == "PERC1 DLL · 35.6 · Standard"
    assert run.heading == "PERC1 DLL on PSS/E 35.6 · Standard level"
    assert run.subtitle == "12 Oct 2026 · 396 cases, all completed · 32 min on 4 workers · time step 0.00417 s"
    assert run.tab_title == "Run · PERC1 DLL · 35.6"
    assert run.overall == "fails"
    assert run.compared[0][:2] == ("ERCOT (NOGRR282)", "fails")
    assert run.psse_version == "35.6.4" and run.python == "3.11.9"
    assert run.warnings and "14.4 s" in run.warnings[0]


def test_listing_runs_is_newest_first_and_skips_folders_that_are_not_runs(tmp_path):
    older = documented_doc()
    older["generated"] = "2026-10-11 08:00:00"
    write_run(tmp_path / "20261011-080000", older)
    write_run(tmp_path / "20261012-094100")
    (tmp_path / "empty").mkdir()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "validation.json").write_text("{not json")
    runs = list_runs(tmp_path)
    assert [r.folder.name for r in runs] == ["20261012-094100", "20261011-080000"]
    assert list_runs(tmp_path / "missing") == []


def test_the_standard_model_is_named_by_its_record():
    doc = documented_doc()
    doc["stages"]["intake"]["target"] = "MAINBL10 + PERCBL1U - bus 100001, load '1'"
    assert summarize(doc, ".").model == "PERC1 standard"


def test_warnings_are_plain_text():
    doc = documented_doc()
    doc["families"]["undervoltage"]["failures"] = 2
    assert "Undervoltage ride-through: 2 run(s) failed or were unstable" in summary_warnings(doc)


def test_measured_behaviour_groups_neighbouring_values():
    rows = measured_rows(documented_doc())
    assert ("Undervoltage 0–0.1 pu", "trips after", "0.180–0.196 s") in rows
    assert ("Undervoltage 0.6–0.7 pu", "trips after", "0.503–0.517 s") in rows
    assert ("Overvoltage 1.25–1.3 pu", "trips after", "2.008–2.064 s") in rows
    assert ("Overvoltage 1.05–1.2 pu", "rides through", "whole tested range") in rows
    assert rows[-1] == ("Reconnection", "between 1.00 and 1.05 pu", "delay 60.7 s · ramp 28.8 s")


# --- tolerance curve -------------------------------------------------------------------------------------------


def test_the_measured_boundary_is_stepped_from_the_tested_values():
    bands = measured_boundary(documented_doc(), "undervoltage")
    assert [(b.lo, b.hi) for b in bands][:3] == [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)]
    assert bands[-1].lo == 0.9 and bands[-1].hi == 1.0  # the last band runs to nominal
    assert all(b.tag == b.lo for b in bands)  # each uses the boundary at its lower voltage
    over = measured_boundary(documented_doc(), "overvoltage")
    assert (over[0].lo, over[0].hi, over[0].tag) == (1.0, 1.05, 1.05) and over[0].rides_all
    assert over[0].ride_through_s == 20.0


def test_ercot_falls_short_at_exactly_three_undervoltage_bands():
    doc = documented_doc()
    uv = shortfalls(measured_boundary(doc, "undervoltage"), ERCOT)
    assert [(f.lo, f.hi) for f in uv] == [(0.5, 0.6), (0.8, 0.9), (0.9, 1.0)]
    assert (uv[0].model_s, uv[0].required_s) == (0.432, 0.5)
    assert uv[1].required_s == 2.0 and math.isinf(uv[2].required_s)
    assert uv[2].label() == "trips after 2.18 s"
    assert shortfalls(measured_boundary(doc, "overvoltage"), ERCOT) == []


def test_the_caption_is_generated_from_the_shortfalls():
    doc = documented_doc()
    falls = shortfalls(measured_boundary(doc, "undervoltage"), ERCOT)
    assert stage_voltages(doc)[:4] == [0.2, 0.5, 0.8, 0.9]
    text = caption(doc, ERCOT, falls)
    assert text.startswith("Short of ERCOT (NOGRR282) at three undervoltage bands, each starting at one of the "
                           "model's own stage voltages (0.5, 0.8, 0.9 pu)")
    assert "Each band uses the boundary measured at its lower voltage." in text
    assert "Overvoltage meets it." in text and text.endswith("The overlay needs no re-run.")
    assert caption(doc, None, []).startswith("Choose a standard to overlay.")


def test_a_standard_with_a_frequency_table_can_fall_short_in_frequency():
    doc = documented_doc()
    search = next(s for s in doc["families"]["frequency"]["searches"] if s["tag"] == 57.0)
    search["points"] = [[0.1, True], [1.0, True], [2.0, False], [60.0, False]]
    falls = shortfalls(measured_boundary(doc, "frequency"), PJM)
    assert falls and falls[0].kind == "frequency" and falls[0].lo == 57.0
    assert shortfalls(measured_boundary(doc, "frequency"), ERCOT) == []  # no table: never a shortfall


def test_a_table_less_standard_says_so_for_frequency():
    assert frequency_note(ERCOT) == ("ERCOT (NOGRR282) has no frequency table in this app, so there is nothing to "
                                     "overlay here.")
    assert frequency_note(PJM) is None and frequency_note(None) is None


def test_the_overlay_offers_every_preset_with_data():
    assert overlay_presets(RIDE_THROUGH_PRESETS.values()) == list(RIDE_THROUGH_PRESETS.values())


def test_figures_without_and_with_an_overlay():
    doc = documented_doc()
    plain = tolerance_figure(doc, "voltage")
    assert [trace.name for trace in plain.data if trace.name] == ["Model rides through (measured)"]
    overlaid = tolerance_figure(doc, "voltage", ERCOT)
    names = [trace.name for trace in overlaid.data if trace.name]
    assert "ERCOT (NOGRR282) requires ride-through" in names and "Short of the standard" in names
    hatch = next(trace for trace in overlaid.data if trace.name == "Short of the standard")
    assert hatch.fillpattern.shape == "/"
    assert overlaid.layout.xaxis.type == "log"
    freq = tolerance_figure(doc, "frequency", ERCOT)  # no table: no requirement line, no shortfall
    assert not [trace for trace in freq.data if trace.name and "requires" in trace.name]
    assert any("not tested" in a.text for a in freq.layout.annotations)
    json.loads(overlaid.to_json())


def test_a_run_without_overvoltage_or_frequency_data_still_draws():
    doc = documented_doc()
    del doc["families"]["overvoltage"]
    assert tolerance_figure(doc, "voltage", ERCOT).data
    del doc["families"]["frequency"]
    assert tolerance_figure(doc, "frequency").layout.annotations[0].text == "Not tested in this run"


@pytest.mark.parametrize("kind", ["undervoltage", "overvoltage", "frequency"])
def test_no_band_is_interpolated(kind):
    doc = documented_doc()
    tags = {s["tag"] for s in doc["families"][kind]["searches"]}
    for band in measured_boundary(doc, kind):
        assert band.tag in tags


def test_a_run_read_by_a_relative_path_gets_an_absolute_folder(tmp_path, monkeypatch):
    """The report page cannot load a relative file URL (B5)."""
    write_run(tmp_path / "20261012-094100")
    monkeypatch.chdir(tmp_path)
    _doc, run = read_run("20261012-094100")
    assert run.folder.is_absolute()
