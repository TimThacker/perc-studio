"""PERC2 DLL v2.3 (`PERC2_v34/v35/v36_v2p3.dll`, ISO-NE): the PERC1 DLL with six more CONs.

`cons.py` has the 2-ICON + 179-CON layout, defaults and the checks measured in PSS/E 35.6.4 and 36.7.1; `dyr.py`
writes/parses the `PERCBL` record with header `12 IT 2 179 33 250 0`; `presets.py` carries a preset's PERC1 DLL bundle
over; `simulation.py` is the PERC1 DLL simulator with the v2.3 ramp rule and momentary cessation. Evidence:
the PSS/E validation library, which is not published.

Both DLLs register the model name PERCBL. The header's CON count (173 or 179) is what tells the two records apart, so
this model and `perc1_dll` each claim only their own count (`matches_dyr`).
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS, validate_cons
from .dyr import build_perc2_dll_dyr_block, is_perc2_dll_record, parse_perc2_dll_record
from .presets import cons_for_preset, preset_gaps
from .simulation import (
    simulate_perc2_dll_frequency_response,
    simulate_perc2_dll_response,
)

MODEL = LoadModel(
    id="perc2_dll",
    label="PERC2 DLL v2.3 (PSS/E v34-v36, ISO-NE)",
    description=(
        "The PERC1 DLL with a reactive-power lead-lag and its own reconnect band and ramps for momentary cessation "
        "(179 CONs). The voltage reconnect ramps (RAMPA, RAMPUA) last their CON times LFM."
    ),
    dyr_model_name="PERCBL",
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_perc2_dll_dyr_block,
    parse_dyr_record=parse_perc2_dll_record,
    simulate=simulate_perc2_dll_response,
    simulate_frequency=simulate_perc2_dll_frequency_response,
    cons_for_preset=cons_for_preset,
    dyr_model_aliases=("PERCOW", "PERCZN", "PERCAR", "PERCAL"),
    supports_record_scopes=True,
    matches_dyr=is_perc2_dll_record,
)

__all__ = ["MODEL", "preset_gaps", "validate_cons"]
