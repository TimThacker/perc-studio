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
| `con_names`, `default_cons` | yes | CON validation, `--source defaults`, overrides |
| `display_fields` | yes (may be empty) | CON tables in reports |
| `build_dyr_record` | yes | `perc-studio export dyr` |
| `parse_dyr_record` + `simulate` | optional | `perc-studio run` with the mock runner |
| `simulate_frequency` | optional | Frequency scenarios (`--fault-frequency-hz`) with the mock runner |
| `cons_for_preset` | optional | `--source preset`, `perc-studio sweep`, envelope validation |
| `result_figure` | optional | A model-specific report figure (a generic voltage/power plot is used otherwise) |
| `matches_dyr` | optional | Telling this model's record from another model's that has the same name (the PERC1 DLL and the PERC2 DLL v2.3 both write `PERCBL`) |

## Steps

1. **Create the package.** Add `src/load_models/<model_id>/__init__.py`.
   Split it into `cons.py`/`dyr.py`/`simulation.py` like
   [`perc1_dll/`](../../src/load_models/perc1_dll/) once it grows past a few
   dozen lines.
2. **Build `MODEL`.** Define a `LoadModel` in that `__init__.py`.
   [`tests/fixtures/example_load_model.py`](../../tests/fixtures/example_load_model.py)
   is a complete, working model with every hook in about 100 lines. Copy it as
   a starting point.
3. **Register it.** Add `<model_id>.MODEL` to `_BUILTIN_MODELS` in
   [`src/load_models/__init__.py`](../../src/load_models/__init__.py).
4. **Run the tests.** `uv run pytest tests/test_load_models.py` runs the
   contract tests against every registered model. They check unique,
   fully-defaulted CONs, display fields that name real CONs, a `.dyr` record
   the registry can recognise, a parse round-trip, the simulator's response
   shape, and preset encoding. You don't need to write new tests for this.
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
