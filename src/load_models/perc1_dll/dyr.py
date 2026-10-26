"""PERC1 (DLL) .dyr record writer and its exact inverse parser.

`parse_perc1_dyr_block` exists so the mock runner is exercised against the
exact `.dyr` text a real PSS/E run would consume, instead of a shortcut
params dict that could silently diverge from what actually gets exported.
"""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, format_con, get_record_scope, validate_load_id
from .cons import PERC1_CON_ORDER, PERC1_DYR_LAYOUT, PERC1_ZIP_FIELDS


def build_perc1_dyr_block(bus_number, load_id, params, scope="bus"):
    """Build the PSS/E v34/v35 PERC1 (Power Electronic Load Model) UDM record.

    Matches the vendor data sheet exactly: model name 'PERC**' with ** set by
    `scope` (BL bus, OW owner, ZN zone, AR area, AL all), fixed header
    ``12, IT, 2, 173, 33, 250, 0`` with IT = 1-5 for the same scopes, 2 ICONs,
    and CON(J) through CON(J+172) - 173 values in ``PERC1_DYR_LAYOUT`` order,
    one "@!" comment row per named group exactly as the vendor's example file
    groups them. `bus_number` is the record's first field: the bus number for
    a bus-scoped record, otherwise the owner/zone/area number (0 for all) -
    see load_models.base.record_number(). Like CLOD, this model carries no
    MW/Mvar of its own: it is a USRLOD that attaches to existing static Load
    records in the .raw case, matched by that first field and the load ID.
    """
    validate_load_id(load_id)
    record_scope = get_record_scope(scope)
    first_field = {"bus": "ibus", "all": "0 (all)"}.get(record_scope.id, f"i{record_scope.id}")
    lines = [f"@! {first_field}  LID  IT"]
    lines.append(
        f"{bus_number} 'USRLOD' '{load_id}' '{record_scope.model_name('PERC')}' 12 {record_scope.it} 2 173 33 250 0"
    )
    lines.append("@! ICON(M) ICON(M+1)  [ICON(M)=0 for 60 Hz, 1 for 50 Hz; ICON(M+1)=1 enables momentary")
    lines.append("@! cessation (Option 2) in place of the undervoltage cease/reconnect (Option 1) used below]")
    lines.append(" 0 0")
    for block in PERC1_DYR_LAYOUT:
        lines.append("@! " + " ".join(block))
        lines.append(" " + " ".join(format_con(params[name]) for name in block))
    lines[-1] = lines[-1] + "/"
    return "\n".join(lines)


_SCOPE_BY_SUFFIX = {scope.suffix: scope for scope in RECORD_SCOPES.values()}
_HEADER_RE = re.compile(
    r"^(\d+)\s+'USRLOD'\s+'([^']+)'\s+'PERC(BL|OW|ZN|AR|AL)'\s+12\s+([1-5])\s+2\s+173\s+33\s+250\s+0\s*$"
)


def parse_perc1_record_scope(dyr_text: str) -> tuple[str, int]:
    """(scope id, first-field number) of the single PERC** record in
    `dyr_text` - e.g. ("owner", 7) for `7 'USRLOD' '1' 'PERCOW' 12 2 ...`."""
    matches = [_HEADER_RE.match(line.strip()) for line in dyr_text.splitlines()]
    matches = [m for m in matches if m]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one PERC1 USRLOD record, found {len(matches)}")
    scope = _SCOPE_BY_SUFFIX[matches[0].group(3)]
    if int(matches[0].group(4)) != scope.it:
        raise ValueError(f"PERC{scope.suffix} record has IT={matches[0].group(4)}; the vendor format requires IT={scope.it}")
    return scope.id, int(matches[0].group(1))


def parse_perc1_dyr_block(dyr_text: str, *, load_id: str | None = None) -> dict:
    """Parse the single PERCBL USRLOD record in `dyr_text` back into a CON
    dict keyed by load_models.perc1_dll.cons.PERC1_CON_ORDER - the same 173 names
    build_perc1_dyr_block consumes. Uses load_models.perc1_dll.cons.PERC1_DYR_LAYOUT's own block
    structure to read each value row positionally, rather than parsing the
    "@!" comment text, so it stays correct even if a comment's wording
    changes. Raises ValueError (fails loudly, never silently drops a CON) if
    zero or multiple PERCBL records are found without `load_id` to
    disambiguate, or if any block's value count doesn't match the expected
    CON layout."""
    lines = dyr_text.splitlines()

    headers = []
    for i, raw_line in enumerate(lines):
        match = _HEADER_RE.match(raw_line.strip())
        if match:
            headers.append((i, match))
    if load_id is not None:
        headers = [(i, m) for i, m in headers if m.group(2) == load_id]

    if not headers:
        suffix = f" with load_id={load_id!r}" if load_id is not None else ""
        raise ValueError(f"no PERCBL USRLOD record found in dyr_text{suffix}")
    if len(headers) > 1:
        raise ValueError(
            f"multiple PERCBL USRLOD records found ({len(headers)}); pass load_id to disambiguate"
        )

    idx, _header_match = headers[0]

    j = idx + 1
    while j < len(lines) and lines[j].lstrip().startswith("@!"):
        j += 1
    if j >= len(lines):
        raise ValueError("PERCBL record is missing its ICON(M)/ICON(M+1) line")
    j += 1  # past the ICON line

    params: dict = {}
    for block in PERC1_DYR_LAYOUT:
        while j < len(lines) and lines[j].lstrip().startswith("@!"):
            j += 1
        if j >= len(lines):
            raise ValueError(f"PERCBL record ended before all CON blocks were read (missing {block})")
        value_line = lines[j].strip().rstrip("/").strip()
        tokens = value_line.split()
        if len(tokens) != len(block):
            raise ValueError(
                f"expected {len(block)} values for block {block}, got {len(tokens)}: {value_line!r}"
            )
        for name, token in zip(block, tokens):
            params[name] = float(token) if "." in token else int(token)
        j += 1

    missing = [name for name in PERC1_CON_ORDER if name not in params]
    if missing:
        raise ValueError(f"parsed PERCBL record is missing CONs: {missing}")

    return params


# A tolerant reader for files this app did not write (vendor samples, hand-edited or re-wrapped records): the header
# may be split across lines or comma separated, and the 2 ICONs + 173 CONs are read as one token stream up to the
# record's closing "/" instead of one row per layout block. Vendor samples also leave the first field as a
# placeholder word (`IBUS`) and may write the load ID unquoted, so both are accepted here.
_RECORD_RE = re.compile(
    r"(?P<number>\d+|[A-Za-z]\w*)\s+'USRLOD'\s+(?:'(?P<id>[^']+)'|(?P<bare_id>[^\s'/]+))\s+"
    r"'PERC(?P<suffix>BL|OW|ZN|AR|AL)'\s+(?P<values>[^/]*)/?")
_HEADER_FIELDS = (12, None, 2, None, 33, 250, 0)  # model type code, IT, N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED
N_ICON, N_CON = 2, 173
# PERC2 V2.3 (PERC2_v3x_v2p3.dll) keeps CON(J)..CON(J+172) unchanged and appends these six (vendor docx, J+173..J+178).
V2P3_EXTRA_CONS = ("TAQ", "TBQ", "RAMPAMC", "RAMPUAMC", "VLRCMC", "VURCMC")
_CON_COUNTS = (N_CON, N_CON + len(V2P3_EXTRA_CONS))


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def parse_perc1_records(dyr_text: str) -> list[dict]:
    """Every PERC** USRLOD record in `dyr_text`, in file order, as dicts with scope, number, load_id, icons, cons and
    error. A malformed record is reported through its `error` (cons empty) rather than raised, so one bad record
    does not hide the others. A placeholder first field (`IBUS`) gives number 0 and is kept in `placeholder`; a
    PERC2 V2.3 record's six extra CONs are kept in `v2p3_cons`, out of `cons`; `n_con` is the header's CON count
    when it could be read."""
    text = re.sub(r"'[^']*'|,", lambda m: " " if m.group(0) == "," else m.group(0), strip_comments(dyr_text))
    records = []
    for match in _RECORD_RE.finditer(text):
        scope = _SCOPE_BY_SUFFIX[match.group("suffix")]
        first = match.group("number")
        record = {"scope": scope.id, "number": int(first) if first.isdigit() else 0,
                  "placeholder": None if first.isdigit() else first,
                  "load_id": match.group("id") if match.group("id") is not None else match.group("bare_id"),
                  "icons": (), "cons": {}, "error": None, "position": match.start()}
        tokens = match.group("values").split()
        try:
            n_con = int(float(tokens[3])) if len(tokens) > 3 else N_CON
            record["n_con"] = n_con
            if n_con not in _CON_COUNTS:
                raise ValueError(f"header gives {n_con} CONs; PERC1 has {N_CON} and PERC2 V2.3 has {_CON_COUNTS[1]}")
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
            record["cons"] = {
                name: int(float(tok)) if name in PERC1_ZIP_FIELDS else (float(tok) if "." in tok else int(tok))
                for name, tok in zip(PERC1_CON_ORDER, values)
            }
            if n_con > N_CON:
                record["v2p3_cons"] = {name: float(tok) for name, tok in zip(V2P3_EXTRA_CONS, values[N_CON:])}
        except ValueError as exc:
            record["cons"], record["error"] = {}, str(exc)
        records.append(record)
    return records


def is_perc1_dll_record(dyr_text: str) -> bool:
    """True when `dyr_text` holds a PERC** record that is not a PERC2 DLL v2.3 one (header CON count 179). Both DLLs
    register PERCBL, so the count is the only thing that tells them apart; a header too broken to read counts as
    PERC1's, so the error is reported against the older model."""
    return any(r.get("n_con") != N_CON + len(V2P3_EXTRA_CONS) for r in parse_perc1_records(dyr_text))
