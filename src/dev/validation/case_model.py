"""Canonical, serializable parameterization of one facility's load-model blocks.

`LoadCase` is the structured, JSON-round-trippable equivalent of the flat
session-state dicts `ui/main_window.py` builds ad hoc. It exists so a
script or an agent can create, save, load, and vary a parameterization
without going through the desktop UI at all.

A case has up to three facility blocks - `it`, `vfd`, and `motor` - and each
block names the load model it uses (`ModelBlock.model_id`, a key of
`load_models.LOAD_MODELS`). CON validation, `.dyr` export, the mock runner and
reports all dispatch through that model, so a block can use any registered
model, not just PERC1. By default `it`/`vfd` use `perc1_dll` and `motor` uses
`clod` (`load_models.DEFAULT_BLOCK_MODELS`).

This module does not reimplement derivation logic: `case_from_preset` asks the block's model to encode a
`presets.ridethrough.RIDE_THROUGH_PRESETS` entry, and `ui_state_to_case`
reuses `export.dyr.get_it_params`/`get_vfd_params`/`get_clod_params` - the same
functions `ui/main_window.py`'s own export path already calls.

`case_to_ui_state`/`ui_state_to_case` let a case round-trip through the
`app.config.DEFAULTS`-shaped dict `ui/main_window.py`/`export/dyr.py` consume. The desktop UI
only edits PERC1 or user-defined (`it`/`vfd`) and CLOD (`motor`) blocks
(`UI_BLOCK_MODELS`), so those converters reject a case whose blocks use any
other model.
"""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app import config
from export.dyr import get_clod_params, get_it_params, get_vfd_params
from load_models import DEFAULT_BLOCK_MODELS, LoadModel, get_load_model
from load_models.base import record_number
from load_models.clod.cons import derive_clod_params
from presets.ridethrough import RIDE_THROUGH_PRESETS

SCHEMA_VERSION = 3
USER_DEFINED_ID = "user_defined"  # see editor/user_model.py

BLOCK_NAMES = ("it", "vfd", "motor")


def _new_case_id() -> str:
    return f"case-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class FacilityInfo:
    name: str
    bus_number: int
    bus_name: str
    use_case: str
    use_case_pct: int
    total_mw: float
    power_factor: float


@dataclass(frozen=True)
class LoadComposition:
    pct_it: float
    pct_cooling_vfd: float
    pct_cooling_motor: float
    pct_other: float

    @property
    def total(self) -> float:
        return self.pct_it + self.pct_cooling_vfd + self.pct_cooling_motor + self.pct_other

    def is_valid(self) -> bool:
        """The load split sums to 100% within 0.01."""
        return abs(self.total - 100.0) < 0.01


@dataclass(frozen=True)
class ModelBlock:
    """One facility block: which load model it uses, and that model's
    fully-resolved CON dict, plus provenance.

    `model_id` is a key of `load_models.LOAD_MODELS`; `cons` always holds a
    value for every one of that model's `con_names` - never partial. The one
    exception is a user-defined (black-box) block (`model_id` "user_defined",
    schema 3): its records come unedited from the user's own .dyr and are held
    in `external` (`editor.user_model.ExternalModel.to_dict()`), with `cons` empty.
    `source` is one of "preset" (a ride-through preset encoded by the model),
    "defaults" (the model's own `default_cons`), "overrides" (built from
    explicit CON values) or "archetype" (a CLOD motor block derived from its
    facility archetype). `qualitative` holds the archetype choices a CLOD
    block was derived from, when there are any.
    """

    model_id: str
    source: str
    cons: dict
    qualitative: dict | None = None
    preset_id: str | None = None
    overrides: dict = field(default_factory=dict)
    external: dict | None = None

    @property
    def is_user_defined(self) -> bool:
        return self.model_id == USER_DEFINED_ID

    @property
    def model(self) -> LoadModel:
        return get_load_model(self.model_id)


@dataclass(frozen=True)
class GenerationInfo:
    has_onsite_gen: bool = False
    notes: str = ""


@dataclass(frozen=True)
class LoadCase:
    """The canonical, serializable parameterization of one facility's load-model
    blocks. mw_*/is_load_split_valid are computed from facility/
    load_composition, never stored, so they cannot drift out of sync."""

    schema_version: int
    case_id: str
    facility: FacilityInfo
    load_composition: LoadComposition
    it_block: ModelBlock | None
    vfd_block: ModelBlock | None
    motor_block: ModelBlock | None
    generation: GenerationInfo
    metadata: dict = field(default_factory=dict)

    @property
    def mw_it(self) -> float:
        return self.facility.total_mw * self.load_composition.pct_it / 100.0

    @property
    def mw_vfd(self) -> float:
        return self.facility.total_mw * self.load_composition.pct_cooling_vfd / 100.0

    @property
    def mw_motor(self) -> float:
        return self.facility.total_mw * self.load_composition.pct_cooling_motor / 100.0

    @property
    def is_load_split_valid(self) -> bool:
        return self.load_composition.is_valid()

    def block(self, name: str) -> ModelBlock | None:
        if name not in BLOCK_NAMES:
            raise ValueError(f"unknown block {name!r}; expected one of {', '.join(BLOCK_NAMES)}")
        return getattr(self, f"{name}_block")

    def blocks(self) -> dict[str, ModelBlock]:
        """Every block the case actually has, keyed by block name."""
        return {name: block for name in BLOCK_NAMES if (block := self.block(name)) is not None}


# --- Model-aware helpers -----------------------------------------------------


def block_dyr_record(case: LoadCase, block_name: str, load_id: str, *, scope: str = "bus",
                     subsystem_number: int | None = None) -> str:
    """The block's `.dyr` record, written by its own load model. `scope`
    (bus/owner/zone/area/all) sets the record's model-name suffix, IT code and
    first field - see load_models.base.RECORD_SCOPES."""
    block = case.block(block_name)
    if block is None:
        raise ValueError(f"case {case.case_id!r} has no {block_name} block")
    number = record_number(scope, case.facility.bus_number, subsystem_number)
    if block.is_user_defined:
        from editor.user_model import ExternalModel, dyr_block_text

        state = ExternalModel.from_dict(block.external or {}).state_keys(block_name)
        return dyr_block_text(state, block_name, number, load_id)
    model = block.model
    if model.supports_record_scopes:
        return model.build_dyr_record(number, load_id, block.cons, scope=scope)
    if scope != "bus":
        raise ValueError(f"load model {model.id!r} only writes bus-scoped records")
    return model.build_dyr_record(number, load_id, block.cons)


def schema_problems(case: LoadCase) -> list[str]:
    """Schema-level checks (no simulation): load split totals 100%, every
    block names a registered model, and every block's CONs exactly match its
    model's `con_names`. Returns an empty list for a valid case."""
    problems = []
    if not case.load_composition.is_valid():
        problems.append(f"load composition totals {case.load_composition.total:.2f}%, expected 100%")
    for name, block in case.blocks().items():
        if block.is_user_defined:
            if not (block.external or {}).get("records"):
                problems.append(f"{name} block (user-defined) has no records from its .dyr file")
            if block.cons:
                problems.append(f"{name} block (user-defined) must not carry CONs; its records hold them")
            continue
        try:
            model = block.model
        except KeyError as exc:
            problems.append(f"{name} block: {exc.args[0]}")
            continue
        missing = [con for con in model.con_names if con not in block.cons]
        unknown = sorted(set(block.cons) - set(model.con_names))
        if missing:
            problems.append(f"{name} block ({model.id}) is missing CONs: {missing}")
        if unknown:
            problems.append(f"{name} block ({model.id}) has unknown CONs: {unknown}")
    return problems


# --- Serialization ---------------------------------------------------------


def to_dict(case: LoadCase) -> dict:
    return dataclasses.asdict(case)


def _migrate_v1(d: dict) -> dict:
    """Schema 1 had separate Perc1Block/ClodBlock shapes and a case-level
    `model_variant`; schema 2 tags every block with its own `model_id`."""
    d = {k: v for k, v in d.items() if k != "model_variant"}
    for name in ("it_block", "vfd_block"):
        if d.get(name) is not None:
            d[name] = {"model_id": "perc1_dll", **d[name]}
    motor = d.get("motor_block")
    if motor is not None:
        motor = dict(motor)
        qualitative = {
            "facility_type": motor.pop("facility_type", None),
            "has_lighting": motor.pop("has_lighting", None),
        }
        d["motor_block"] = {"model_id": "clod", **motor, "qualitative": qualitative}
    d["schema_version"] = 2
    return d


def _migrate_v2(d: dict) -> dict:
    """Schema 3 adds an optional `external` on each block (user-defined models); schema-2 blocks have none."""
    return {**d, "schema_version": SCHEMA_VERSION}


def from_dict(d: dict) -> LoadCase:
    """Reconstructs a LoadCase explicitly (not via a generic loader), so a
    malformed or foreign JSON fails loudly rather than silently dropping a
    field. Schema-1 JSON is migrated on load."""
    version = d.get("schema_version")
    if version == 1:
        d = _migrate_v1(d)
        version = 2
    if version == 2:
        d = _migrate_v2(d)
        version = SCHEMA_VERSION
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
    try:
        facility = FacilityInfo(**d["facility"])
        load_composition = LoadComposition(**d["load_composition"])
        blocks = {
            name: ModelBlock(**d[f"{name}_block"]) if d.get(f"{name}_block") is not None else None
            for name in BLOCK_NAMES
        }
        generation = GenerationInfo(**d.get("generation", {}))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed LoadCase JSON: {exc}") from exc
    return LoadCase(
        schema_version=version,
        case_id=d["case_id"],
        facility=facility,
        load_composition=load_composition,
        it_block=blocks["it"],
        vfd_block=blocks["vfd"],
        motor_block=blocks["motor"],
        generation=generation,
        metadata=d.get("metadata", {}),
    )


def to_json(case: LoadCase, path: str | None = None, *, indent: int | None = 2) -> str:
    text = json.dumps(to_dict(case), indent=indent)
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def from_json(text_or_path: str) -> LoadCase:
    """Accepts either a JSON string or a filesystem path."""
    try:
        is_path = os.path.isfile(text_or_path)
    except (OSError, ValueError):
        is_path = False
    if is_path:
        with open(text_or_path, "r", encoding="utf-8") as f:
            text_or_path = f.read()
    return from_dict(json.loads(text_or_path))


# --- Construction paths ------------------------------------------------


def _clod_motor_block(facility_type: str, has_lighting: bool) -> ModelBlock:
    return ModelBlock(
        model_id=DEFAULT_BLOCK_MODELS["motor"],
        source="archetype",
        qualitative={"facility_type": facility_type, "has_lighting": has_lighting},
        cons=derive_clod_params(facility_type, has_lighting),
    )


def case_from_preset(
    preset_id: str,
    *,
    facility: FacilityInfo,
    load_composition: LoadComposition,
    model_id: str = DEFAULT_BLOCK_MODELS["it"],
    include_vfd: bool = True,
    include_motor: bool = True,
    motor_facility_type: str = "Mixed - moderate mix of large & small motors",
    motor_has_lighting: bool = False,
    case_id: str | None = None,
) -> LoadCase:
    """The primary sweep-generation entry point: `model_id`'s own
    `cons_for_preset` hook encodes a ridethrough_presets.RIDE_THROUGH_PRESETS
    entry into CONs for the it (and optionally vfd) block."""
    try:
        preset = RIDE_THROUGH_PRESETS[preset_id]
    except KeyError:
        raise KeyError(
            f"unknown preset id {preset_id!r}; valid ids: {sorted(RIDE_THROUGH_PRESETS)}"
        ) from None
    model = get_load_model(model_id)
    if not model.supports_presets:
        raise ValueError(f"load model {model_id!r} has no cons_for_preset hook, so it cannot encode a preset")

    def preset_block(block_name: str) -> ModelBlock:
        return ModelBlock(
            model_id=model_id, source="preset", preset_id=preset_id,
            cons=model.cons_for_preset(preset, block_name),
        )

    return LoadCase(
        schema_version=SCHEMA_VERSION,
        case_id=case_id or _new_case_id(),
        facility=facility,
        load_composition=load_composition,
        it_block=preset_block("it"),
        vfd_block=preset_block("vfd") if include_vfd else None,
        motor_block=_clod_motor_block(motor_facility_type, motor_has_lighting) if include_motor else None,
        generation=GenerationInfo(),
        metadata={"created_at": _now_iso(), "source": "preset", "preset_id": preset_id, "model_id": model_id},
    )


def case_from_model_defaults(
    model_id: str,
    *,
    facility: FacilityInfo,
    load_composition: LoadComposition,
    block_name: str = "it",
    case_id: str | None = None,
) -> LoadCase:
    """A case whose single block carries `model_id`'s own `default_cons` - the
    starting point for exercising a newly added model before it has any
    preset support. Refine it with `case_with_overrides`."""
    model = get_load_model(model_id)
    if block_name not in BLOCK_NAMES:
        raise ValueError(f"unknown block {block_name!r}; expected one of {', '.join(BLOCK_NAMES)}")
    blocks = {name: None for name in BLOCK_NAMES}
    blocks[block_name] = ModelBlock(model_id=model_id, source="defaults", cons=dict(model.default_cons))
    return LoadCase(
        schema_version=SCHEMA_VERSION,
        case_id=case_id or _new_case_id(),
        facility=facility,
        load_composition=load_composition,
        it_block=blocks["it"],
        vfd_block=blocks["vfd"],
        motor_block=blocks["motor"],
        generation=GenerationInfo(),
        metadata={"created_at": _now_iso(), "source": "defaults", "model_id": model_id},
    )


def case_with_overrides(base: LoadCase, block: str, cons: dict) -> LoadCase:
    """The sweep primitive for varying specific CONs (e.g. VDPA) across a
    range. Validates every key in `cons` against the block's own model's
    `con_names`, raising ValueError listing any unknown key rather than
    silently accepting a typo. Returns a NEW LoadCase (frozen dataclasses, no
    mutation); the touched block's `source` is left unchanged - only its
    `cons`/`overrides` are updated."""
    old = base.block(block)
    if old is None:
        raise ValueError(f"case has no {block} block to override")

    valid_names = set(old.model.con_names)
    unknown = [k for k in cons if k not in valid_names]
    if unknown:
        raise ValueError(f"unknown CON name(s) for block {block!r} ({old.model_id}): {sorted(unknown)}")

    new_block = dataclasses.replace(old, cons={**old.cons, **cons}, overrides={**old.overrides, **cons})
    return dataclasses.replace(base, **{f"{block}_block": new_block})


# --- ui/main_window.py converters (not adopted by ui/main_window.py in this phase) -----------------


# The desktop UI edits the PERC variants (its model-version selector) or a user-defined block on it/vfd, and CLOD on motor.
UI_BLOCK_MODELS = {"it": ("perc1_dll", "perc1_standard", "perc2_standard", "perc2_dll", USER_DEFINED_ID),
                   "vfd": ("perc1_dll", "perc1_standard", "perc2_standard", "perc2_dll", USER_DEFINED_ID),
                   "motor": ("clod",)}


def _require_default_models(case: LoadCase) -> None:
    for name, block in case.blocks().items():
        if block.model_id not in UI_BLOCK_MODELS[name]:
            raise ValueError(
                f"the desktop UI edits {' or '.join(map(repr, UI_BLOCK_MODELS[name]))} for the {name} block; "
                f"this case uses {block.model_id!r}"
            )


def _external_state(block: ModelBlock, name: str) -> dict:
    if not block.is_user_defined:
        return {}
    from editor.user_model import ExternalModel

    return ExternalModel.from_dict(block.external or {}).state_keys(name)


def _external_from_state(merged: dict, name: str) -> dict | None:
    """A user-defined block's `external` from the `{block}_user_*` export-state keys."""
    if merged.get(f"{name}_model_id") != USER_DEFINED_ID:
        return None
    return {"source_file": merged.get(f"{name}_user_source", ""), "records": list(merged.get(f"{name}_user_records", [])),
            "label": merged.get(f"{name}_user_label", ""), "dlls": list(merged.get(f"{name}_user_dlls", []))}


def case_to_ui_state(case: LoadCase) -> dict:
    """Produces a config.DEFAULTS-shaped flat dict. Forces it_advanced/
    vfd_advanced/motor_advanced=True with every CON populated under the
    *_adv_* keys, because export.dyr.get_it_params/get_vfd_params read every
    CON from them and get_clod_params only uses its pass-through values when
    motor_advanced is True - otherwise it re-derives from the archetype and a
    preset/overrides-sourced case's real CON values would be discarded. Every
    caller that needs a dyr-exportable session_state dict should go through
    this function rather than re-deriving the mapping."""
    _require_default_models(case)
    if case.it_block is None:
        raise ValueError("the desktop UI requires an it block")
    state = dict(config.DEFAULTS)
    state.update(
        {
            "facility_name": case.facility.name,
            "bus_number": case.facility.bus_number,
            "bus_name": case.facility.bus_name,
            "use_case": case.facility.use_case,
            "use_case_pct": case.facility.use_case_pct,
            "total_mw": case.facility.total_mw,
            "power_factor": case.facility.power_factor,
            "pct_it": case.load_composition.pct_it,
            "pct_cooling_vfd": case.load_composition.pct_cooling_vfd,
            "pct_cooling_motor": case.load_composition.pct_cooling_motor,
            "pct_other": case.load_composition.pct_other,
            "has_onsite_gen": case.generation.has_onsite_gen,
            "gen_notes": case.generation.notes,
        }
    )

    state["it_advanced"] = True
    state["it_model_id"] = case.it_block.model_id
    state.update(_external_state(case.it_block, "it"))
    for name, value in case.it_block.cons.items():
        state[f"it_adv_{name}"] = value
    state["include_vfd_block"] = case.vfd_block is not None
    if case.vfd_block is not None:
        state["vfd_advanced"] = True
        state["vfd_model_id"] = case.vfd_block.model_id
        state.update(_external_state(case.vfd_block, "vfd"))
        for name, value in case.vfd_block.cons.items():
            state[f"vfd_adv_{name}"] = value
    state["include_motor_block"] = case.motor_block is not None
    if case.motor_block is not None:
        state["motor_advanced"] = True
        clod_keymap = {
            "PC_LM": "clod_adv_lm",
            "PC_SM": "clod_adv_sm",
            "PC_TX": "clod_adv_tx",
            "PC_DL": "clod_adv_dl",
            "PC_CP": "clod_adv_cp",
        }
        for name, value in case.motor_block.cons.items():
            state[clod_keymap[name]] = value
        qualitative = case.motor_block.qualitative or {}
        if qualitative.get("facility_type") is not None:
            state["motor_facility_type"] = qualitative["facility_type"]
        if qualitative.get("has_lighting") is not None:
            state["motor_has_lighting"] = qualitative["has_lighting"]

    return state


def ui_state_to_case(session_state: dict) -> LoadCase:
    """Inverse of case_to_ui_state: reads a dict shaped like ui/main_window.py's
    self.state into a LoadCase, reusing export.dyr.get_it_params/
    get_vfd_params/get_clod_params - the exact functions ui/main_window.py's own export
    path already calls - so this never re-derives the it_advanced/*_adv_*
    resolution logic a second time. Testable with a plain dict literal, no
    PySide6/QApplication import required."""
    merged = dict(config.DEFAULTS)
    merged.update(session_state)

    facility = FacilityInfo(
        name=merged["facility_name"],
        bus_number=int(merged["bus_number"]),
        bus_name=merged["bus_name"],
        use_case=merged["use_case"],
        use_case_pct=int(merged["use_case_pct"]),
        total_mw=float(merged["total_mw"]),
        power_factor=float(merged["power_factor"]),
    )
    load_composition = LoadComposition(
        pct_it=float(merged["pct_it"]),
        pct_cooling_vfd=float(merged["pct_cooling_vfd"]),
        pct_cooling_motor=float(merged["pct_cooling_motor"]),
        pct_other=float(merged["pct_other"]),
    )

    it_block = ModelBlock(
        model_id=merged.get("it_model_id", DEFAULT_BLOCK_MODELS["it"]),
        source="overrides",
        cons=get_it_params(merged),
        external=_external_from_state(merged, "it"),
    )

    vfd_block = None
    if merged.get("include_vfd_block", True):
        vfd_block = ModelBlock(
            model_id=merged.get("vfd_model_id", DEFAULT_BLOCK_MODELS["vfd"]),
            source="overrides",
            cons=get_vfd_params(merged),
            external=_external_from_state(merged, "vfd"),
        )

    motor_block = None
    if merged.get("include_motor_block", False):
        motor_source = "overrides" if merged.get("motor_advanced") else "archetype"
        motor_block = ModelBlock(
            model_id=DEFAULT_BLOCK_MODELS["motor"],
            source=motor_source,
            qualitative={
                "facility_type": merged.get("motor_facility_type"),
                "has_lighting": merged.get("motor_has_lighting"),
            },
            cons=get_clod_params(merged),
        )

    generation = GenerationInfo(
        has_onsite_gen=bool(merged.get("has_onsite_gen", False)),
        notes=str(merged.get("gen_notes", "")),
    )

    return LoadCase(
        schema_version=SCHEMA_VERSION,
        case_id=_new_case_id(),
        facility=facility,
        load_composition=load_composition,
        it_block=it_block,
        vfd_block=vfd_block,
        motor_block=motor_block,
        generation=generation,
        metadata={"created_at": _now_iso(), "source": "ui_state"},
    )
