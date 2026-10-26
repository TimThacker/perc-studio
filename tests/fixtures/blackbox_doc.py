"""A reduced validation document for the documented PERC1 DLL run on PSS/E 35.6 (Standard level, compared with
ERCOT NOGRR282). The brackets are the measured ones; the cases
are reduced to the bracketing pairs. The comparison is computed with the app's own scoring."""

from __future__ import annotations

import json
from pathlib import Path

from blackbox.protocol import overall_from
from blackbox.scoring import compare_family, overall
from load_models.perc1_dll.dyr import build_perc1_dyr_block
from presets.ridethrough import RIDE_THROUGH_PRESETS

# tag: (longest seen riding through, shortest seen tripping) in s; None = rode through everything run
UNDERVOLTAGE = {0.0: (0.180, 0.196), 0.1: (0.180, 0.196), 0.2: (0.262, 0.278), 0.3: (0.273, 0.289),
                0.4: (0.273, 0.289), 0.5: (0.432, 0.448), 0.6: (0.503, 0.517), 0.7: (0.503, 0.517),
                0.8: (0.672, 0.688), 0.9: (2.12, 2.18)}
OVERVOLTAGE = {1.05: None, 1.10: None, 1.15: None, 1.20: None, 1.25: (2.008, 2.064), 1.30: (2.008, 2.064)}
FREQUENCY = dict.fromkeys((57.0, 57.5, 58.0, 58.5, 59.0, 59.5, 60.5, 61.0, 61.5, 62.0))
MAX_V, MAX_F = 20.0, 60.0


def _search(tag, bracket, hi):
    lo = 1.0 / 60.0
    if bracket is None:
        points = [[lo, True], [hi, True]]
    else:
        ok, trip = bracket
        points = [[lo, True], [ok, True], [trip, False], [hi, False]]
    transitions = [] if bracket is None else [[bracket[0], bracket[1], True]]
    return {"tag": tag, "points": points, "transitions": transitions, "monotonic": True,
            "all_good": bracket is None}


def _family(kind, title, values, unit, outer_name, hi, inner_unit="s"):
    return {"title": title, "kind": kind, "description": "", "outer_name": outer_name, "outer_unit": unit,
            "inner": {"name": "duration", "unit": inner_unit, "lo": 1.0 / 60.0, "hi": hi},
            "searches": [_search(tag, b, hi) for tag, b in values.items()], "failures": 0}


def placed_record() -> str:
    """The ERCOT bundle's PERC1 DLL record as the rig places it (`{BUS}` for the bus)."""
    text = build_perc1_dyr_block(100001, "1", RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    return text.replace("100001", "{BUS}", 1)


def documented_doc(preset_ids=("ercot_nogrr282",)) -> dict:
    families = {
        "undervoltage": _family("undervoltage", "Undervoltage ride-through", UNDERVOLTAGE, "pu", "sag depth", MAX_V),
        "overvoltage": _family("overvoltage", "Overvoltage ride-through", OVERVOLTAGE, "pu", "swell level", MAX_V),
        "frequency": _family("frequency", "Frequency ride-through", FREQUENCY, "Hz", "frequency", MAX_F),
        "recovery": {"title": "Reconnection window", "kind": "recovery", "outer_unit": "", "searches": [],
                     "reconnections": [{"recovery_pu": 1.0, "reconnected": True, "delay_s": 60.7, "ramp_s": 28.8,
                                        "key": "r1"},
                                       {"recovery_pu": 1.048, "reconnected": True, "delay_s": 60.7, "ramp_s": 28.8,
                                        "key": "r2"},
                                       {"recovery_pu": 0.95, "reconnected": False, "key": "r3"}]},
    }
    maxima = {"undervoltage": MAX_V, "overvoltage": MAX_V, "frequency": MAX_F}
    comparison = {}
    for pid in preset_ids:
        preset = RIDE_THROUGH_PRESETS[pid]
        per = {}
        for kind in ("undervoltage", "overvoltage", "frequency"):
            if kind == "frequency" and preset.frequency_ride_through is None:
                per[kind] = {"overall": "no requirement", "points": [],
                             "note": "this preset publishes no frequency ride-through table"}
                continue
            verdicts = compare_family(preset, kind, families[kind]["searches"], maxima[kind])
            per[kind] = {"overall": overall(verdicts), "points": [v.to_dict() for v in verdicts]}
        comparison[pid] = {"label": preset.label, "families": per, "overall": overall_from(per)}
    return {
        "schema": 1, "app_version": "1.1.0", "generated": "2026-10-12 09:41:00",
        "setup": {"level": "standard", "level_title": "Standard", "presets": [], "dyr_name": "perc1_dll_ercot.dyr",
                  "dlls": ["C:/models/PERC2_V35.dll"], "p_mw": 100.0, "q_mvar": 20.0, "forced_delt": None},
        "environment": {"selection": {"version": "35.6", "install_dir": "C:/Program Files/PTI/PSSE35/35.6",
                                      "python_exe": "python.exe", "pspy_folder": "PSSPY311"},
                        "psse": {"major": 35, "minor": 6, "patch": 4}, "python": "3.11.9"},
        "stages": {"intake": {"target": "PERC1 - bus 100001, load '1'", "placed_records": [placed_record()],
                              "flags": []},
                   "robustness": {"cadence": {"warning": "Depends on how the study steps: the reconnect ramp takes "
                                                         "14.4 s when run() is called every step, against 28.8 s."}}},
        "families": families, "comparison": comparison, "diagnosis": [], "points": [], "stopped": None,
        "stats": {"cases_run": 396, "cases_cached": 0, "wall_seconds": 1924.0, "delt": 0.004166667,
                  "prompt_window_s": 0.5, "workers": 4},
    }


def write_run(folder: Path, doc: dict | None = None, *, cases: int = 2) -> Path:
    """A run folder with the document and a few case folders holding a channel file."""
    folder = Path(folder)
    for i in range(cases):
        case = folder / "work" / "cache" / f"case{i}"
        case.mkdir(parents=True, exist_ok=True)
        (case / "case.outx").write_bytes(b"")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "validation.json").write_text(json.dumps(doc or documented_doc()), encoding="utf-8")
    (folder / "report.html").write_text("<html><body>report</body></html>", encoding="utf-8")
    return folder
