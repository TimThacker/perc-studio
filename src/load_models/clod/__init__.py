"""CLOD (PSS/E composite motor load), used for the optional cooling-motor block.

Export-only: CLOD has no parser, simulator, or ride-through envelope in this
app, so it can be stored and written to `.dyr` but not mock-run or validated.
`cons.py` has the five composition CONs and the facility-archetype derivation;
`dyr.py` writes the `CLODxx` record.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS, derive_clod_params
from .dyr import build_clod_record

MODEL = LoadModel(
    id="clod",
    label="CLOD (composite motor load)",
    description="PSS/E's composite motor load, parameterized by share of large/small motors, "
    "transformer exciting current, discharge lighting and constant power.",
    dyr_model_name="CLODBL",
    dyr_model_aliases=("CLODOW", "CLODZN", "CLODAR", "CLODAL"),
    supports_record_scopes=True,
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_clod_record,
)

__all__ = ["MODEL", "derive_clod_params"]
