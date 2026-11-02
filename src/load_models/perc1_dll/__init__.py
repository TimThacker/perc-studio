"""PERC1 (Power Electronic Load Model), DLL variant for PSS/E v34/v35.

The project's primary model: `cons.py` holds the 173-CON layout and vendor
defaults, `dyr.py` writes/parses the `PERCBL` record, `presets.py` carries a
preset's PERC1 bundle over unchanged, and `simulation.py` is the analytic
response the live chart and mock runner use.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS
from .dyr import build_perc1_dll_record, is_perc1_dll_record, parse_perc1_dll_record
from .presets import cons_for_preset, preset_gaps
from .simulation import (
    simulate_perc1_dll_frequency_response,
    simulate_perc1_dll_response,
)


def _result_figure(result, cons, block_label, **kwargs):
    # Imported lazily: preview/perc1_dll.py imports this package, so a module-level
    # import here would be circular.
    from preview.perc1_dll import build_perc1_response_figure_from_result

    return build_perc1_response_figure_from_result(result, cons, block_label, **kwargs)


MODEL = LoadModel(
    id="perc1_dll",
    label="PERC1 (DLL, PSS/E v34/v35)",
    description=(
        "Power-electronics-interfaced load (UPS/IT, VFD) with voltage/frequency "
        "cease-and-reconnect and a 4-stage multi-stage trip table."
    ),
    dyr_model_name="PERCBL",
    dyr_model_aliases=("PERCOW", "PERCZN", "PERCAR", "PERCAL"),
    supports_record_scopes=True,
    # The PERC2 DLL v2.3 writes PERCBL too (with 179 CONs): see load_models/perc2_dll.
    matches_dyr=is_perc1_dll_record,
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_perc1_dll_record,
    parse_dyr_record=parse_perc1_dll_record,
    simulate=simulate_perc1_dll_response,
    simulate_frequency=simulate_perc1_dll_frequency_response,
    cons_for_preset=cons_for_preset,
    result_figure=_result_figure,
)

__all__ = ["MODEL", "preset_gaps"]
