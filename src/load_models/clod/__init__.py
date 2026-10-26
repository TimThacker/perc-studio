"""CLOD (PSS/E composite motor load), used for the optional cooling-motor block.

Export-only: CLOD has no parser, simulator, or ride-through envelope in this
app, so it can be stored and written to `.dyr` but not mock-run or validated.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CLOD_DISPLAY_FIELDS, derive_clod_params
from .dyr import clod_record

MODEL = LoadModel(
    id="clod",
    label="CLOD (composite motor load)",
    description="PSS/E's composite motor load, parameterized by share of large/small motors, "
    "transformer exciting current, discharge lighting and constant power.",
    dyr_model_name="CLODBL",
    con_names=tuple(name for name, _ in CLOD_DISPLAY_FIELDS),
    default_cons=derive_clod_params("Mixed - moderate mix of large & small motors", False),
    display_fields=tuple(CLOD_DISPLAY_FIELDS),
    build_dyr_record=clod_record,
    dyr_model_aliases=("CLODOW", "CLODZN", "CLODAR", "CLODAL"),
    supports_record_scopes=True,
)
