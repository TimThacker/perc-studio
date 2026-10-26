# Runners

[perc-studio](../README.md) > Runners

`run` and `sweep` execute a `.dyr` record against a fault scenario through a runner. There are two, behind one
interface.

```python
class PsseRunner(Protocol):
    def run(self, raw_case_path, dyr_text, scenario, *, block_name, case_id) -> SimulationResult: ...
```

`get_runner(name)` (`src/psse/runner.py`) is the single factory every command and sweep goes through. Every command,
`dev/validation/sweep.py` and `dev/validation/checks.py` depend only on the protocol, so a third runner would work
with all of them.

| `--runner` | What it is | Needs |
|---|---|---|
| `mock` (default) | An analytic stand-in: the load model's own `simulate` hook | nothing |
| `psse` | `blackbox.runner.PsseSubprocessRunner`: each case in its own PSS/E process on the black-box one-bus rig | a PSS/E selection |

## Selecting PSS/E

`--runner psse` reads the selection from the environment:

| Variable | Meaning |
|---|---|
| `PERC_STUDIO_PSSE_VERSION` | e.g. `35.6` or `36.7`. Required. |
| `PERC_STUDIO_PSSE_DIR` | Install folder, when not the version's standard path |
| `PERC_STUDIO_PSSE_PYTHON` | The Python that runs `psspy`, when not found from `PSSPYxx` |
| `PERC_STUDIO_PSSE_PSPY` | The `PSSPYxx` folder, when not the newest |
| `PERC_STUDIO_PSSE_DLLS` | The model's DLL(s), separated by `;` |

or the selection saved by the app's Black-Box Validation tab. With no selection the runner raises
`NotImplementedError` and the command exits **4**. `perc-studio info` shows which of these variables are set;
`perc-studio psse check` proves a selection works (see [PSS/E and black box](commands/blackbox.md)).

```bash
export PERC_STUDIO_PSSE_VERSION=35.6
export PERC_STUDIO_PSSE_DLLS="C:/models/PERC2_v35_v2p3.dll"
perc-studio run case.json --fault-duration-s 1.0 --fault-voltage-pu 0.5 --runner psse --out psse_result.json
```

## What `MockPsseRunner` computes

It is **not** a PSS/E simulation. It finds which registered load model wrote the record
(`load_models.find_model_for_dyr`, by the quoted model name in the `.dyr` text), parses the text back into a CON dict
with that model's own parser - so it always runs on the *exact* artifact a real run would consume - and runs that
model's analytic `simulate` hook (`simulate_frequency` for a frequency event). For PERC1 that is
`load_models.perc1_dll.simulation.simulate_perc1_response`, the same simplified approximation the desktop app's live
chart uses.

- It honors `fault_duration_s` and `fault_voltage_pu`/`fault_frequency_hz`. It **ignores** `fault_start_s` (analytic
  simulators start the event at 0.5 s) and adds a warning to the result when another value was requested.
- It evaluates **all four Option-3 stages per direction** (`VDPA`/`DMA` + `VDPA1-3`/`DMA1-3`, `VDUA`/`TDUA` +
  `VDUA1-3`/`TDUA1-3`) like the real DLL: every stage whose own threshold the event crosses counts down from the same
  onset, and the shortest dwell that completes within the event trips. See [Background](background.md).
- It needs the block's model to have both a parser and a simulator (`models list`'s `mock_run`); a CLOD `motor`
  block exits **2**. A frequency scenario also needs `frequency_mock_run`.

A mock pass is not a substitute for a PSS/E run: no network solve, no generator dynamics. Use it to check your
parameterization logic and the envelope bookkeeping, then confirm with `--runner psse` or `blackbox`.
