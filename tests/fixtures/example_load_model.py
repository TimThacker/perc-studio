"""A minimal, complete load model used to prove the backend is model-agnostic.

`example_step_trip` is deliberately tiny - one undervoltage and one
overvoltage trip point, four CONs - but implements every `LoadModel` hook, so
the tests can run the full generate -> export -> mock run -> validate ->
report loop on a model that is not PERC1. It doubles as a copy-and-edit
template for docs/developer/ADDING_A_LOAD_MODEL.md.

It is registered only inside tests (see the `example_model` fixture in
tests/conftest.py), never in the app's built-in registry.
"""

from __future__ import annotations

import re

from load_models.base import FAULT_START, LoadModel, format_con, validate_load_id
from presets.ridethrough import collapsed_overvoltage_point, collapsed_point

DYR_MODEL_NAME = "STPTRP"
CON_NAMES = ("VUV", "TUV", "VOV", "TOV")
DEFAULT_CONS = {"VUV": 0.70, "TUV": 0.10, "VOV": 1.20, "TOV": 0.50}
DISPLAY_FIELDS = (
    ("VUV", "Undervoltage trip threshold (pu)"),
    ("TUV", "Undervoltage trip delay (s)"),
    ("VOV", "Overvoltage trip threshold (pu)"),
    ("TOV", "Overvoltage trip delay (s)"),
)


def build_dyr_record(bus_number, load_id, cons):
    validate_load_id(load_id)
    values = " ".join(format_con(cons[name]) for name in CON_NAMES)
    return f"@! {' '.join(CON_NAMES)}\n{bus_number} 'USRLOD' '{load_id}' '{DYR_MODEL_NAME}' {values} /"


_RECORD_RE = re.compile(rf"^\s*\d+\s+'USRLOD'\s+'[^']+'\s+'{DYR_MODEL_NAME}'\s+(.*?)\s*/\s*$", re.MULTILINE)


def parse_dyr_record(dyr_text):
    match = _RECORD_RE.search(dyr_text)
    if match is None:
        raise ValueError(f"no {DYR_MODEL_NAME} record found")
    values = [float(token) for token in match.group(1).split()]
    if len(values) != len(CON_NAMES):
        raise ValueError(f"expected {len(CON_NAMES)} CON values, got {len(values)}")
    return dict(zip(CON_NAMES, values))


def simulate(cons, fault_duration_s, fault_voltage_pu):
    """Trips the whole block if the event crosses a threshold for at least
    that threshold's delay; never reconnects."""
    if fault_voltage_pu <= cons["VUV"] and fault_duration_s >= cons["TUV"]:
        trip_type, delay = "undervoltage", cons["TUV"]
    elif fault_voltage_pu >= cons["VOV"] and fault_duration_s >= cons["TOV"]:
        trip_type, delay = "overvoltage", cons["TOV"]
    else:
        trip_type, delay = None, None
    fault_end = FAULT_START + fault_duration_s
    sim_end = fault_end + 1.0
    v_points = [(0.0, 1.0), (FAULT_START, 1.0), (FAULT_START, fault_voltage_pu),
                (fault_end, fault_voltage_pu), (fault_end, 1.0), (sim_end, 1.0)]
    if trip_type:
        trip_time = FAULT_START + delay
        p_points = [(0.0, 1.0), (trip_time, 1.0), (trip_time, 0.0), (sim_end, 0.0)]
        markers = {"trip_time": trip_time}
    else:
        p_points = [(0.0, 1.0), (sim_end, 1.0)]
        markers = {}
    return {"v_points": v_points, "p_points": p_points, "sim_end": sim_end,
            "trips": trip_type is not None, "trip_type": trip_type, "markers": markers}


def cons_for_preset(preset, block_name):
    """Collapse the preset's envelopes to their single most-demanding
    mandatory point per direction."""
    under = collapsed_point(preset.envelope)
    over = collapsed_overvoltage_point(preset.overvoltage_envelope)
    return {"VUV": under.voltage_pu, "TUV": under.min_duration_s,
            "VOV": over.voltage_pu, "TOV": over.min_duration_s if over.min_duration_s is not None else 2.0}


MODEL = LoadModel(
    id="example_step_trip",
    label="Example step-trip model",
    description="Single undervoltage and overvoltage trip point; test/template model only.",
    dyr_model_name=DYR_MODEL_NAME,
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_dyr_record,
    parse_dyr_record=parse_dyr_record,
    simulate=simulate,
    cons_for_preset=cons_for_preset,
)
