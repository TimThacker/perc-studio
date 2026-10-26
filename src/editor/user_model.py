"""A user-defined (black-box) model block: a load model this app does not edit or simulate,
taken as it is from the user's own .dyr file and DLLs.

Qt-free. The block keeps the records of one load from the file. When the facility is
exported, those records are written unchanged except for what attaches them to the
facility's load: the first field (bus, owner, zone or area number) and the load ID. A
comment above them records the original header and the DLLs the model needs. CON and
ICON values are never interpreted or changed (the same rule black-box validation follows).

Reading the file uses `blackbox.intake`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace

USER_DEFINED_ID = "user_defined"
USER_DEFINED_LABEL = "User-defined (black-box)"
_TOKEN_RE = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s,/'\"]+")


@dataclass(frozen=True)
class ExternalModel:
    source_file: str  # the file name shown in the UI
    records: tuple[str, ...]  # the load's record texts as they are in the file, each ending in "/"
    label: str  # e.g. "PERC1 - bus 4021, load '1'"
    scope: str  # bus | owner | zone | area | all
    number: int
    load_id: str
    dlls: tuple[str, ...] = ()
    source_path: str = ""

    def with_dlls(self, dlls) -> ExternalModel:
        unique = tuple(dict.fromkeys(dlls))
        return replace(self, dlls=unique)

    @property
    def original_header(self) -> str:
        where = "all loads" if self.scope == "all" else f"{self.scope} {self.number}"
        return f"{where}, load '{self.load_id}'"

    def state_keys(self, block: str) -> dict:
        """The export-state keys `export.dyr` reads for a user-defined block."""
        return {f"{block}_model_id": USER_DEFINED_ID, f"{block}_user_records": list(self.records),
                f"{block}_user_source": self.source_file, f"{block}_user_dlls": list(self.dlls),
                f"{block}_user_header": self.original_header, f"{block}_user_label": self.label}

    def to_dict(self) -> dict:
        return {"source_file": self.source_file, "records": list(self.records), "label": self.label,
                "scope": self.scope, "number": self.number, "load_id": self.load_id, "dlls": list(self.dlls)}

    @classmethod
    def from_dict(cls, d: dict) -> ExternalModel:
        return cls(d["source_file"], tuple(d["records"]), d.get("label", ""), d.get("scope", "bus"),
                   int(d.get("number", 0)), str(d.get("load_id", "1")), tuple(d.get("dlls", ())))


def read_external_model(text: str, source_file: str, target_index: int | None = 0, *, dlls=(),
                        source_path: str = ""):
    """With `target_index=None`: the labels of the loads in the file (raises ValueError when there is none).
    Otherwise the `ExternalModel` for that load."""
    from blackbox.intake import load_targets, scan_dyr

    records = scan_dyr(text)
    targets = load_targets(records)
    if not targets:
        raise ValueError(f"{source_file} has no load-model record (a USRLOD or a library load model) to use.")
    if target_index is None:
        return [t.label for t in targets]
    target = targets[target_index]
    by_index = {r.index: r for r in records}
    texts = tuple(by_index[i].text() for i in target.record_indices)
    return ExternalModel(source_file, texts, target.label, target.scope, target.number, target.load_id,
                         tuple(dlls), source_path)


def placed_records(model: ExternalModel, number: int, load_id: str) -> list[str]:
    """The model's records attached to the facility's load: only the first field and the load ID change."""
    out = []
    for text in model.records:
        tokens = _TOKEN_RE.findall(text)
        if len(tokens) >= 3:
            tokens[0] = str(number)
            tokens[2] = f"'{load_id}'"
        out.append(" ".join(tokens) + " /")
    return out


def dyr_block_text(model_dict_or_state: dict, block: str, number: int, load_id: str) -> str:
    """The commented records for a user-defined block in the facility .dyr, from export state."""
    s = model_dict_or_state
    records = s.get(f"{block}_user_records") or []
    model = ExternalModel(s.get(f"{block}_user_source", ""), tuple(records), s.get(f"{block}_user_label", ""),
                          "bus", 0, "", tuple(s.get(f"{block}_user_dlls", ())))
    dlls = ", ".join(os.path.basename(d) for d in model.dlls) or "none listed"
    lines = [
        f"/ User-defined model from {model.source_file or 'a user .dyr'} (not edited or simulated by this app).",
        (f"/ Original record: {s.get(f'{block}_user_header', '')}. Attached here to bus/number {number}, "
         f"load '{load_id}'; CONs and ICONs unchanged."),
        f"/ Needs these DLLs loaded in PSS/E: {dlls}.",
    ]
    return "\n".join(lines + placed_records(model, number, load_id))
