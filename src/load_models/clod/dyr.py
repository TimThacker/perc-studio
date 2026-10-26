"""CLOD .dyr record writer."""

from ..base import get_record_scope, validate_load_id


def clod_record(bus_number, load_id, params, scope="bus"):
    """One CLOD record. Like PERC1, the model name carries the record's scope
    (CLODBL/CLODOW/CLODZN/CLODAR/CLODAL - "BL" is Bus, not "baseline")."""
    validate_load_id(load_id)
    model_name = get_record_scope(scope).model_name("CLOD")
    fields = [
        f"{bus_number}", f"'{model_name}'", f"'{load_id}'",
        f"{params['PC_LM']:.2f}", f"{params['PC_SM']:.2f}",
        f"{params['PC_TX']:.2f}", f"{params['PC_DL']:.2f}", f"{params['PC_CP']:.2f}",
    ]
    return "   " + ", ".join(fields) + "  /"
