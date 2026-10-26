"""PERC1 (Power Electronic Load Model), DLL variant for PSS/E v34/v35.

The project's primary model: `cons.py` holds the 173-CON layout and vendor
defaults, `dyr.py` writes/parses the `PERCBL` record, and `simulation.py` is
the analytic response the live chart and mock runner use.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import PERC1_CON_ORDER, PERC1_DEFAULT_CONS, PERC1_DISPLAY_FIELDS
from .dyr import build_perc1_dyr_block, is_perc1_dll_record, parse_perc1_dyr_block
from .simulation import simulate_perc1_frequency_response, simulate_perc1_response


def _cons_for_preset(preset, block_name: str) -> dict:
    """Ride-through presets already carry fully-resolved PERC1 bundles."""
    if block_name == "it":
        return dict(preset.it_bundle)
    if block_name == "vfd":
        return dict(preset.vfd_bundle)
    raise ValueError(f"ride-through presets define PERC1 CONs for blocks 'it' and 'vfd', not {block_name!r}")


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
    con_names=tuple(PERC1_CON_ORDER),
    default_cons=dict(PERC1_DEFAULT_CONS),
    display_fields=tuple(PERC1_DISPLAY_FIELDS),
    build_dyr_record=build_perc1_dyr_block,
    parse_dyr_record=parse_perc1_dyr_block,
    simulate=simulate_perc1_response,
    simulate_frequency=simulate_perc1_frequency_response,
    cons_for_preset=_cons_for_preset,
    result_figure=_result_figure,
    dyr_model_aliases=("PERCOW", "PERCZN", "PERCAR", "PERCAL"),
    supports_record_scopes=True,
    # The PERC2 DLL v2.3 writes PERCBL too (with 179 CONs): see load_models/perc2_dll.
    matches_dyr=is_perc1_dll_record,
)
