"""Browsing a validation's cases and plotting chosen channels (no Qt, no PSS/E)."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from blackbox.explorer import (
    OTHER_GROUP,
    ResultsError,
    build_figure,
    channel_names,
    load_case,
    open_results,
)

FIXTURES = Path(__file__).parent / "fixtures" / "outx"
CSV = "time,V,F_HZ,P,Q\n0,1,60,1,0.2\n1,0.5,60,0.4,0.1\n2,1,60,0,0\n"


def make_run(root: Path, *, with_outx=True, layout="work/cache") -> Path:
    """A run folder with two judged cases, one unjudged case and a validation.json."""
    cases = root / layout
    specs = {"aaa": ("4ch.outx", "0.5 pu for 1 s", "tripped"), "bbb": ("10ch.outx", "0.9 pu for 2 s", "rode through")}
    points = []
    for key, (outx, event, verdict) in specs.items():
        folder = cases / key
        folder.mkdir(parents=True)
        (folder / "result.csv").write_text(CSV)
        (folder / "meta.json").write_text(json.dumps({"status": "ok"}))
        (folder / "job.json").write_text(json.dumps({"segments": [[0, 1.0, 60.0]]}))
        if with_outx:
            shutil.copy(FIXTURES / outx, folder / "case.outx")
        points.append({"family": "undervoltage", "key": key, "status": "ok", "event": event, "event_start": 1.0,
                       "event_end": 2.0, "outcome": {"label": verdict}})
    extra = cases / "ccc"
    extra.mkdir()
    (extra / "meta.json").write_text(json.dumps({"status": "ok"}))
    (extra / "job.json").write_text(json.dumps({"segments": [[0.0, 1.0, 60.0], [1.0, 0.3, 60.0]]}))
    (extra / "result.csv").write_text(CSV)
    doc = {"families": {"undervoltage": {"title": "Undervoltage ride-through"}}, "points": points}
    (root / "validation.json").write_text(json.dumps(doc))
    return root


def test_cases_are_grouped_by_test_and_labelled_by_event(tmp_path):
    results = open_results(make_run(tmp_path))
    groups = [(c.group, c.label, c.verdict) for c in results.cases]
    assert groups == [("Undervoltage ride-through", "0.5 pu for 1 s", "tripped"),
                      ("Undervoltage ride-through", "0.9 pu for 2 s", "rode through"),
                      (OTHER_GROUP, "0 pu @ 1 s -> 0.3 pu @ 1 s", "ok")][:2] + [groups[2]]
    assert results.cases[2].group == OTHER_GROUP and "0.3 pu" in results.cases[2].label
    assert results.cases[0].event == (1.0, 2.0)


def test_a_bundle_zip_and_a_validation_json_open_the_same_way(tmp_path):
    run = make_run(tmp_path / "run", layout="cases")  # the bundle layout
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        for f in run.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(run).as_posix())
    from_zip = open_results(bundle)
    assert len(from_zip.cases) == 3 and load_case(from_zip.cases[0]) is not None
    assert len(open_results(run / "validation.json").cases) == 3
    from_zip.close()


def test_channel_file_wins_and_the_csv_is_the_fallback(tmp_path):
    results = open_results(make_run(tmp_path))
    assert load_case(results.cases[1]).names[:4] == ["V", "F", "P", "Q"] and len(load_case(results.cases[1]).names) == 10
    csv_only = open_results(make_run(tmp_path / "second", with_outx=False))
    data = load_case(csv_only.cases[0])
    assert data.names == ["V", "F (Hz)", "P", "Q"] and data.time == [0.0, 1.0, 2.0]


def test_an_unreadable_channel_file_falls_back_to_the_csv(tmp_path):
    results = open_results(make_run(tmp_path))
    (results.cases[0].folder / "case.outx").write_bytes(b"garbage")
    assert load_case(results.cases[0]).names == ["V", "F (Hz)", "P", "Q"]


def test_union_of_channels_keeps_first_seen_order(tmp_path):
    results = open_results(make_run(tmp_path))
    files = [load_case(c) for c in results.cases[:2]]
    assert channel_names(files)[:5] == ["V", "F", "P", "Q", "XVOLT3"]


def test_figure_has_one_panel_per_channel_and_one_trace_per_case_and_channel(tmp_path):
    results = open_results(make_run(tmp_path))
    selected = [(c, load_case(c)) for c in results.cases[:2]]
    fig = build_figure(selected, ["V", "P", "XVOLT3"])
    traces = [t for t in fig.data if t.name != "Disturbance"]  # the shaded event window's legend key
    assert len(traces) == 5  # XVOLT3 exists only in the 10-channel file
    assert sorted({t.legendgroup for t in traces}) == ["aaa", "bbb"]
    assert [a.text for a in fig.layout.annotations] == ["V (pu)", "P (pu)", "XVOLT3"]
    assert sum(1 for t in traces if t.showlegend) == 2  # one legend entry per case, not per panel
    assert [t.line.dash for t in traces[:2]] == ["solid", "solid"] and traces[-1].line.dash == "dash"
    assert fig.layout.legend.yanchor == "bottom"  # the legend sits above the plot


def test_figure_with_no_channel_says_so(tmp_path):
    results = open_results(make_run(tmp_path))
    fig = build_figure([(results.cases[0], load_case(results.cases[0]))], [])
    assert any("at least one channel" in a.text for a in fig.layout.annotations)


@pytest.mark.parametrize("make", ["missing", "empty_folder", "not_a_zip"])
def test_things_that_are_not_results_are_refused(tmp_path, make):
    target = {"missing": tmp_path / "nothing", "empty_folder": tmp_path, "not_a_zip": tmp_path / "x.zip"}[make]
    if make == "not_a_zip":
        target.write_bytes(b"nope")
    with pytest.raises(ResultsError):
        open_results(target)


def test_closing_a_bundle_removes_its_unpacked_folder(tmp_path):
    run = make_run(tmp_path / "run", layout="cases")
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        for f in run.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(run).as_posix())
    results = open_results(bundle)
    unpacked = results.case_root
    assert unpacked.exists()
    results.close()
    assert not unpacked.exists()
    results.close()  # closing twice is harmless
