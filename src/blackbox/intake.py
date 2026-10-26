"""Reading a `.dyr` file without knowing its models, and placing one load's
records on the test rig.

Every record is split into tokens and given a type from its header only: a
user-written model (`USRLOD`, `USRLODC`, `USRMDL`, ...), a PSS/E library load
model (family + BL/OW/ZN/AR/AL), or something else. CON values are never
interpreted or changed: black-box validation runs the model exactly as
written. What a record attaches to decides where it goes on the rig.

The unit under test is a **load target**: every load-model record in the file
that attaches to the same load (scope, number, load id). A composite model
such as PERCxx1U is a `MAINxx10` record plus its component records, so testing
"the load" runs them together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LOAD_SCOPES = {"BL": "bus", "OW": "owner", "ZN": "zone", "AR": "area", "AL": "all"}
SCOPE_BY_IT = {1: "bus", 2: "owner", 3: "zone", 4: "area", 5: "all"}
# PSS/E library load-model families: a 4-letter family, the 2-letter scope, then an optional suffix
# (CLODBL, CMLDBLDGU2, MAINBL10, LDFRBL, ...). Records outside this list are reported, not run.
LOAD_FAMILIES = ("CLOD", "CMLD", "CIM5", "CIM6", "CIMW", "EXTL", "IEEL", "LDFR", "LDRL", "LDSH", "LVSH", "DLSH",
                 "MAIN", "LSTC", "PERC", "MOTW", "CMPL", "CMLS")
# User-model record types: header layout after the record type.
USER_RECORDS = {
    # type: (device, has_id, tokens before the IC IT NI NC NS NV header)
    "USRLOD": ("load", True, 2),
    "USRLODC": ("load", True, 2),
    "USRMDL": ("machine", True, 2),
    "USRBUS": ("bus", False, 1),
    "USRBRN": ("branch", True, 3),
    "USRAUX": ("other", True, 2),
    "USRMSC": ("other", False, 1),
}
WRAP = 78

_TOKEN_RE = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s,/'\"]+")


def strip_comments(text: str) -> str:
    """Drop `@!` and `//` comment lines; PSS/E ignores them."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def _split_records(text: str) -> list[tuple[str, bool]]:
    """(record text, terminated) for each record: text up to the closing `/` that is outside quotes."""
    records, current, quote = [], [], None
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            current.append(ch)
        elif ch == "/":
            records.append(("".join(current), True))
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        records.append((tail, False))
    return [(t, done) for t, done in records if t.strip()]


def _unquote(token: str) -> str:
    return token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"" else token


def _num(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


@dataclass(frozen=True)
class DyrRecord:
    index: int
    tokens: tuple[str, ...]
    number: int | None
    record_type: str  # the second field: 'USRLOD', 'CLODBL', 'GENROU', ...
    model: str  # the model's own name (for user models, the name after the id)
    device: str  # load | machine | bus | branch | playback | other
    kind: str  # user | library | unknown
    load_id: str | None = None
    scope: str | None = None
    header: dict = field(default_factory=dict)  # user models: ic, it, ni, nc, ns, nv
    icons: tuple[float, ...] = ()
    error: str | None = None

    @property
    def label(self) -> str:
        where = {"bus": f"bus {self.number}", "owner": f"owner {self.number}", "zone": f"zone {self.number}",
                 "area": f"area {self.number}", "all": "all loads"}.get(self.scope or "", f"{self.number}")
        name = self.model if self.model == self.record_type else f"{self.record_type} {self.model}"
        text = f"#{self.index + 1} {name}"
        if self.device == "load":
            text += f" - {where}, load '{self.load_id}'"
        elif self.number is not None:
            text += f" - {self.device} at {self.number}"
        return text + (f" (unreadable: {self.error})" if self.error else "")

    def text(self) -> str:
        return " ".join(self.tokens) + " /"


def _classify(index: int, tokens: list[str], terminated: bool) -> DyrRecord:
    number = int(tokens[0]) if tokens and re.fullmatch(r"-?\d+", tokens[0]) else None
    rtype = _unquote(tokens[1]).upper() if len(tokens) > 1 else ""
    base = {"index": index, "tokens": tuple(tokens), "number": number, "record_type": rtype}
    error = None if terminated else "no closing '/'"
    if number is None or not rtype:
        return DyrRecord(model=rtype or "?", device="other", kind="unknown", error=error or "not a dynamics record",
                         **base)
    if rtype == "PLBVF1" or rtype.startswith("PLB"):
        return DyrRecord(model=rtype, device="playback", kind="library", error=error, **base)

    if rtype in USER_RECORDS:
        device, has_id, before = USER_RECORDS[rtype]
        rest = tokens[2:]
        load_id = _unquote(rest[0]) if has_id and rest else None
        name_at = before - 1
        model = _unquote(rest[name_at]).upper() if len(rest) > name_at else "?"
        nums = [_num(t) for t in rest[before:before + 6]]
        if len(nums) < 6 or any(n is None for n in nums):
            return DyrRecord(model=model, device=device, kind="user", load_id=load_id,
                             error=error or "header IC IT NI NC NS NV is incomplete", **base)
        ic, it, ni, nc, ns, nv = (int(n) for n in nums)
        header = {"ic": ic, "it": it, "ni": ni, "nc": nc, "ns": ns, "nv": nv}
        data = rest[before + 6:]
        icons = tuple(n for n in (_num(t) for t in data[:ni]) if n is not None)
        scope = SCOPE_BY_IT.get(it) if device == "load" else None
        return DyrRecord(model=model, device=device, kind="user", load_id=load_id, scope=scope, header=header,
                         icons=icons, error=error, **base)

    family, suffix = rtype[:4], rtype[4:6]
    if family in LOAD_FAMILIES and suffix in LOAD_SCOPES:
        load_id = _unquote(tokens[2]) if len(tokens) > 2 else None
        return DyrRecord(model=rtype, device="load", kind="library", load_id=load_id, scope=LOAD_SCOPES[suffix],
                         error=error, **base)
    return DyrRecord(model=rtype, device="other", kind="library", error=error, **base)


def scan_dyr(text: str) -> list[DyrRecord]:
    """Every record in the file, in order."""
    return [_classify(i, _TOKEN_RE.findall(piece), terminated)
            for i, (piece, terminated) in enumerate(_split_records(strip_comments(text)))]


@dataclass(frozen=True)
class LoadTarget:
    """One load and every load-model record in the file that attaches to it."""

    scope: str
    number: int
    load_id: str
    record_indices: tuple[int, ...]
    models: tuple[str, ...]

    @property
    def label(self) -> str:
        where = "all loads" if self.scope == "all" else f"{self.scope} {self.number}"
        return f"{' + '.join(self.models)} - {where}, load '{self.load_id}'"


def load_targets(records: list[DyrRecord]) -> list[LoadTarget]:
    groups: dict[tuple, list[DyrRecord]] = {}
    for rec in records:
        if rec.device == "load" and not rec.error and rec.load_id is not None and rec.scope:
            groups.setdefault((rec.scope, rec.number if rec.scope != "all" else 0, rec.load_id), []).append(rec)
    return [LoadTarget(scope, number, lid, tuple(r.index for r in recs), tuple(r.model for r in recs))
            for (scope, number, lid), recs in groups.items()]


@dataclass(frozen=True)
class Placement:
    """A load target moved onto the rig: record texts with `{BUS}` for the rig bus, and the rig fields that make
    an owner/zone/area/all-scoped record find the rig's load."""

    records: tuple[str, ...]
    rig: dict
    expect_ncon: int
    notes: tuple[str, ...]
    flags: tuple[str, ...]


def _wrap(tokens: list[str]) -> str:
    lines, line = [], ""
    for tok in tokens:
        if line and len(line) + 1 + len(tok) > WRAP:
            lines.append(line)
            line = tok
        else:
            line = f"{line} {tok}" if line else tok
    lines.append(line + " /")
    return "\n".join(lines)


def place_on_rig(records: list[DyrRecord], target: LoadTarget, *, map_own_bus_icons: bool = True) -> Placement:
    """The target's records rewritten for the rig. Only the first field changes (the bus number of a bus-scoped
    record becomes `{BUS}`), plus ICONs that equal the record's own bus when `map_own_bus_icons`. ICONs that
    look like other buses in the file are flagged, never changed."""
    by_index = {r.index: r for r in records}
    bus_numbers = {r.number for r in records if r.scope == "bus" or r.device in ("machine", "bus", "branch")}
    rig = {"load_id": target.load_id}
    notes, flags = [], []
    if target.scope in ("owner", "zone", "area"):
        rig[target.scope] = target.number
        notes.append(f"The rig's load is put in {target.scope} {target.number} so the record attaches to it.")
    elif target.scope == "all":
        notes.append("An all-loads record attaches to the rig's only load.")
    texts, expect_ncon = [], 0
    for idx in target.record_indices:
        rec = by_index[idx]
        tokens = list(rec.tokens)
        if target.scope == "bus":
            tokens[0] = "{BUS}"
        if rec.kind == "user":
            before = USER_RECORDS[rec.record_type][2]
            icon_start = 2 + before + 6
            for k, value in enumerate(rec.icons):
                if value != int(value) or int(value) <= 0:
                    continue
                pos = icon_start + k
                if target.scope == "bus" and int(value) == rec.number and map_own_bus_icons:
                    tokens[pos] = "{BUS}"
                    notes.append(f"{rec.model}: ICON({k + 1}) = {int(value)} is the record's own bus; it now "
                                 "points at the rig bus.")
                elif int(value) in bus_numbers:
                    flags.append(f"{rec.model}: ICON({k + 1}) = {int(value)} matches a bus number in the file. If "
                                 "it is a bus, PSS/E will not find it on the one-bus rig.")
            if len(target.record_indices) == 1:
                expect_ncon = rec.header.get("nc", 0)
        texts.append(_wrap(tokens))
    if target.scope == "bus":
        notes.append(f"Bus {target.number} becomes the rig bus.")
    return Placement(tuple(texts), rig, expect_ncon, tuple(notes), tuple(flags))


def other_records_note(records: list[DyrRecord], target: LoadTarget) -> list[str]:
    """What the file holds that will not be run with this target."""
    skipped = [r for r in records if r.index not in target.record_indices]
    if not skipped:
        return []
    kinds: dict[str, int] = {}
    for r in skipped:
        kinds[r.device] = kinds.get(r.device, 0) + 1
    parts = [f"{n} {d} record{'s' if n > 1 else ''}" for d, n in sorted(kinds.items())]
    return [f"Not run with this load: {', '.join(parts)}."]
