# File formats

[perc-studio](../README.md) > File formats

The JSON files `perc-studio` reads and writes. Each is defined by a plain Python module, so you can also build them in
code.

- [`LoadCase`](#loadcase) - the parameterization every command consumes
- [Fault scenario](#fault-scenario) - one constant voltage or frequency disturbance
- [`SimulationResult`](#simulationresult) - what `run` produces
- [Sweep spec](#sweep-spec) and its [output tree](#sweep-output-tree)

## LoadCase

Defined in `src/dev/validation/case_model.py`. `params generate`, `dyr to-case` and `sweep` produce it; `params`,
`export`, `run`, `validate` and `report` consume it.

```json
{
  "schema_version": 3,
  "case_id": "case-8ff73182f545",
  "facility": {
    "name": "Example Data Center", "bus_number": 100001, "bus_name": "DC_POI",
    "use_case": "AI Training", "use_case_pct": 100, "total_mw": 300.0, "power_factor": 0.99
  },
  "load_composition": { "pct_it": 70.0, "pct_cooling_vfd": 20.0, "pct_cooling_motor": 5.0, "pct_other": 5.0 },
  "it_block": {
    "model_id": "perc1_dll",
    "source": "preset",
    "cons": { "VDPA": 0.9, "DMA": 2.0, "...": "every CON of the block's model - 173 for perc1_dll" },
    "qualitative": null,
    "preset_id": "ercot_nogrr282",
    "overrides": {},
    "external": null
  },
  "vfd_block": { "...": "same shape as it_block, or null if the case has no VFD block" },
  "motor_block": {
    "model_id": "clod",
    "source": "archetype",
    "cons": { "PC_LM": 35.0, "PC_SM": 35.0, "PC_TX": 5.0, "PC_DL": 5.0, "PC_CP": 10.0 },
    "qualitative": { "facility_type": "Mixed - moderate mix of large & small motors", "has_lighting": false },
    "preset_id": null, "overrides": {}, "external": null
  },
  "generation": { "has_onsite_gen": false, "notes": "" },
  "metadata": { "created_at": "2026-10-26T01:13:03+00:00", "source": "preset", "preset_id": "ercot_nogrr282", "model_id": "perc1_dll" }
}
```

- Each block names its load model (`model_id`, a key of `load_models.LOAD_MODELS`) and its `cons` are **always fully
  populated** with exactly that model's CONs, never partial. `models show MODEL` lists them.
- `source` is how the block was built: `preset` (a ride-through preset encoded by the model), `defaults` (the
  model's own `default_cons`), `overrides` (a case with explicit values layered on), or `archetype` (a CLOD motor
  block derived from its facility archetype, kept in `qualitative`). `overrides` records which CONs were set explicitly; `dyr to-case` leaves `source` as
  `defaults` and puts every imported CON in `overrides`.
- `external` is only used by the desktop app's user-defined (black-box) block (`model_id` `user_defined`), whose
  records are held unedited; `params`/`export` of such a case is limited to what the app supports.
- `mw_it`, `mw_vfd`, `mw_motor` and `is_load_split_valid` are computed from `facility`/`load_composition`, never
  stored, so they cannot drift.
- `schema_version` is checked on load. Version 1 and 2 files are migrated automatically; any other value is a hard
  error (exit 3 from `params validate`, a Python `ValueError` if loaded directly).
- The desktop app's own state converts to and from a case (`case_to_ui_state`/`ui_state_to_case`), which is how
  `export facility` and `export report` produce byte-for-byte the files the app would.

## Fault scenario

Defined by `psse.runner.FaultScenario`. One constant disturbance starting at `fault_start_s`:

```json
{ "id": "sag_0.5pu_1s", "fault_start_s": 0.5, "fault_duration_s": 1.0, "fault_voltage_pu": 0.5, "description": "" }
```

```json
{ "id": "freq_58.5hz_310s", "fault_start_s": 0.5, "fault_duration_s": 310.0, "fault_frequency_hz": 58.5 }
```

| Field | Meaning |
|---|---|
| `id` | Name used in file names and reports. |
| `fault_start_s` | When the event starts. The mock runner ignores it (always 0.5 s) and says so in `warnings`. |
| `fault_duration_s` | How long the event lasts. |
| `fault_voltage_pu` | Voltage during the event; above 1.0 is a swell. Default 1.0. |
| `fault_frequency_hz` | Present for a frequency event; voltage stays nominal. |
| `description` | Free text. |

`scenario make` and `scenario suite` write these; `run --scenario` reads one; a sweep spec holds a list.

## SimulationResult

Defined by `psse.runner.SimulationResult`; `run` returns it as `data.result` and writes it to `--out`.

| Field | Meaning |
|---|---|
| `case_id`, `block_name`, `scenario_id` | What was run. |
| `time_s`, `voltage_pu`, `active_power_pu`, `reactive_power_pu`, `frequency_hz` | The traces (`frequency_hz` only for frequency events; `reactive_power_pu` may be `null`). |
| `tripped`, `trip_time_s`, `trip_type` | Whether the load tripped, when, and why (`undervoltage`, `overvoltage`, `underfrequency`, `overfrequency`). |
| `reconnect_time_s`, `final_power_pu` | Recovery. |
| `runner_id` | `mock` or `psse`. |
| `raw_case_path`, `dyr_text_sha256` | Provenance: the `.raw` case path recorded, and the hash of the exact `.dyr` text run. |
| `warnings` | Runner notes (e.g. the mock ignoring `fault_start_s`). |
| `metadata` | `scenario` (the scenario that produced the result - `validate results` and `report case` read it back, so the scenario is not passed twice), plus runner details. |

## Sweep spec

JSON, or YAML (`.yaml`/`.yml`; `pyyaml` is a project dependency). Describes the cartesian product of presets x
scenarios that `sweep` runs:

```json
{
  "sweep_id": "ercot_spp_probe",
  "base_case": {
    "facility": {
      "name": "Example Data Center", "bus_number": 101, "bus_name": "BUS_101",
      "total_mw": 300.0, "power_factor": 0.99,
      "pct_it": 70.0, "pct_cooling_vfd": 20.0, "pct_cooling_motor": 5.0, "pct_other": 5.0
    }
  },
  "presets": ["ercot_nogrr282", "spp_hill"],
  "scenarios": [
    { "id": "sag_75_600ms", "fault_start_s": 0.5, "fault_duration_s": 0.6, "fault_voltage_pu": 0.75 },
    { "id": "ride_85_600ms", "fault_start_s": 0.5, "fault_duration_s": 0.6, "fault_voltage_pu": 0.85 }
  ],
  "runner": "mock",
  "block": "it",
  "model": "perc1_dll"
}
```

| Key | Default | Meaning |
|---|---|---|
| `sweep_id` | `sweep` | Names the default output directory. |
| `base_case.facility` | app defaults | Every field optional. |
| `presets` | required | Ids from `presets list`. |
| `scenarios` | required | [Fault scenarios](#fault-scenario); a `scenario suite` file drops in unchanged. |
| `runner` | `mock` | `mock` or `psse`; `sweep --runner` overrides it. |
| `block` | `it` | `it` or `vfd`, the blocks presets apply to. |
| `model` | `perc1_dll` | The load model under test: it needs a `cons_for_preset` hook (see `models list`'s `ride_through_presets`) and, for the mock runner, a parser and simulator. |

A worked example is checked in at [`tests/fixtures/sweep_example.json`](../../../../tests/fixtures/sweep_example.json).
Check a spec without running it: `perc-studio sweep spec.json --dry-run`.

### Sweep output tree

`sweep` writes everything under `--output-dir` (default `output/<sweep_id>-<UTC timestamp>/`; `output/` is
gitignored):

```
<run dir>/
  cases/<case_id>.json                           one LoadCase per (preset, scenario) pair
  cases/<case_id>__<block>.dyr                   that case's exported .dyr record
  results/<case_id>__<block>__<scenario_id>.json the SimulationResult
  reports/<case_id>__<block>__<scenario_id>.html per-scenario report (plot + verdict)
  reports/summary.json                           the primary machine-readable artifact
  reports/summary.html                           the same data as a table
```

`reports/summary.json` is the one file to read for the whole run; `summary.html` is rendered from the same data,
never a second computation. `report sweep --output-dir DIR` re-prints it.
