"""PERC1 standard variant: PSS/E 36.7's built-in PERCxx1U load component model.

Not the DLL model in `perc1_dll`. `cons.py` has the 30-CON layout, defaults and
the validated limits; `dyr.py` writes/parses the MAINxx10 + PERCxx1U records;
`presets.py` maps ride-through presets onto the one cease/reconnect cycle the
model has. `simulation.py` is an analytic stand-in (cease/reconnect logic,
exponents, current limits, droop; no washout or lead-lag transients) checked
against PSS/E traces in the PSS/E validation library, which is not published.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS, validate_cons
from .dyr import build_perc1_standard_dyr_block, parse_perc1_standard_record
from .presets import cons_for_preset, preset_gaps
from .simulation import (
    simulate_perc1_standard_frequency_response,
    simulate_perc1_standard_response,
)

MODEL = LoadModel(
    id="perc1_standard",
    label="PERC1 standard (PSS/E 36.7+, built in)",
    description=(
        "PSS/E's built-in power-electronic load component model (PERCxx1U): one undervoltage cease/reconnect "
        "cycle, droop, voltage exponents and current limits. No overvoltage, frequency or multi-stage trips."
    ),
    dyr_model_name="PERCBL1U",
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_perc1_standard_dyr_block,
    parse_dyr_record=parse_perc1_standard_record,
    dyr_model_aliases=("PERCOW1U", "PERCZN1U", "PERCAR1U", "PERCAL1U"),
    supports_record_scopes=True,
    simulate=simulate_perc1_standard_response,
    simulate_frequency=simulate_perc1_standard_frequency_response,
    cons_for_preset=cons_for_preset,
    unmodelled_events=("overvoltage", "frequency"),
)

__all__ = ["MODEL", "preset_gaps", "validate_cons"]
