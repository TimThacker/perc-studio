# Adding a load model

The backend is model-agnostic. PERC1 is one registered load model and CLOD
is another. Case JSON, `.dyr` export, the mock runner, envelope validation,
sweeps, reports and the `perc-studio` CLI all look a block's model up by its
`model_id`, so they need no changes for a new one.

A model is one `LoadModel` object (`src/load_models/base.py`). Only the
required fields are needed to store and export it. Each optional hook unlocks
one more stage of the developer workflow:

| Field / hook | Required? | Unlocks |
|---|---|---|
| `id`, `label`, `description` | yes | Registry entry; `model_id` in case JSON |
| `dyr_model_name` | yes | Recognising the model's record in `.dyr` text |
| `dyr_model_aliases`, `supports_record_scopes` | optional | Owner/zone/area/all-scoped records (`PERCOW`, `PERCZN`, ...) |
| `matches_dyr` | optional | Telling this model's record from another model's that has the same name (the PERC1 DLL and the PERC2 DLL v2.3 both write `PERCBL`) |
| `con_names`, `default_cons` | yes | CON validation, `--source defaults`, overrides |
| `display_fields` | yes (may be empty) | CON tables in reports |
| `build_dyr_record` | yes | `perc-studio export dyr` |
| `parse_dyr_record` + `simulate` | optional | `perc-studio run` with the mock runner |
| `simulate_frequency` | optional | Frequency scenarios (`--fault-frequency-hz`) with the mock runner |
| `unmodelled_events` | optional | Envelope validation reports `"overvoltage"`/`"frequency"` as not modelled instead of failing them |
| `cons_for_preset` | optional | `--source preset`, `perc-studio sweep`, envelope validation |
| `result_figure` | optional | A model-specific report figure (a generic voltage/power plot is used otherwise) |

## Package layout

Every built-in model is one package, `src/load_models/<model_id>/`, with the
same files and the same public names. A file exists only if the model has the
hook it backs. `<id>` below is the model id itself (`perc2_dll`, not `perc2`):

| File | Public names | Backs |
|---|---|---|
| `__init__.py` | `MODEL`, `__all__` | The registry entry |
| `cons.py` | `CON_NAMES` (tuple, record order, any ICONs first), `DEFAULT_CONS` (dict), `DISPLAY_FIELDS` (tuple of `(con, label[, tooltip])`); optional `ICON_NAMES`, `CON_ONLY_NAMES`, `CON_SPECS`, `ConIssue`, `validate_cons(cons, ...) -> list[ConIssue]` | `con_names`, `default_cons`, `display_fields` |
| `dyr.py` | `build_<id>_record(number, load_id, cons, scope="bus", ...)`; with a parser, `parse_<id>_record(dyr_text) -> dict` and `parse_<id>_records(dyr_text) -> list[dict]` (every record in a file, for `.dyr` import); with a shared record name, `is_<id>_record(dyr_text) -> bool` | `build_dyr_record`, `parse_dyr_record`, `matches_dyr` |
| `simulation.py` | `simulate_<id>_response(cons, fault_duration_s, fault_voltage_pu)`, `simulate_<id>_frequency_response(cons, fault_duration_s, fault_frequency_hz)` | `simulate`, `simulate_frequency` |
| `presets.py` | `cons_for_preset(preset, block_name) -> dict`, `preset_gaps(preset) -> list[str]` (what the preset asks for that the model cannot encode; `[]` if nothing) | `cons_for_preset` |

Rules:

- **`__init__.py` only wires.** It has a docstring saying what the model is
  and what each file holds, imports from its own files, builds `MODEL`, and
  lists `MODEL` (plus any helpers the UI needs, such as `preset_gaps` and
  `validate_cons`) in `__all__`. It holds no logic. The one exception is an
  adapter that has to import lazily to avoid a cycle, such as `perc1_dll`'s
  `_result_figure`.
- **Every file has the same shape.** A module docstring, then
  `from __future__ import annotations`, imports, constants, private helpers
  (leading underscore), public functions, and last of all `__all__`, which
  lists exactly the public names the file defines. A test checks the
  docstring and `__all__`. Anything else a model exposes beyond the table
  (for example `perc1_dll`'s `simulate_perc1_dll_event`, which the preview
  calls) is a public name like any other and goes in `__all__`.
- **`cons.py` runs in one order:** the names (`ICON_NAMES`, `CON_ONLY_NAMES`
  where the model has them, then `CON_NAMES`), then `DEFAULT_CONS`, then
  `DISPLAY_FIELDS`, then the rest (`ConIssue`, `validate_cons` and any
  helpers). `validate_cons` is optional: a model has one only if PSS/E
  rejects or silently changes some of its values and that was measured. A PSS/E
  flag test (`flag_on`) lives here too, and nowhere else in the package.
- **`dyr.py` starts with the same header constants:** `FAMILY`, `MODEL_CODE`,
  `N_ICON`, `N_CON`, `N_STATE`, `N_VAR`, `N_RESERVED_ICON` (the numbers in the
  record header; the writer and the parser both use them, never a literal),
  and defines `strip_comments(text)`. The scope lookup is a private
  `_SCOPE_BY_SUFFIX`.
- **`simulation.py` names its internals the same way:** `_response` is the core
  that runs one event, `_run_logic` the cease/reconnect state machine, and the
  public functions are thin wrappers over them. A model with a second path
  (`perc2_dll`'s momentary cessation) prefixes it: `_run_mc_logic`,
  `_mc_voltage_response`.
- **`MODEL` takes the module objects as they are.** Pass `con_names=CON_NAMES`,
  not `tuple(...)` or `dict(...)` copies. The `LoadModel(...)` arguments go in
  the order of the table at the top of this page.
- **Function names carry the model id; constants don't.** Two models'
  functions are often imported side by side (tests, `editor/dyr_import.py`),
  so they need distinct names. Constants are per-module. When another module
  imports one, it aliases it with the model's prefix:
  `from load_models.perc1_dll.cons import DEFAULT_CONS as PERC1_DEFAULT_CONS`.
- **Each model is defined in full in its own files.** Two models may use a
  CON name, a check or a constant that looks the same, but PSS/E may treat it
  differently in each. Keep a separate copy in each package rather than
  moving it to a shared module. A model imports nothing from another model
  package and no shared helper module; its only imports from `load_models`
  are `..base` (the `LoadModel` contract and the `.dyr` helpers every record
  writer uses). That includes small helpers such as a flag test or a preset
  bundle lookup: copy them. The CON names a model writes to its `.dyr` record
  stay as the vendor spells them, whatever another model calls the same CON.
- `tests/test_load_models.py::test_builtin_model_follows_the_package_layout`
  checks these names for every built-in model, and
  `test_builtin_models_import_nothing_from_each_other` checks the import rule.

CLOD (`clod/`) is the export-only case: `cons.py` and `dyr.py`, nothing else.
The [worked example](#worked-example-a-step-trip-model) below is a complete
model in this layout.

## Worked example: a step-trip model

A complete model small enough to read in one sitting: one undervoltage and one
overvoltage trip point, no reconnect, so four CONs. It writes
`IBUS 'USRLOD' 'ID' 'STPBL' 12 IT 0 4 1 1 0 CON(J) .. CON(J+3) /`, simulates the
trip, and collapses a ride-through preset to its most demanding point per
direction. Every file follows the layout above, and `tests/test_doc_example.py`
writes these blocks to a package and checks them against the layout rules, so
the example cannot drift from them. The hooks it leaves out
(`simulate_frequency`, `matches_dyr`, `validate_cons`, `result_figure`) are
optional; see the table at the top of this page. For a model that is fully
built out, read [`perc1_standard/`](../../src/load_models/perc1_standard/).

**`cons.py`**: names first, then defaults, then the display rows.

```python step_trip/cons.py
"""Step-trip CONs: one undervoltage and one overvoltage trip point."""

from __future__ import annotations

CON_NAMES = ("VUV", "TUV", "VOV", "TOV")

DEFAULT_CONS = {"VUV": 0.70, "TUV": 0.10, "VOV": 1.20, "TOV": 0.50}

DISPLAY_FIELDS = (
    ("VUV", "Undervoltage trip threshold (pu)", "VUV"),
    ("TUV", "Undervoltage trip delay (s)", "TUV"),
    ("VOV", "Overvoltage trip threshold (pu)", "VOV"),
    ("TOV", "Overvoltage trip delay (s)", "TOV"),
)


__all__ = [
    "CON_NAMES",
    "DEFAULT_CONS",
    "DISPLAY_FIELDS",
]
```

**`dyr.py`**: the header constants, `strip_comments`, a writer, and a parser that reads every record in a file (`parse_<id>_record` returns the first one's CONs, as `LoadModel.parse_dyr_record` expects).

```python step_trip/dyr.py
""".dyr writer and parser for the step-trip model: `IBUS 'USRLOD' 'ID' 'STPBL' 12 IT 0 4 1 1 0 CON(J) .. CON(J+3) /`."""

from __future__ import annotations

import re

from ..base import RECORD_SCOPES, format_con, get_record_scope, validate_load_id
from .cons import CON_NAMES

FAMILY = "STP"
MODEL_CODE = 12
N_ICON, N_CON, N_STATE, N_VAR, N_RESERVED_ICON = 0, 4, 1, 1, 0

_SCOPE_BY_SUFFIX = {scope.suffix: scope for scope in RECORD_SCOPES.values()}
_RECORD_RE = re.compile(
    rf"(?P<number>\d+)\s+'USRLOD'\s+'(?P<id>[^']+)'\s+'{FAMILY}(?P<suffix>BL|OW|ZN|AR|AL)'\s+(?P<values>[^/]*)/"
)


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("@!", "//")))


def build_step_trip_record(number, load_id, cons, scope="bus") -> str:
    validate_load_id(load_id)
    sc = get_record_scope(scope)
    header = f"{MODEL_CODE} {sc.it} {N_ICON} {N_CON} {N_STATE} {N_VAR} {N_RESERVED_ICON}"
    values = " ".join(format_con(cons[name]) for name in CON_NAMES)
    return f"@! {' '.join(CON_NAMES)}\n{number} 'USRLOD' '{load_id}' '{sc.model_name(FAMILY)}' {header} {values} /"


def parse_step_trip_records(dyr_text: str) -> list[dict]:
    """Every step-trip record in the text: scope, number, load_id and cons (`error` set when the CON count is wrong)."""
    records = []
    for match in _RECORD_RE.finditer(strip_comments(dyr_text)):
        values = [float(token) for token in match.group("values").split()[7:]]
        record = {"scope": _SCOPE_BY_SUFFIX[match.group("suffix")].id, "number": int(match.group("number")),
                  "load_id": match.group("id"), "cons": {}, "error": None}
        if len(values) == N_CON:
            record["cons"] = dict(zip(CON_NAMES, values))
        else:
            record["error"] = f"expected {N_CON} CON values, got {len(values)}"
        records.append(record)
    return records


def parse_step_trip_record(dyr_text: str) -> dict:
    records = parse_step_trip_records(dyr_text)
    if not records:
        raise ValueError(f"no {FAMILY}** record found")
    if records[0]["error"]:
        raise ValueError(records[0]["error"])
    return records[0]["cons"]


__all__ = [
    "FAMILY",
    "MODEL_CODE",
    "N_CON",
    "N_ICON",
    "N_RESERVED_ICON",
    "N_STATE",
    "N_VAR",
    "build_step_trip_record",
    "parse_step_trip_record",
    "parse_step_trip_records",
    "strip_comments",
]
```

**`simulation.py`**: `_response` is the core; the public function is a thin wrapper over it. The response dict is what the live chart and the mock runner read.

```python step_trip/simulation.py
"""Step-trip response: the block trips if the event crosses a threshold for at least that threshold's delay."""

from __future__ import annotations

from ..base import FAULT_DURATION, FAULT_START, V_FAULT


def _response(cons, fault_duration_s, fault_voltage_pu):
    if fault_voltage_pu <= cons["VUV"] and fault_duration_s >= cons["TUV"]:
        trip_type, delay = "undervoltage", cons["TUV"]
    elif fault_voltage_pu >= cons["VOV"] and fault_duration_s >= cons["TOV"]:
        trip_type, delay = "overvoltage", cons["TOV"]
    else:
        trip_type, delay = None, None
    fault_end = FAULT_START + fault_duration_s
    sim_end = fault_end + 1.0
    v_points = [(0.0, 1.0), (FAULT_START, 1.0), (FAULT_START, fault_voltage_pu),
                (fault_end, fault_voltage_pu), (fault_end, 1.0), (sim_end, 1.0)]
    if trip_type:
        trip_time = FAULT_START + delay
        p_points = [(0.0, 1.0), (trip_time, 1.0), (trip_time, 0.0), (sim_end, 0.0)]
        markers = {"trip_time": trip_time}
    else:
        p_points = [(0.0, 1.0), (sim_end, 1.0)]
        markers = {}
    return {"v_points": v_points, "p_points": p_points, "sim_end": sim_end,
            "trips": trip_type is not None, "trip_type": trip_type, "markers": markers}


def simulate_step_trip_response(cons, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT):
    return _response(cons, fault_duration_s, fault_voltage_pu)


__all__ = [
    "simulate_step_trip_response",
]
```

**`presets.py`**: `cons_for_preset` maps a preset onto the model's CONs, and `preset_gaps` says what it could not encode. The import of `presets.ridethrough` is lazy because that module imports `load_models` when it loads.

```python step_trip/presets.py
"""Ride-through presets for the step-trip model: each preset collapses to its most demanding point per direction."""

from __future__ import annotations


def cons_for_preset(preset, block_name: str) -> dict:
    from presets.ridethrough import (  # lazy: presets import load_models
        collapsed_overvoltage_point,
        collapsed_point,
    )

    under = collapsed_point(preset.envelope)
    over = collapsed_overvoltage_point(preset.overvoltage_envelope)
    return {"VUV": under.voltage_pu, "TUV": under.min_duration_s, "VOV": over.voltage_pu,
            "TOV": over.min_duration_s if over.min_duration_s is not None else 2.0}


def preset_gaps(preset) -> list[str]:
    """What the preset asks for that this model cannot encode: its other envelope points and any reconnect."""
    return ["only the most demanding point per direction is kept; the model never reconnects"]


__all__ = [
    "cons_for_preset",
    "preset_gaps",
]
```

**`__init__.py`**: wiring only.

```python step_trip/__init__.py
"""Step-trip model: one undervoltage and one overvoltage trip point, no reconnect.

`cons.py` holds the four CONs, `dyr.py` writes and parses the `STPBL` record, `simulation.py` is the analytic response
and `presets.py` collapses a ride-through preset to its most demanding point per direction.
"""

from __future__ import annotations

from ..base import LoadModel
from .cons import CON_NAMES, DEFAULT_CONS, DISPLAY_FIELDS
from .dyr import build_step_trip_record, parse_step_trip_record
from .presets import cons_for_preset, preset_gaps
from .simulation import simulate_step_trip_response

MODEL = LoadModel(
    id="step_trip",
    label="Step-trip model",
    description="Single undervoltage and overvoltage trip point, no reconnect.",
    dyr_model_name="STPBL",
    dyr_model_aliases=("STPOW", "STPZN", "STPAR", "STPAL"),
    supports_record_scopes=True,
    con_names=CON_NAMES,
    default_cons=DEFAULT_CONS,
    display_fields=DISPLAY_FIELDS,
    build_dyr_record=build_step_trip_record,
    parse_dyr_record=parse_step_trip_record,
    simulate=simulate_step_trip_response,
    cons_for_preset=cons_for_preset,
)

__all__ = ["MODEL", "preset_gaps"]
```

Then register it (`step_trip.MODEL` in `_BUILTIN_MODELS`) and follow the
steps below. `tests/test_load_models.py` picks the model up from the registry
and runs the contract tests and the layout checks against it.

## Steps

1. **Create the package.** Add `src/load_models/<model_id>/` with the files
   from [Package layout](#package-layout) that your model's hooks need.
   [`perc1_standard/`](../../src/load_models/perc1_standard/) is a complete
   example.
2. **Build `MODEL`.** Define a `LoadModel` in that `__init__.py` from the
   names your files export.
3. **Register it.** Add `<model_id>.MODEL` to `_BUILTIN_MODELS` in
   [`src/load_models/__init__.py`](../../src/load_models/__init__.py).
4. **Run the tests.** `uv run pytest tests/test_load_models.py` runs the
   contract tests against every registered model. They check unique,
   fully-defaulted CONs, display fields that name real CONs, a `.dyr` record
   the registry can recognise, a parse round-trip, the simulator's response
   shape, preset encoding, and the package layout. You don't need to write new
   tests for this. `tests/test_model_regression.py` also compares every
   registered model with a golden file in `tests/golden/`, so it fails for a
   new model until you record its baseline with
   `UPDATE_GOLDEN=1 uv run pytest tests/test_model_regression.py`. Review the
   new `tests/golden/<model_id>.json` before committing it. The same command is
   how you accept a deliberate change to an existing model's behavior.
5. **Exercise it end to end** with the CLI:

   ```bash
   uv run perc-studio models list                      # is it registered, what can it do?
   uv run perc-studio params generate --source defaults --model <model_id> --out case.json
   uv run perc-studio params generate --source overrides --base-case case.json \
       --override it.<CON>=<value> --out case.json
   uv run perc-studio export dyr case.json
   uv run perc-studio run case.json --fault-duration-s 0.5 --fault-voltage-pu 0.5
   ```

   With a `cons_for_preset` hook, sweep it over every ride-through preset by
   adding `"model": "<model_id>"` to a sweep spec (see
   [`tests/fixtures/sweep_example.json`](../../tests/fixtures/sweep_example.json)):

   ```bash
   uv run perc-studio sweep my_sweep.json
   ```

## Hook contracts

- **`build_dyr_record(number, load_id, cons) -> str`**: one complete
  `.dyr` record; `number` is its first field (the bus number for a
  bus-scoped record). A model whose record name varies with the PSS/E
  subsystem scope (like PERC1's `PERCBL`/`PERCOW`/`PERCZN`/`PERCAR`/`PERCAL`)
  sets `supports_record_scopes=True`, takes a `scope` keyword, and lists the
  extra names in `dyr_model_aliases`. Call `load_models.base.validate_load_id(load_id)` first. The
  model name must appear quoted (`'<dyr_model_name>'`), because
  `find_model_for_dyr` uses it to pick the parser. If another model writes
  the same name, give both a `matches_dyr(dyr_text) -> bool` that tells the
  records apart by something else (`perc1_dll` and `perc2_dll` use the
  header's CON count, 173 or 179); `find_model_for_dyr` checks it after the
  name.
- **`parse_dyr_record(dyr_text) -> dict`**: the exact inverse, returning every
  CON. The mock runner parses the exported text instead of reusing the
  in-memory dict, so export bugs show up in testing.
- **`simulate(cons, fault_duration_s, fault_voltage_pu) -> dict`**: the
  response to one constant-depth event starting at `base.FAULT_START`. Must
  include `v_points` and `p_points` (lists of `(t, value)` points), `sim_end`,
  `trips`, `trip_type` (`"undervoltage"`, `"overvoltage"` or `None`) and
  `markers` (`trip_time`, and optionally `reconnect_end`). This is an analytic
  stand-in, not PSS/E.
- **`simulate_frequency(cons, fault_duration_s, fault_frequency_hz) -> dict`**:
  the same response shape as `simulate`, plus `f_points`, for a constant
  frequency excursion; `trip_type` is `"underfrequency"`, `"overfrequency"`
  or `None`.
- **`cons_for_preset(preset, block_name) -> dict`**: every CON, encoding a
  `presets.ridethrough.RideThroughPreset`. The preset's `envelope` and
  `overvoltage_envelope` (and the optional `frequency_ride_through` table) are
  model-agnostic. The `it_bundle` and
  `vfd_bundle` fields are PERC1 CONs, so a new model should read the
  envelopes instead. `presets.ridethrough.collapsed_point` and
  `multi_stage_undervoltage` are useful helpers.
- **`result_figure(result, cons, block_label, *, envelope, overvoltage_envelope, height)`**:
  returns a plotly figure for case reports.

`load_models/perc1_standard/` is a worked example of a model with a different
`.dyr` record shape (composite load: a `MAINxx10` record plus the component),
validated limits (`CON_SPECS`, `validate_cons`) and a preset mapper that says
what it cannot encode (`preset_gaps`). `load_models/perc2_standard/` adds ICONs
(its six flags are stored as integer entries at the front of the CON dict, in
record order) and a simulator that reports every cease/reconnect cycle
(`trip_events`, `reconnect_events`). Validate a new model against PSS/E (for
example with `perc-studio blackbox`, or your own runs): slot-by-slot CON order,
clamps, behavior, and the app's own exported records.

## What stays PERC1/CLOD-specific

- **Desktop UI** (`src/ui/block.py`): the parameter rows are built from a
  `editor.model_ui.ModelUiSpec` (fields, groups, bounds, defaults, preset mapping,
  notes) and the IT/VFD/Screening blocks have a model selector, so a
  PERC1-family model is added to the UI with one spec and, if its response
  differs, one preview page (`preview/standard.py` is the example). `dev.validation.case_model.case_to_ui_state`/`ui_state_to_case` carry the
  per-block model id for the PERC1 variants, user-defined (imported `.dyr`)
  blocks and CLOD, and reject any other model (`dev.validation.case_model.UI_BLOCK_MODELS`).
- **CLOD archetype derivation** (`load_models/clod/cons.py`,
  `derive_clod_params`): turns the motor facility archetype into CLOD CONs.
- **Ride-through preset bundles** (`presets/ridethrough.py`): each preset's
  `it_bundle`/`vfd_bundle` is precomputed PERC1 CONs. Other models derive
  their own CONs from the envelopes through `cons_for_preset`.

## Facility blocks vs. models

A case has three facility blocks: `it`, `vfd` and `motor`. The block is the
part of the facility's load; the model is how PSS/E represents it. By
default `it`/`vfd` use `perc1_dll` and `motor` uses `clod`
(`load_models.DEFAULT_BLOCK_MODELS`), but any block can carry any registered
model. Ride-through presets and sweeps apply to the `it`/`vfd` blocks.
