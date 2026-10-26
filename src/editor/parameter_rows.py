"""The parameter rows of a block: one row per field group of the model, each with a
one-line summary of its current values ("UV 0.70 pu · 0.02 s").

Qt-free. The rows are the model's `ModelUiSpec.field_groups` (so a row's detail editor
shows the same sections the group always had); this module adds the row id, the
member CONs and the summary text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from editor.model_ui import (
    DLL_MODEL_ID,
    PERC2_DLL_MODEL_ID,
    PERC2_MODEL_ID,
    STANDARD_MODEL_ID,
    ModelUiSpec,
    get_ui_spec,
)


@dataclass(frozen=True)
class ParameterRow:
    id: str
    title: str
    cons: tuple[str, ...]
    sections: tuple[tuple[str | None, tuple[str, ...]], ...]  # (subtitle or None, CONs), in display order
    note: str | None = None

    def summary(self, model_id: str, values: dict) -> str:
        formatter = _SUMMARIES.get(model_id, {}).get(self.id)
        if formatter is None:
            return ""
        try:
            return formatter(values)
        except (KeyError, TypeError, ValueError):
            return ""


def row_id(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def rows_for(spec_or_model: ModelUiSpec | str) -> list[ParameterRow]:
    spec = get_ui_spec(spec_or_model) if isinstance(spec_or_model, str) else spec_or_model
    rows = []
    for group in spec.field_groups:
        title, content = group[0], group[1]
        note = group[2] if len(group) > 2 else None
        if content and isinstance(content[0], tuple):
            sections = tuple((sub, tuple(names)) for sub, names in content)
        else:
            sections = ((None, tuple(content)),)
        cons = tuple(name for _sub, names in sections for name in names)
        rows.append(ParameterRow(row_id(title), title, cons, sections, note))
    return rows


def row_for_con(rows: list[ParameterRow], con: str) -> ParameterRow | None:
    return next((row for row in rows if con in row.cons), None)


# --- summaries ---------------------------------------------------------------------------------------


def _num(value, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def _short(value) -> str:
    """1.0 -> "1.0", 1.25 -> "1.25", 0 -> "0"."""
    value = float(value)
    if value == int(value):
        return f"{int(value)}" if abs(value) >= 10 or value == 0 else f"{value:.1f}"
    return f"{value:g}"


def _dll_voltage(v: dict) -> str:
    return f"UV {_num(v['VDPA'])} pu · {_num(v['DMA'])} s"


def _dll_frequency(v: dict) -> str:
    return f"{float(v['FUFTP1']):.1f}–{float(v['FOFTP1']):.1f} Hz"


def _fractions(cease: str, recon: str) -> Callable[[dict], str]:
    return lambda v: f"{_num(v[cease])} / {_num(v[recon])}"


_PERC2_FLAGS = (("VLMflag", "VLM"), ("VHMflag", "VHM"), ("VLLflag", "VLL"), ("VLHflag", "VLH"), ("FLflag", "FL"),
                ("FHflag", "FH"))


def _perc2_flags(v: dict) -> str:
    on = [short for name, short in _PERC2_FLAGS if round(float(v[name])) == 1]
    return " · ".join(on) if on else "all off"


def _perc2_long(prefix: str, flag: str) -> Callable[[dict], str]:
    def text(v: dict) -> str:
        if round(float(v[flag])) != 1:
            return "off"
        return f"V{prefix}C1 {_num(v[f'V{prefix}C1'])} pu · {_short(v[f'TV{prefix}C1'])} s"
    return text


def _perc2_dll_mc(v: dict) -> str:
    if round(float(v["MCFLAG"])) != 1:
        return "off"
    return f"below {_num(v['VLBLK'])} / above {_num(v['VUBLK'])} pu"


_DLL_SUMMARIES: dict[str, Callable[[dict], str]] = {
    "voltage_ride_through": _dll_voltage,
    "frequency_ride_through": _dll_frequency,
    "trip_reconnect_fractions": _fractions("FCEASE", "FRECON"),
    "load_voltage_response": lambda v: f"NPA {round(float(v['NPA']))}",
    "frequency_droop": lambda v: f"DROOPA {_short(v['DROOPA'])}",
    "current_limits": lambda v: f"IPMAX {_short(v['IPMAXA'])}",
}

_SUMMARIES: dict[str, dict[str, Callable[[dict], str]]] = {
    DLL_MODEL_ID: _DLL_SUMMARIES,
    PERC2_DLL_MODEL_ID: {
        **_DLL_SUMMARIES,
        "momentary_cessation": _perc2_dll_mc,
        "reactive_lead_lag": lambda v: f"TAQ {_short(v['TAQ'])} · TBQ {_short(v['TBQ'])}",
        "system_and_load_basis": lambda v: (f"{50 if round(float(v['FREQ50'])) == 1 else 60} Hz · "
                                            f"LFM {_short(v['LFM'])}"),
    },
    STANDARD_MODEL_ID: {
        "voltage_ride_through": lambda v: f"Vcease {_num(v['Vcease'])} pu · {_num(v['Tcease'])} s",
        "load_voltage_response": lambda v: f"nP {_short(v['nP'])} · nQ {_short(v['nQ'])}",
        "current_limits": lambda v: f"Ipmax {_short(v['Ipmax'])}",
        "frequency_droop": lambda v: f"Kdroop {_short(v['Kdroop'])}",
    },
    PERC2_MODEL_ID: {
        "ride_through_checks": _perc2_flags,
        "voltage_ride_through": lambda v: f"VLcease {_num(v['VLcease'])} pu · {_num(v['Tcease'])} s",
        "long_low_voltage_ride_through": _perc2_long("L", "VLLflag"),
        "long_high_voltage_ride_through": _perc2_long("H", "VLHflag"),
        "frequency_ride_through": lambda v: f"{float(v['FLC1']):.1f}–{float(v['FHC1']):.1f} Hz",
        "load_voltage_response": lambda v: f"nP {_short(v['nP'])} · nQ {_short(v['nQ'])}",
        "current_limits": lambda v: f"Ipmax {_short(v['Ipmax'])} · Imax {_short(v['Imax'])}",
        "frequency_droop": lambda v: f"Kdroop {_short(v['Kdroop'])}",
    },
}
