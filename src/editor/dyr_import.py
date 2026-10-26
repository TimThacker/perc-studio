"""Read a PSS/E `.dyr` file back into the app: which PERC1 records it holds, and the CONs of the one the user picks.

The UI uses this to load an existing model into an editor block so the live preview can inspect it before any
simulation. Nothing here needs Qt. Records are found per model (`load_models.perc1_dll.dyr.parse_perc1_records`,
`load_models.perc2_dll.dyr.parse_perc2_dll_records`, `load_models.perc1_standard.dyr.parse_perc1_standard_records`,
`load_models.perc2_standard.dyr.parse_perc2_standard_records`), so a file may mix models; CLOD records are listed
but cannot be inspected (the app has no CLOD editor). The PERC1 DLL and the PERC2 DLL v2.3 both write PERCBL; the
header's CON count (173 or 179) decides which one a record is.

An import never rejects a value for being out of range - inspecting a questionable model is the point - it
reports it in `warnings` instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from editor.model_ui import get_ui_spec
from load_models.perc1_dll.dyr import parse_perc1_records, strip_comments
from load_models.perc1_standard.dyr import parse_perc1_standard_records
from load_models.perc2_dll.dyr import N_CON as PERC2_DLL_N_CON
from load_models.perc2_dll.dyr import parse_perc2_dll_records
from load_models.perc2_standard.dyr import parse_perc2_standard_records

_CLOD_RE = re.compile(r"(\d+)\s*,?\s*'CLOD(BL|OW|ZN|AR|AL)'\s*,?\s*'([^']*)'")
_SCOPE_BY_SUFFIX = {"BL": "bus", "OW": "owner", "ZN": "zone", "AR": "area", "AL": "all"}


@dataclass(frozen=True)
class RecordRef:
    """One model record found in a `.dyr` file. `index` is its position among all records in the file."""

    index: int
    model_id: str  # "perc1_dll", "perc2_dll", "perc1_standard", "perc2_standard" or "clod"
    scope: str
    number: int
    load_id: str
    inspectable: bool
    error: str | None = None
    placeholder: str | None = None  # the word a vendor sample has in place of the first field, e.g. "IBUS"

    @property
    def label(self) -> str:
        names = {"perc1_dll": "PERC1 DLL", "perc2_dll": "PERC2 DLL v2.3", "perc1_standard": "PERC1 standard",
                 "perc2_standard": "PERC2 standard", "clod": "CLOD"}
        first = {"bus": "bus", "owner": "owner", "zone": "zone", "area": "area", "all": "all"}[self.scope]
        number = f"{self.placeholder} (placeholder)" if self.placeholder else self.number
        where = "all loads" if self.scope == "all" else f"{first} {number}"
        text = f"{names[self.model_id]} - {where}, load ID '{self.load_id}'"
        if self.error:
            return f"{text} (unreadable: {self.error})"
        return text if self.inspectable else f"{text} (not inspectable in this app)"


@dataclass(frozen=True)
class ImportedRecord:
    ref: RecordRef
    cons: dict
    extras: dict = field(default_factory=dict)  # standard model: component, description, load_fraction
    warnings: tuple[str, ...] = ()

    @property
    def model_id(self) -> str:
        return self.ref.model_id


def _perc1_dll_records(dyr_text: str) -> list[dict]:
    """The PERC** records that are the PERC1 DLL's: a 179-CON header is the PERC2 DLL v2.3's (`perc2_dll`)."""
    return [r for r in parse_perc1_records(dyr_text) if r.get("n_con") != PERC2_DLL_N_CON]


def _scan(dyr_text: str) -> list[tuple[RecordRef, dict, dict]]:
    """(ref, cons, extras) for every record, in the order they appear in the file."""
    found = []
    for model_id, parser in (("perc1_dll", _perc1_dll_records), ("perc2_dll", parse_perc2_dll_records),
                             ("perc1_standard", parse_perc1_standard_records),
                             ("perc2_standard", parse_perc2_standard_records)):
        for record in parser(dyr_text):
            extras = {k: record[k] for k in ("component", "description", "load_fraction", "icons") if k in record}
            found.append((record["position"], model_id, record, extras))
    # The parsers report offsets into the comment-stripped text, so look for CLOD records in the same text.
    for match in _CLOD_RE.finditer(strip_comments(dyr_text)):
        record = {"scope": _SCOPE_BY_SUFFIX[match.group(2)], "number": int(match.group(1)),
                  "load_id": match.group(3), "cons": {}, "error": None}
        found.append((match.start(), "clod", record, {}))
    found.sort(key=lambda item: item[0])
    refs = []
    for index, (_pos, model_id, record, extras) in enumerate(found):
        ref = RecordRef(index, model_id, record["scope"], record["number"], record["load_id"],
                        inspectable=model_id != "clod" and record["error"] is None, error=record["error"],
                        placeholder=record.get("placeholder"))
        refs.append((ref, record["cons"], extras))
    return refs


def list_records(dyr_text: str) -> list[RecordRef]:
    """Every PERC1 (DLL or standard), PERC2 (DLL v2.3 or standard) and CLOD record in the file."""
    return [ref for ref, _cons, _extras in _scan(dyr_text)]


def import_record(dyr_text: str, record: int | RecordRef | None = None) -> ImportedRecord:
    """The CONs of one record. `record` is a `RecordRef` (or its index) from `list_records`; it may be omitted when
    the file holds exactly one record. Raises ValueError when there is nothing to inspect or the choice is ambiguous."""
    records = _scan(dyr_text)
    if not records:
        raise ValueError("no PERC1 (DLL or standard), PERC2 (DLL v2.3 or standard) or CLOD record found in this .dyr "
                         "file")
    if record is None:
        if len(records) != 1:
            raise ValueError(f"the file holds {len(records)} records; choose one: " + "; ".join(r.label for r, _, _ in records))
        index = 0
    else:
        index = record.index if isinstance(record, RecordRef) else int(record)
    if not 0 <= index < len(records):
        raise ValueError(f"no record #{index} in this file (it has {len(records)})")
    ref, cons, extras = records[index]
    if ref.error:
        raise ValueError(f"{ref.label}")
    if ref.model_id == "clod":
        raise ValueError("CLOD records cannot be inspected in this app (only PERC1 DLL, PERC2 DLL v2.3, PERC1 "
                         "standard and PERC2 standard)")
    return ImportedRecord(ref, cons, extras, tuple(_warnings(ref, cons, extras, len(records))))


def _warnings(ref: RecordRef, cons: dict, extras: dict, record_count: int) -> list[str]:
    notes = []
    if record_count > 1:
        notes.append(f"The file holds {record_count} records; showing {ref.label}.")
    ranges = get_ui_spec(ref.model_id).field_ranges
    for name, value in cons.items():
        if name in ranges and not ranges[name][0] <= value <= ranges[name][1]:
            notes.append(f"{name} = {value:g} is outside the usual range {ranges[name][0]:g} to {ranges[name][1]:g}.")
    if ref.placeholder:
        notes.append(f"The record's first field is the placeholder '{ref.placeholder}', not a {ref.scope} number.")
    if ref.model_id == "perc1_dll" and any(extras.get("icons", ())):
        notes.append(f"ICON(M)/ICON(M+1) = {extras['icons'][0]}/{extras['icons'][1]} in the file; the preview and "
                     "any exported record use 0/0 (60 Hz, undervoltage cease/reconnect).")
    if ref.model_id == "perc2_dll":
        # Both flags are kept and exported as they are; say so, since every preset has them off.
        if round(float(cons.get("MCFLAG", 0))) == 1:
            notes.append("MCFLAG (ICON(M+1)) = 1 in the file: momentary cessation is on, and is kept in the preview "
                         "and on export.")
        if round(float(cons.get("FREQ50", 0))) == 1:
            notes.append("FREQ50 (ICON(M)) = 1 in the file: it is kept on export, but the DLL ignores it and compares "
                         "every frequency setting with 60 Hz.")
    if ref.model_id in ("perc1_standard", "perc2_standard"):
        fraction = extras.get("load_fraction")
        if fraction is None:
            notes.append("No matching MAINxx10 record in the file; PSS/E needs one above this record.")
        elif fraction not in (1.0, -1.0) and not 0 < fraction < 1:
            notes.append(f"The main record gives this component a load fraction of {fraction:g}.")
    return notes
