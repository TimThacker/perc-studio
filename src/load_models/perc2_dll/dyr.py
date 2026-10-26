"""`.dyr` writer/parser for the PERC2 DLL v2.3 (`PERC2_v3x_v2p3.dll`).

The record is the PERC1 DLL's with 179 CONs:

    IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 179 33 250 0  ICON(M) ICON(M+1)  CON(J) .. CON(J+178) /

`**`/IT are the record scope (BL 1, OW 2, ZN 3, AR 4, AL 5). The vendor document's own "DYRE FORMAT" section still
says 173 CONs; that is the PERC1 DLL's count, and a 173-CON record on the v2.3 DLL leaves the six new CONs undefined
(measured in PSS/E). Both DLLs register the model name `PERCBL`, so the header's CON count is
the only thing that tells the two records apart.
"""

from __future__ import annotations

from ..base import format_con, get_record_scope, validate_load_id
from ..perc1_dll.dyr import parse_perc1_records
from .cons import (
    CON_NAMES,
    CON_ONLY_NAMES,
    DYR_LAYOUT,
    ICON_NAMES,
    ZIP_FIELDS,
    validate_cons,
)

N_CON = 179
HEADER = (12, 2, N_CON, 33, 250, 0)  # model type, NICON, NCON, NSTATE, NVAR, reserved; IT goes after the 12


def build_perc2_dll_dyr_block(number, load_id, cons, scope="bus", *, description=None) -> str:
    """One PERC2 v2.3 record: the PERC1 DLL's row groups plus the three v2.3 rows, header `12 IT 2 179 33 250 0`, the
    two ICONs on their own line. Raises ValueError for values `validate_cons` marks as errors."""
    validate_load_id(load_id)
    sc = get_record_scope(scope)
    bad = [i for i in validate_cons(cons) if i.level == "error"]
    if bad:
        raise ValueError("; ".join(f"{i.con}: {i.message}" for i in bad))
    first = {"bus": "ibus", "all": "0 (all)"}.get(sc.id, f"i{sc.id}")
    lines = [f"@! PERC2 DLL v2.3 (PERC2_v3x_v2p3.dll){': ' + description if description else ''}",
             f"@! {first}  LID  IT",
             f"{number} 'USRLOD' '{load_id}' '{sc.model_name('PERC')}' 12 {sc.it} 2 {N_CON} 33 250 0",
             ("@! ICON(M) ICON(M+1)  [ICON(M): the document's 50 Hz flag, ignored by the DLL; ICON(M+1) = 1 enables "
              "momentary cessation]"),
             f" {int(cons['FREQ50'])} {int(cons['MCFLAG'])}"]
    for block in DYR_LAYOUT:
        lines.append("@! " + " ".join(block))
        lines.append(" " + " ".join(format_con(int(cons[n]) if n in ZIP_FIELDS else cons[n]) for n in block))
    lines[-1] += " /"
    return "\n".join(lines)


def _record_to_cons(record) -> dict:
    icons = record["icons"]
    out = {name: int(v) for name, v in zip(ICON_NAMES, icons)}
    out.update(record["cons"])
    out.update(record.get("v2p3_cons", {}))
    return out


def parse_perc2_dll_records(dyr_text: str) -> list[dict]:
    """Every PERC** record with the v2.3 header (179 CONs) in `dyr_text`, in file order: scope, number, load_id,
    placeholder, cons (flags + 179 CONs), error, position. 173-CON (PERC1 DLL) records are left out."""
    out = []
    for rec in parse_perc1_records(dyr_text):
        if rec.get("n_con") != N_CON:
            continue  # a PERC1 DLL (173-CON) record, or a header too broken to read
        r = dict(rec)
        r["cons"] = _record_to_cons(rec) if rec["error"] is None else {}
        r.pop("v2p3_cons", None)
        out.append(r)
    return out


def is_perc2_dll_record(dyr_text: str) -> bool:
    """True when `dyr_text` holds a PERC** record whose header gives 179 CONs (the v2.3 layout)."""
    return any(r.get("n_con") == N_CON for r in parse_perc1_records(dyr_text))


def parse_perc2_dll_record(dyr_text: str) -> dict:
    """The flags and 179 CONs of the single v2.3 record in `dyr_text`."""
    records = parse_perc2_dll_records(dyr_text)
    if len(records) != 1:
        raise ValueError(f"expected exactly one PERC2 v2.3 (179-CON) PERC** record, found {len(records)}")
    if records[0]["error"]:
        raise ValueError(records[0]["error"])
    cons = records[0]["cons"]
    missing = [n for n in CON_NAMES if n not in cons]
    if missing:
        raise ValueError(f"parsed record is missing {missing}")
    return {n: cons[n] for n in CON_NAMES}


__all__ = ["CON_ONLY_NAMES", "build_perc2_dll_dyr_block", "is_perc2_dll_record", "parse_perc2_dll_record",
           "parse_perc2_dll_records"]
