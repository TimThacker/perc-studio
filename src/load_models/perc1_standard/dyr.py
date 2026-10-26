"""`.dyr` writer/parser for the PERC1 standard model (PSS/E 36.7 PERCxx1U).

The record (data sheet, printed p. 602) is

    IBUS 'USRLODC' ID 'PERCxx1U' 230 IT 0 30 8 24 2 CompNum 'CompDesc' CON(J) to CON(J+29) /

and PSS/E 36.7.1 only applies it to a load that also has a main-component
record above it:

    IBUS 'MAINxx10' ID ICON(M) to ICON(M+9) CON(J) to CON(J+9) /

(Every number below was measured in PSS/E 36.7.1.) When the PERC component carries less than the whole load, the
rest needs a static component with load fraction -1, or PSS/E disables the
main model ("Sum of "load" type components < 1.0 ... Main model will be
disabled").
"""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, get_record_scope, validate_load_id
from .cons import CON_NAMES, validate_cons

MODEL_CODE = 230  # the first header number; any other value is "Invalid user model type code"
N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED_ICON = 0, 30, 8, 24, 2
FAMILY = "PERC"
VERSION_SUFFIX = "1U"
MAX_COMPONENTS = 10

# LSTCxx static component: PFs, P1e, P1c, P2e, P2c, Pfrq, Q1e, Q1c, Q2e, Q2c, Qfrq. The remainder of a partially
# PERC load; the data sheet's example (constant-impedance-heavy ZIP) is a reasonable stand-in.
STATIC_REMAINDER_CONS = (1.0, 2.0, 0.3, 1.0, 0.7, 0.0, 2.0, 1.0, 1.0, 1.0, -1.0)


def perc_model_name(scope: str) -> str:
    return f"{FAMILY}{get_record_scope(scope).suffix}{VERSION_SUFFIX}"


def format_value(value) -> str:
    return f"{float(value):.6g}"


def _main_record(number, load_id, scope, fractions: dict[int, float]) -> str:
    """MAINxx10: component types (1 = load) for the listed components, their load fractions (-1 = the balance)."""
    ctype = [1 if i + 1 in fractions else 0 for i in range(MAX_COMPONENTS)]
    frac = [fractions.get(i + 1, 0.0) for i in range(MAX_COMPONENTS)]
    suffix = get_record_scope(scope).suffix
    return (f"{number} 'MAIN{suffix}10' '{load_id}' {' '.join(map(str, ctype))}  "
            f"{' '.join(format_value(f) for f in frac)} /")


def build_perc1_standard_dyr_block(number, load_id, cons, scope="bus", *, load_fraction=1.0, component=1,
                                   description="PERC1 load") -> str:
    """The complete record set for one load: the main component, the PERC
    component and - only when `load_fraction` < 1 - a static component for the
    rest. `number` is the records' first field (`base.record_number`: the bus
    for a bus-scoped record, the owner/zone/area number, or 0 for All). Raises
    ValueError for CONs PSS/E would reject; values it merely adjusts are
    reported by `validate_cons`, not raised here."""
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

    other = 2 if component == 1 else 1  # the static remainder's component slot
    fractions = {component: float(load_fraction)}
    lines = [f"@! PERC1 standard (PSS/E 36.7 {perc_model_name(scope)}): main component + PERC component"
             + (" + static remainder" if load_fraction < 1 else ""),
             f"@! PERC CONs: {' '.join(CON_NAMES)}"]
    if load_fraction < 1:
        fractions[other] = -1.0
    lines.append(_main_record(number, load_id, scope, fractions))
    values = " ".join(format_value(cons[n]) for n in CON_NAMES)
    lines.append(f"{number} 'USRLODC' '{load_id}' '{perc_model_name(scope)}' {MODEL_CODE} {scope_obj.it} {N_ICON} {N_CON} "
                 f"{N_STATE} {N_VAR} {N_RESERVED_ICON} {component} '{description}' {values} /")
    if load_fraction < 1:
        lines.append(f"{number} 'LSTC{scope_obj.suffix}' '{load_id}' {other} 'Static remainder' "
                     f"{' '.join(format_value(v) for v in STATIC_REMAINDER_CONS)} /")
    return "\n".join(lines)


_NAMES = "|".join(f"{FAMILY}{s.suffix}{VERSION_SUFFIX}" for s in RECORD_SCOPES.values())
_PERC_RE = re.compile(
    rf"(?P<number>\d+)\s+'USRLODC'\s+'(?P<id>[^']+)'\s+'(?P<model>{_NAMES})'\s+{MODEL_CODE}\s+(?P<it>[1-5])\s+{N_ICON}\s+{N_CON}\s+"
    rf"{N_STATE}\s+{N_VAR}\s+{N_RESERVED_ICON}\s+(?P<comp>\d+)\s+'(?P<desc>[^']*)'\s+(?P<values>[^/]*?)\s*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def parse_perc1_standard_record(dyr_text: str) -> dict:
    """The 30 CONs of the first PERCxx1U record in `dyr_text` (comment rows
    and continuation lines allowed)."""
    match = _PERC_RE.search(_strip_comments(dyr_text))
    if match is None:
        raise ValueError("no PERCxx1U 'USRLODC' record with the standard header (230 IT 0 30 8 24 2) found")
    values = [float(token) for token in match.group("values").split()]
    if len(values) != N_CON:
        raise ValueError(f"expected {N_CON} CON values, got {len(values)}")
    return dict(zip(CON_NAMES, values))


def parse_perc1_standard_header(dyr_text: str) -> dict:
    """Scope, number, load id and component number of the first PERCxx1U record."""
    match = _PERC_RE.search(_strip_comments(dyr_text))
    if match is None:
        raise ValueError("no PERCxx1U 'USRLODC' record found")
    suffix = match.group("model")[len(FAMILY):len(FAMILY) + 2]
    scope = next(s.id for s in RECORD_SCOPES.values() if s.suffix == suffix)
    return {"scope": scope, "number": int(match.group("number")), "load_id": match.group("id"),
            "component": int(match.group("comp")), "description": match.group("desc")}


_MAIN_RE = re.compile(r"(?P<number>\d+)\s+'MAIN(?P<suffix>BL|OW|ZN|AR|AL)10'\s+'(?P<id>[^']+)'\s+(?P<values>[^/]*?)\s*/")


def parse_perc1_standard_records(dyr_text: str) -> list[dict]:
    """Every PERCxx1U record in `dyr_text`, in file order: scope, number, load_id, component, description, cons,
    error and `load_fraction` - the fraction its MAINxx10 record gives that component (-1 means "the balance"; None
    when the file has no matching main record). A record with the wrong number of CONs carries `error`."""
    text = re.sub(r"'[^']*'|,", lambda m: " " if m.group(0) == "," else m.group(0), _strip_comments(dyr_text))
    mains = {}
    for main in _MAIN_RE.finditer(text):
        tokens = main.group("values").split()
        if len(tokens) >= 2 * MAX_COMPONENTS:
            mains[(int(main.group("number")), main.group("id"))] = [float(t) for t in tokens[-MAX_COMPONENTS:]]
    records = []
    for match in _PERC_RE.finditer(text):
        header = {"scope": next(s.id for s in RECORD_SCOPES.values() if s.suffix == match.group("model")[len(FAMILY):len(FAMILY) + 2]),
                  "number": int(match.group("number")), "load_id": match.group("id"),
                  "component": int(match.group("comp")), "description": match.group("desc"),
                  "position": match.start()}
        fractions = mains.get((header["number"], header["load_id"]))
        header["load_fraction"] = fractions[header["component"] - 1] if fractions and header["component"] <= MAX_COMPONENTS else None
        values = [float(token) for token in match.group("values").split()]
        if len(values) == N_CON:
            records.append({**header, "cons": dict(zip(CON_NAMES, values)), "error": None})
        else:
            records.append({**header, "cons": {}, "error": f"expected {N_CON} CON values, got {len(values)}"})
    return records
