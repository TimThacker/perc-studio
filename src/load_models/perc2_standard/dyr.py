"""`.dyr` writer/parser for the PERC2 standard model (PSS/E 36.7 PERCxx2U).

The record (data sheet, "DYR Syntax") is

    IBUS 'USRLODC' ID 'PERCxx2U' 230 IT 6 57 8 44 16 CompNum 'CompDesc' ICON(M) to ICON(M+5) CON(J) to CON(J+56) /

The six numbers after IT are NICON, NCON, NSTATE, NVAR and the reserved-ICON count; the six flags are written
before the CONs. Like PERCxx1U, the record is a component of PSS/E's composite load: it only applies to a load that
also has a `MAINxx10` record of the same scope and id above it, and a load that is only partly PERC2 needs a static
remainder with load fraction -1 (every number below was measured in PSS/E 36.7.1).
"""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, get_record_scope, validate_load_id
from ..perc1_standard.dyr import (
    MAX_COMPONENTS,
    STATIC_REMAINDER_CONS,
    _main_record,
    _strip_comments,
    format_value,
)
from .cons import CON_NAMES, CON_ONLY_NAMES, ICON_NAMES, validate_cons

MODEL_CODE = 230
N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED_ICON = 6, 57, 8, 44, 16
FAMILY = "PERC"
VERSION_SUFFIX = "2U"


def perc2_model_name(scope: str) -> str:
    return f"{FAMILY}{get_record_scope(scope).suffix}{VERSION_SUFFIX}"


def format_flag(value) -> str:
    return str(round(float(value)))


def build_perc2_standard_dyr_block(number, load_id, cons, scope="bus", *, load_fraction=1.0, component=1,
                                   description="PERC2 load") -> str:
    """The complete record set for one load: the main component, the PERC2 component and - only when
    `load_fraction` < 1 - a static component for the rest. `number` is the records' first field
    (`base.record_number`). Raises ValueError for values PSS/E would reject or that make the record meaningless;
    values PSS/E merely adjusts are reported by `validate_cons`, not raised here."""
    validate_load_id(load_id)
    scope_obj = get_record_scope(scope)
    if not 1 <= component <= MAX_COMPONENTS:
        raise ValueError(f"component must be 1-{MAX_COMPONENTS}, got {component}")
    if not 0 < load_fraction <= 1:
        raise ValueError(f"load_fraction must be in (0, 1], got {load_fraction}")
    bad = [i for i in validate_cons(cons) if i.level == "error"]
    if bad:
        raise ValueError("; ".join(f"{i.con}: {i.message}" for i in bad))
    description = description.replace("'", "")

    other = 2 if component == 1 else 1
    fractions = {component: float(load_fraction)}
    lines = [f"@! PERC2 standard (PSS/E 36.7 {perc2_model_name(scope)}): main component + PERC2 component"
             + (" + static remainder" if load_fraction < 1 else ""),
             f"@! PERC2 ICONs: {' '.join(ICON_NAMES)}",
             f"@! PERC2 CONs: {' '.join(CON_ONLY_NAMES)}"]
    if load_fraction < 1:
        fractions[other] = -1.0
    lines.append(_main_record(number, load_id, scope, fractions))
    flags = " ".join(format_flag(cons[n]) for n in ICON_NAMES)
    values = [format_value(cons[n]) for n in CON_ONLY_NAMES]
    # Ten CONs per continuation line keeps the record readable; PSS/E reads a record to its '/'.
    body = "\n    ".join(" ".join(values[i:i + 10]) for i in range(0, len(values), 10))
    lines.append(f"{number} 'USRLODC' '{load_id}' '{perc2_model_name(scope)}' {MODEL_CODE} {scope_obj.it} {N_ICON} "
                 f"{N_CON} {N_STATE} {N_VAR} {N_RESERVED_ICON} {component} '{description}' {flags}\n    {body} /")
    if load_fraction < 1:
        lines.append(f"{number} 'LSTC{scope_obj.suffix}' '{load_id}' {other} 'Static remainder' "
                     f"{' '.join(format_value(v) for v in STATIC_REMAINDER_CONS)} /")
    return "\n".join(lines)


_NAMES = "|".join(f"{FAMILY}{s.suffix}{VERSION_SUFFIX}" for s in RECORD_SCOPES.values())
_PERC2_RE = re.compile(
    rf"(?P<number>\d+)\s+'USRLODC'\s+'(?P<id>[^']+)'\s+'(?P<model>{_NAMES})'\s+{MODEL_CODE}\s+(?P<it>[1-5])\s+{N_ICON}\s+"
    rf"{N_CON}\s+{N_STATE}\s+{N_VAR}\s+{N_RESERVED_ICON}\s+(?P<comp>\d+)\s+'(?P<desc>[^']*)'\s+(?P<values>[^/]*?)\s*/",
    re.DOTALL)
_MAIN_RE = re.compile(r"(?P<number>\d+)\s+'MAIN(?P<suffix>BL|OW|ZN|AR|AL)10'\s+'(?P<id>[^']+)'\s+(?P<values>[^/]*?)\s*/")


def _values_to_cons(tokens: list[str]) -> dict:
    flags = [round(float(t)) for t in tokens[:N_ICON]]
    cons = [float(t) for t in tokens[N_ICON:]]
    return {**dict(zip(ICON_NAMES, flags)), **dict(zip(CON_ONLY_NAMES, cons))}


def _scope_of(model_name: str) -> str:
    suffix = model_name[len(FAMILY):len(FAMILY) + 2]
    return next(s.id for s in RECORD_SCOPES.values() if s.suffix == suffix)


def parse_perc2_standard_record(dyr_text: str) -> dict:
    """The 6 flags and 57 CONs of the first PERCxx2U record in `dyr_text` (comment rows and continuation lines
    allowed)."""
    match = _PERC2_RE.search(_strip_comments(dyr_text))
    if match is None:
        raise ValueError("no PERCxx2U 'USRLODC' record with the standard header (230 IT 6 57 8 44 16) found")
    tokens = match.group("values").split()
    if len(tokens) != N_ICON + N_CON:
        raise ValueError(f"expected {N_ICON} flags and {N_CON} CON values, got {len(tokens)} values")
    return _values_to_cons(tokens)


def parse_perc2_standard_header(dyr_text: str) -> dict:
    """Scope, number, load id and component number of the first PERCxx2U record."""
    match = _PERC2_RE.search(_strip_comments(dyr_text))
    if match is None:
        raise ValueError("no PERCxx2U 'USRLODC' record found")
    return {"scope": _scope_of(match.group("model")), "number": int(match.group("number")),
            "load_id": match.group("id"), "component": int(match.group("comp")), "description": match.group("desc")}


def parse_perc2_standard_records(dyr_text: str) -> list[dict]:
    """Every PERCxx2U record in `dyr_text`, in file order, in the same shape as
    `perc1_standard.dyr.parse_perc1_standard_records`: scope, number, load_id, component, description, position, cons,
    error and `load_fraction` (from the matching MAINxx10 record; None when there is none)."""
    text = re.sub(r"'[^']*'|,", lambda m: " " if m.group(0) == "," else m.group(0), _strip_comments(dyr_text))
    mains = {}
    for main in _MAIN_RE.finditer(text):
        tokens = main.group("values").split()
        if len(tokens) >= 2 * MAX_COMPONENTS:
            mains[(int(main.group("number")), main.group("id"))] = [float(t) for t in tokens[-MAX_COMPONENTS:]]
    records = []
    for match in _PERC2_RE.finditer(text):
        header = {"scope": _scope_of(match.group("model")), "number": int(match.group("number")),
                  "load_id": match.group("id"), "component": int(match.group("comp")),
                  "description": match.group("desc"), "position": match.start()}
        fractions = mains.get((header["number"], header["load_id"]))
        header["load_fraction"] = (fractions[header["component"] - 1]
                                   if fractions and header["component"] <= MAX_COMPONENTS else None)
        tokens = match.group("values").split()
        if len(tokens) == N_ICON + N_CON:
            records.append({**header, "cons": _values_to_cons(tokens), "error": None})
        else:
            records.append({**header, "cons": {}, "error": f"expected {N_ICON + N_CON} values (6 flags + 57 CONs), "
                                                           f"got {len(tokens)}"})
    return records


__all__ = ["CON_NAMES", "build_perc2_standard_dyr_block", "parse_perc2_standard_header", "parse_perc2_standard_record",
           "parse_perc2_standard_records", "perc2_model_name"]
