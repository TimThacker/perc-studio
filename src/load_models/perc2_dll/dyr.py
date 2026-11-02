"""`.dyr` writer/parser for the PERC2 DLL v2.3 (`PERC2_v3x_v2p3.dll`).

The record is the PERC1 DLL's with 179 CONs:

    IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 179 33 250 0  ICON(M) ICON(M+1)  CON(J) .. CON(J+178) /

`**`/IT are the record scope (BL 1, OW 2, ZN 3, AR 4, AL 5). The vendor document's own "DYRE FORMAT" section still
says 173 CONs; that is the PERC1 DLL's count, and a 173-CON record on the v2.3 DLL leaves the six new CONs undefined
(measured in PSS/E). Both DLLs register the model name `PERCBL`, so the header's CON count is
the only thing that tells the two records apart.
"""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, format_con, get_record_scope, validate_load_id
from .cons import (
    CON_NAMES,
    CON_ONLY_NAMES,
    DYR_LAYOUT,
    ICON_NAMES,
    ZIP_FIELDS,
    validate_cons,
)

FAMILY = "PERC"
MODEL_CODE = 12  # the first header number
N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED_ICON = 2, 179, 33, 250, 0
N_CON_V1 = 173  # CON(J)..CON(J+172) are the PERC1 DLL record's; the six v2.3 CONs follow
V2P3_EXTRA_CONS = ("TAQ", "TBQ", "RAMPAMC", "RAMPUAMC", "VLRCMC", "VURCMC")


def build_perc2_dll_record(number, load_id, cons, scope="bus", *, description=None) -> str:
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
             (f"{number} 'USRLOD' '{load_id}' '{sc.model_name(FAMILY)}' {MODEL_CODE} {sc.it} {N_ICON} {N_CON} "
              f"{N_STATE} {N_VAR} {N_RESERVED_ICON}"),
             ("@! ICON(M) ICON(M+1)  [ICON(M): the document's 50 Hz flag, ignored by the DLL; ICON(M+1) = 1 enables "
              "momentary cessation]"),
             f" {int(cons['FREQ50'])} {int(cons['MCFLAG'])}"]
    for block in DYR_LAYOUT:
        lines.append("@! " + " ".join(block))
        lines.append(" " + " ".join(format_con(int(cons[n]) if n in ZIP_FIELDS else cons[n]) for n in block))
    lines[-1] += " /"
    return "\n".join(lines)


_SCOPE_BY_SUFFIX = {scope.suffix: scope for scope in RECORD_SCOPES.values()}
_HEADER_FIELDS = (MODEL_CODE, None, N_ICON, None, N_STATE, N_VAR, N_RESERVED_ICON)  # IT and N_CON vary
# A tolerant reader for files this app did not write (vendor samples, hand-edited or re-wrapped records): the header
# may be split across lines or comma separated, and the 2 ICONs + 179 CONs are read as one token stream up to the
# record's closing "/" instead of one row per layout block. Vendor samples also leave the first field as a
# placeholder word (`IBUS`) and may write the load ID unquoted, so both are accepted here.
_RECORD_RE = re.compile(
    r"(?P<number>\d+|[A-Za-z]\w*)\s+'USRLOD'\s+(?:'(?P<id>[^']+)'|(?P<bare_id>[^\s'/]+))\s+"
    rf"'{FAMILY}(?P<suffix>BL|OW|ZN|AR|AL)'\s+(?P<values>[^/]*)/?")


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def _scan_records(dyr_text: str) -> list[dict]:
    """Every PERC** USRLOD record whose header gives 179 CONs, in file order. A record with any other CON count (a
    PERC1 DLL record) or a header too broken to read is left out; one that is malformed beyond that carries its
    `error` (cons empty) instead of being raised, so one bad record does not hide the others."""
    text = re.sub(r"'[^']*'|,", lambda m: " " if m.group(0) == "," else m.group(0), strip_comments(dyr_text))
    records = []
    for match in _RECORD_RE.finditer(text):
        scope = _SCOPE_BY_SUFFIX[match.group("suffix")]
        first = match.group("number")
        tokens = match.group("values").split()
        try:
            n_con = int(float(tokens[3])) if len(tokens) > 3 else N_CON_V1
        except ValueError:
            continue
        if n_con != N_CON:
            continue
        record = {"scope": scope.id, "number": int(first) if first.isdigit() else 0,
                  "placeholder": None if first.isdigit() else first,
                  "load_id": match.group("id") if match.group("id") is not None else match.group("bare_id"),
                  "icons": (), "cons": {}, "error": None, "position": match.start(), "n_con": n_con}
        try:
            expected = len(_HEADER_FIELDS) + N_ICON + n_con
            if len(tokens) != expected:
                raise ValueError(f"expected {expected} numbers after the PERC{scope.suffix} name (7 header fields, "
                                 f"{N_ICON} ICONs, {n_con} CONs), got {len(tokens)}")
            header = [float(t) for t in tokens[:len(_HEADER_FIELDS)]]
            for got, want in zip(header, _HEADER_FIELDS):
                if want is not None and got != want:
                    raise ValueError(f"header field {got:g} where the vendor format has {want}")
            if int(header[1]) != scope.it:
                raise ValueError(f"PERC{scope.suffix} record has IT={int(header[1])}; the vendor format requires IT={scope.it}")
            record["icons"] = tuple(int(float(t)) for t in tokens[len(_HEADER_FIELDS):len(_HEADER_FIELDS) + N_ICON])
            values = tokens[len(_HEADER_FIELDS) + N_ICON:]
            cons = {name: int(v) for name, v in zip(ICON_NAMES, record["icons"])}
            cons.update({
                name: int(float(tok)) if name in ZIP_FIELDS else (float(tok) if "." in tok else int(tok))
                for name, tok in zip(CON_ONLY_NAMES[:N_CON_V1], values)
            })
            cons.update({name: float(tok) for name, tok in zip(V2P3_EXTRA_CONS, values[N_CON_V1:])})
            record["cons"] = cons
        except ValueError as exc:
            record["cons"], record["error"] = {}, str(exc)
        records.append(record)
    return records


def parse_perc2_dll_records(dyr_text: str) -> list[dict]:
    """Every PERC** record with the v2.3 header (179 CONs) in `dyr_text`, in file order: scope, number, load_id,
    placeholder, cons (flags + 179 CONs), error, position. 173-CON (PERC1 DLL) records are left out."""
    return _scan_records(dyr_text)


def is_perc2_dll_record(dyr_text: str) -> bool:
    """True when `dyr_text` holds a PERC** record whose header gives 179 CONs (the v2.3 layout)."""
    return bool(_scan_records(dyr_text))


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


__all__ = [
    "FAMILY",
    "MODEL_CODE",
    "N_CON",
    "N_CON_V1",
    "N_ICON",
    "N_RESERVED_ICON",
    "N_STATE",
    "N_VAR",
    "V2P3_EXTRA_CONS",
    "build_perc2_dll_record",
    "is_perc2_dll_record",
    "parse_perc2_dll_record",
    "parse_perc2_dll_records",
    "strip_comments",
]
