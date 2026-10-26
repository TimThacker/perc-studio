"""PERC2 standard variant: PSS/E 36.7's built-in PERCxx2U load component model.

`cons.py` has the 6-flag + 57-CON layout, defaults and the limits measured in PSS/E 36.7.1; `dyr.py` writes/parses
the MAINxx10 + PERCxx2U records; `presets.py` maps ride-through presets onto the model's momentary, long and frequency
checks; `simulation.py` is an analytic stand-in (the cease/reconnect machine, exponents, current limits, droop; no
washout or lead-lag transients) checked against PSS/E traces in the PSS/E validation library, which is not published.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS, validate_cons
from .dyr import build_perc2_standard_dyr_block, parse_perc2_standard_record
from .presets import cons_for_preset, preset_gaps
from .simulation import (
    simulate_perc2_standard_frequency_response,
    simulate_perc2_standard_response,
)

MODEL = LoadModel(
    id="perc2_standard",
    label="PERC2 standard (PSS/E 36.7+, built in)",
    description=(
        "PSS/E's built-in power-electronic load component model with voltage and frequency based ceasing (PERCxx2U): "
        "momentary and 4-point long low/high-voltage cease with their own reconnect settings, a frequency cease that "
        "never reconnects, droop, voltage exponents and P-priority current limits."
    ),
    dyr_model_name="PERCBL2U",
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_perc2_standard_dyr_block,
    parse_dyr_record=parse_perc2_standard_record,
    dyr_model_aliases=("PERCOW2U", "PERCZN2U", "PERCAR2U", "PERCAL2U"),
    supports_record_scopes=True,
    simulate=simulate_perc2_standard_response,
    simulate_frequency=simulate_perc2_standard_frequency_response,
    cons_for_preset=cons_for_preset,
)

__all__ = ["MODEL", "preset_gaps", "validate_cons"]
