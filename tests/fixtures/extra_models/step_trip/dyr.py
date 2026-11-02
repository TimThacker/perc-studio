""".dyr writer and parser for the step-trip model: `IBUS 'USRLOD' 'ID' 'STPBL' 12 IT 0 4 1 1 0 CON(J) .. CON(J+3) /`."""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, format_con, get_record_scope, validate_load_id
from .cons import CON_NAMES

FAMILY = "STP"
MODEL_CODE = 12
N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED_ICON = 0, 4, 1, 1, 0

_SCOPE_BY_SUFFIX = {scope.suffix: scope for scope in RECORD_SCOPES.values()}
_RECORD_RE = re.compile(
    rf"(?P<number>\d+)\s+'USRLOD'\s+'(?P<id>[^']+)'\s+'{FAMILY}(?P<suffix>BL|OW|ZN|AR|AL)'\s+(?P<values>[^/]*)/"
)


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def build_step_trip_record(number, load_id, cons, scope="bus") -> str:
    validate_load_id(load_id)
    sc = get_record_scope(scope)
    header = f"{MODEL_CODE} {sc.it} {N_ICON} {N_CON} {N_STATE} {N_VAR} {N_RESERVED_ICON}"
    values = " ".join(format_con(cons[name]) for name in CON_NAMES)
    return f"@! {' '.join(CON_NAMES)}\n{number} 'USRLOD' '{load_id}' '{sc.model_name(FAMILY)}' {header} {values} /"


def parse_step_trip_records(dyr_text: str) -> list[dict]:
    """Every step-trip record in the text: scope, number, load_id and cons (`error` set when the CON count is wrong)."""
    records = []
    for match in _RECORD_RE.finditer(strip_comments(dyr_text)):
        values = [float(token) for token in match.group("values").split()[7:]]
        record = {"scope": _SCOPE_BY_SUFFIX[match.group("suffix")].id, "number": int(match.group("number")),
                  "load_id": match.group("id"), "cons": {}, "error": None}
        if len(values) == N_CON:
            record["cons"] = dict(zip(CON_NAMES, values))
        else:
            record["error"] = f"expected {N_CON} CON values, got {len(values)}"
        records.append(record)
    return records


def parse_step_trip_record(dyr_text: str) -> dict:
    records = parse_step_trip_records(dyr_text)
    if not records:
        raise ValueError(f"no {FAMILY}** record found")
    if records[0]["error"]:
        raise ValueError(records[0]["error"])
    return records[0]["cons"]


__all__ = [
    "FAMILY",
    "MODEL_CODE",
    "N_CON",
    "N_ICON",
    "N_RESERVED_ICON",
    "N_STATE",
    "N_VAR",
    "build_step_trip_record",
    "parse_step_trip_record",
    "parse_step_trip_records",
    "strip_comments",
]
