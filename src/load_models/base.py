"""The load-model contract every registered model implements, plus the small
.dyr helpers and default disturbance shared across models.

Adding a model means building one `LoadModel` (see docs/developer/ADDING_A_LOAD_MODEL.md);
everything downstream - case JSON, `.dyr` export, the mock runner, envelope
validation, sweeps and reports - dispatches through it by `model_id`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# The app's default disturbance: a single constant-depth voltage event starting
# at FAULT_START, lasting FAULT_DURATION seconds at V_FAULT pu. Analytic
# simulators always start the event at FAULT_START.
FAULT_START = 0.5
FAULT_DURATION = 0.083
V_FAULT = 0.30

# The default frequency event: FREQUENCY_EVENT_HZ held for
# FREQUENCY_EVENT_DURATION seconds, starting at FAULT_START.
NOMINAL_FREQUENCY_HZ = 60.0
FREQUENCY_EVENT_DURATION = 60.0
FREQUENCY_EVENT_HZ = 58.5

@dataclass(frozen=True)
class RecordScope:
    """Which loads a PSS/E load-model record applies to. The vendor PERC1
    documentation (Rev7, "DYRE FORMAT") names the record 'PERC**' with ** =
    BL/OW/ZN/AR/AL and sets IT = 1-5 to match. The record's first field is the
    bus, owner, zone or area number (0 for All) - that part is the standard
    PSS/E load-model convention; the vendor text only shows the bus form."""

    id: str
    label: str
    suffix: str
    it: int
    number_label: str | None  # None: the record's first field is always 0

    def model_name(self, family: str) -> str:
        return f"{family}{self.suffix}"


RECORD_SCOPES: dict[str, RecordScope] = {
    scope.id: scope
    for scope in (
        RecordScope("bus", "Bus", "BL", 1, "Bus number"),
        RecordScope("owner", "Owner", "OW", 2, "Owner number"),
        RecordScope("zone", "Zone", "ZN", 3, "Zone number"),
        RecordScope("area", "Area", "AR", 4, "Area number"),
        RecordScope("all", "All", "AL", 5, None),
    )
}


def get_record_scope(scope_id: str) -> RecordScope:
    try:
        return RECORD_SCOPES[scope_id]
    except KeyError:
        raise ValueError(f"unknown record scope {scope_id!r}; expected one of {', '.join(RECORD_SCOPES)}") from None


def record_number(scope_id: str, bus_number: int, subsystem_number: int | None = None) -> int:
    """The record's first field: the bus number for Bus, the owner/zone/area
    number for those scopes, and 0 for All."""
    scope = get_record_scope(scope_id)
    if scope.id == "bus":
        return int(bus_number)
    if scope.id == "all":
        return 0
    if subsystem_number is None:
        raise ValueError(f"{scope.label}-scoped records need the {scope.number_label.lower()}")
    return int(subsystem_number)


@dataclass(frozen=True)
class LoadModel:
    """Everything the backend needs to store, export, run, and validate one
    PSS/E dynamic load model. Only the required fields are needed to store
    and export a model; each optional hook unlocks one more stage of the
    developer loop.

    Required:
      id               registry key, stored as `model_id` on every case block
      label            human-readable name
      description      one or two sentences on what the model represents
      dyr_model_name   the model name as it appears quoted in a .dyr record
                       (e.g. "PERCBL") - used to recognise a record in .dyr text
      con_names        every CON in .dyr order
      default_cons     a value for every name in `con_names`
      display_fields   (con_name, label) or (con_name, label, tooltip) rows
                       worth showing in reports
      build_dyr_record (number, load_id, cons) -> .dyr record text, where
                       number is the record's first field (the bus number
                       for a bus-scoped record). A model that sets
                       supports_record_scopes also takes scope="bus" |
                       "owner" | "zone" | "area" | "all" (RECORD_SCOPES).

    Optional hooks:
      parse_dyr_record (dyr_text) -> cons; the inverse of build_dyr_record.
                       Required (with `simulate`) for the mock runner.
      simulate         (cons, fault_duration_s, fault_voltage_pu) -> response
                       dict with at least v_points, p_points, sim_end, trips,
                       trip_type and markers (see perc1_dll/simulation.py).
      simulate_frequency
                       (cons, fault_duration_s, fault_frequency_hz) -> the same
                       response shape plus f_points, for a constant frequency
                       excursion. Enables frequency scenarios in the mock runner.
      cons_for_preset  (RideThroughPreset, block_name) -> full CON dict that
                       encodes that preset's ride-through envelope. Enables
                       `case_from_preset`, sweeps, and envelope validation.
      unmodelled_events  ("overvoltage" and/or "frequency") disturbances the model cannot respond to
      matches_dyr      (dyr_text) -> bool; tells this model's record from another model's that has the same name
      result_figure    (result, cons, block_label, *, envelope,
                       overvoltage_envelope, height) -> plotly Figure for case
                       reports. Reports fall back to a generic voltage/power
                       plot without it.
    """

    id: str
    label: str
    description: str
    dyr_model_name: str
    con_names: tuple[str, ...]
    default_cons: Mapping[str, float]
    display_fields: tuple[tuple[str, ...], ...]
    build_dyr_record: Callable[[int, str, Mapping], str]
    parse_dyr_record: Callable[[str], dict] | None = None
    simulate: Callable[[Mapping, float, float], dict] | None = None
    simulate_frequency: Callable[[Mapping, float, float], dict] | None = None
    # Record names this model also writes (e.g. PERCOW/PERCZN/... for the
    # non-bus scopes), so find_model_for_dyr recognises every form.
    dyr_model_aliases: tuple[str, ...] = ()
    supports_record_scopes: bool = False
    cons_for_preset: Callable[..., dict] | None = None
    result_figure: Callable[..., object] | None = None
    # Disturbances the model has no logic for ("overvoltage", "frequency"): envelope validation reports them as
    # not modelled instead of failing a trip the model can never make.
    unmodelled_events: tuple[str, ...] = ()
    # (dyr_text) -> bool: for two models that share a record name (the PERC1 DLL and the PERC2 DLL v2.3 both write
    # PERCBL), whether `dyr_text` holds this model's record. find_model_for_dyr checks it after the name.
    matches_dyr: Callable[[str], bool] | None = None

    @property
    def can_run_mock(self) -> bool:
        return self.parse_dyr_record is not None and self.simulate is not None

    @property
    def supports_presets(self) -> bool:
        return self.cons_for_preset is not None

    def capabilities(self) -> dict:
        return {
            "dyr_export": True,
            "dyr_parse": self.parse_dyr_record is not None,
            "mock_run": self.can_run_mock,
            "frequency_mock_run": self.can_run_mock and self.simulate_frequency is not None,
            "ride_through_presets": self.supports_presets,
            "custom_result_figure": self.result_figure is not None,
            "record_scopes": list(RECORD_SCOPES) if self.supports_record_scopes else ["bus"],
        }


def format_con(value):
    """Render a single CON value. NPA/NQA are true integers (0/1/2 ZIP
    exponent selectors) in the model; everything else is a plain decimal."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return f"{value:.4f}"


def validate_load_id(load_id):
    """PSS/E's static Load/USRLOD identifier field is `character*2` - a real
    PSS/E case rejects anything longer ("Load identifier is more than two
    characters", confirmed directly against PSS/E v35.6.4's own
    `load_data_6` API), and a blank identifier is likewise invalid. Every
    .dyr-generating function must call this before embedding a load_id in
    exported text, since nothing upstream (dev/validation/case_model.py, app/config.py) checks
    length - a bad value would otherwise only surface as a PSS/E load error
    long after export."""
    if not load_id or len(load_id) > 2:
        raise ValueError(
            f"invalid PSS/E load id {load_id!r}: must be 1-2 characters "
            "(PSS/E's Load/USRLOD identifier field is character*2)"
        )
