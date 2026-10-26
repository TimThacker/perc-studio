"""What a model block's parameters are compared against, and which of them the user changed.

Qt-free. A block starts from a *baseline*: a ride-through preset's values, the values of
a record imported from a .dyr file, or the model's defaults. `EditTracker` holds the
baseline and the current values, says which CONs differ ("edited"), and gives the
strings the parameter panel shows ("2 edited", "Reset to preset", ...).

Reset returns to the baseline: the preset's values for a preset, the file's values for
an imported file (an imported block stays imported).
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRESET, IMPORTED, DEFAULTS = "preset", "imported", "defaults"
ABS_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Baseline:
    kind: str  # PRESET | IMPORTED | DEFAULTS
    values: dict
    preset_id: str | None = None
    preset_label: str | None = None
    file_name: str | None = None
    record_label: str | None = None

    @classmethod
    def from_preset(cls, preset, values: dict) -> Baseline:
        return cls(PRESET, dict(values), preset_id=preset.id, preset_label=preset.label)

    @classmethod
    def from_import(cls, values: dict, file_name: str = "", record_label: str = "") -> Baseline:
        return cls(IMPORTED, dict(values), file_name=file_name or None, record_label=record_label or None)

    @classmethod
    def defaults(cls, values: dict) -> Baseline:
        return cls(DEFAULTS, dict(values))

    @property
    def name(self) -> str:
        """What the values are, for "Matches ..." and "Edits are shown against ..."."""
        if self.kind == PRESET:
            return self.preset_label or self.preset_id or "the preset"
        if self.kind == IMPORTED:
            return self.file_name or "the imported file"
        return "the model defaults"


@dataclass
class EditTracker:
    baseline: Baseline
    current: dict = field(default_factory=dict)
    # Per-CON comparison tolerance: a spin box showing 4 decimals cannot hold a file's 6th digit, so a value
    # within half its last digit of the baseline is not an edit.
    tolerances: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.current:
            self.current = dict(self.baseline.values)

    # --- values ------------------------------------------------------------------------------------

    def set_value(self, con: str, value) -> None:
        self.current[con] = value

    def set_values(self, values: dict) -> None:
        self.current.update(values)

    def is_edited(self, con: str) -> bool:
        if con not in self.current or con not in self.baseline.values:
            return False
        a, b = self.current[con], self.baseline.values[con]
        try:
            return abs(float(a) - float(b)) > max(ABS_TOLERANCE, self.tolerances.get(con, 0.0))
        except (TypeError, ValueError):
            return a != b

    def edited_cons(self) -> set[str]:
        return {con for con in self.current if self.is_edited(con)}

    def edited_count(self) -> int:
        return len(self.edited_cons())

    def edited_rows(self, rows) -> set[str]:
        """Ids of the rows (`editor.parameter_rows.ParameterRow`) holding at least one edited CON."""
        edited = self.edited_cons()
        return {row.id for row in rows if edited & set(row.cons)}

    @property
    def can_reset(self) -> bool:
        return self.edited_count() > 0

    def needs_confirmation(self) -> bool:
        """Leaving this baseline (another preset, another file, another model) would discard edits."""
        return self.edited_count() > 0

    def reset(self) -> dict:
        """Back to the baseline's values; returns them."""
        self.current = dict(self.baseline.values)
        return dict(self.current)

    def rebase(self, baseline: Baseline, current: dict | None = None) -> None:
        self.baseline = baseline
        self.current = dict(current if current is not None else baseline.values)

    # --- strings -----------------------------------------------------------------------------------

    def reset_label(self) -> str:
        return {PRESET: "Reset to preset", IMPORTED: "Reset to file"}.get(self.baseline.kind, "Reset to defaults")

    def baseline_note(self) -> str:
        if self.edited_count():
            return f"Edits are shown against {self.baseline.name}"
        return f"Matches {self.baseline.name}"

    def edited_pill(self) -> str:
        return f"{self.edited_count()} edited"
