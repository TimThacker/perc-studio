"""Step-trip model: one undervoltage and one overvoltage trip point, no reconnect.

`cons.py` holds the four CONs, `dyr.py` writes and parses the `STPBL` record, `simulation.py` is the analytic response
and `presets.py` collapses a ride-through preset to its most demanding point per direction.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS
from .dyr import build_step_trip_record, parse_step_trip_record
from .presets import cons_for_preset, preset_gaps
from .simulation import simulate_step_trip_response

MODEL = LoadModel(
    id="step_trip",
    label="Step-trip model",
    description="Single undervoltage and overvoltage trip point, no reconnect.",
    dyr_model_name="STPBL",
    dyr_model_aliases=("STPOW", "STPZN", "STPAR", "STPAL"),
    supports_record_scopes=True,
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_step_trip_record,
    parse_dyr_record=parse_step_trip_record,
    simulate=simulate_step_trip_response,
    cons_for_preset=cons_for_preset,
)

__all__ = ["MODEL", "preset_gaps"]
