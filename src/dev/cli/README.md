# perc-studio

`perc-studio <command>` is the automation CLI for PERC Studio. The same `perc-studio` command with no arguments
opens the desktop app; with a command (`params`, `export`, `sweep`, `blackbox`, ...) it does everything the GUI does -
build a parameterization, export a `.dyr`, import one, generate a report - from a script, plus things the GUI cannot do:

- **Generate many parameterizations programmatically** - from a preset, from a model's default CONs, from an
  existing `.dyr`, or by layering explicit CON overrides onto any of them.
- **Close the loop**: run a parameterization against a fault scenario (a built-in analytic mock, or real PSS/E),
  compare what happened with what the selected ride-through preset's own envelope says *should* have happened, and
  get a pass/fail verdict with a plot.
- **Characterize any load model as a black box** in PSS/E and browse the results afterwards.

Every command prints one JSON object to stdout and uses a fixed set of exit codes
([output contract](docs/output_contract.md)). `perc-studio` is written to be driven by a script or an agent at least as
easily as by a person typing commands.

## Quick start

```bash
uv sync                                   # or: pip install -e .
uv run perc-studio --help                   # the command tree
uv run perc-studio info --pretty            # version, models, presets, PSS/E environment

# generate -> export -> run -> validate -> report, for one preset and one fault
perc-studio params generate --source preset --preset-id ercot_nogrr282 --out case.json
perc-studio export dyr case.json --block it --out it.dyr
perc-studio run case.json --fault-duration-s 2.0 --fault-voltage-pu 0.75 --out result.json
perc-studio validate results --case case.json --result result.json
perc-studio report case --case case.json --result result.json --out report.html
```

More recipes, one per task, are in the [cookbook](docs/cookbook.md); the same loop as a single narrated run is the
[walkthrough](docs/walkthrough.md).

## Command map

Each group links to its reference page. Every command also takes `--pretty` (indent the JSON) and `--help`.

```
perc-studio
├── info                          version, registered models, preset count, PSS/E environment
├── models      list | show       the registered load models           -> commands/models.md
├── presets     list | show       the ride-through presets             -> commands/presets.md
├── params      generate | validate | show | diff                      -> commands/params.md
├── dyr         list | show | to-case     read an existing .dyr        -> commands/dyr.md
├── export      dyr | facility | report                                -> commands/export.md
├── scenario    make | suite      build fault scenario files           -> commands/scenario.md
├── run                           one case, one scenario, one runner   -> commands/run_validate_report.md
├── validate    results           expected vs actual behavior          -> commands/run_validate_report.md
├── report      case | sweep      HTML reports                         -> commands/run_validate_report.md
├── sweep                         presets x scenarios, end to end      -> commands/sweep.md
├── psse        check             does this PSS/E selection work       -> commands/blackbox.md
├── blackbox                      black-box validation in PSS/E        -> commands/blackbox.md
├── results     list | show | cases | plot    browse black-box runs    -> commands/blackbox.md
└── dll         inspect           check a model DLL                    -> commands/blackbox.md
```

| Task | Command |
|---|---|
| See what models/presets exist | `models list`, `presets list` |
| Build a case | `params generate` (`--source preset\|defaults\|overrides`), `dyr to-case` |
| Compare two cases | `params diff` |
| Get PSS/E text | `export dyr` (bare records), `export facility` (the app's full file) |
| Get the app's HTML report | `export report` |
| Define a fault | `scenario make`, `scenario suite` |
| Simulate and judge | `run`, `validate results`, `report case` |
| Do that for many presets and faults | `sweep` (`--dry-run` to check the spec first) |
| Test a model in real PSS/E | `psse check`, `dll inspect`, `blackbox` |
| Look at a finished black-box run | `results list`, `results show`, `results cases`, `results plot` |

## Documentation

| Page | Contents |
|---|---|
| [Output contract](docs/output_contract.md) | The JSON envelope, exit codes, Click-level errors, scripting patterns |
| [Cookbook](docs/cookbook.md) | Worked examples for every command group |
| [Walkthrough](docs/walkthrough.md) | One case from generation to a plotted verdict, then a sweep |
| [File formats](docs/formats.md) | `LoadCase`, fault scenario, `SimulationResult`, sweep spec, sweep output tree |
| [Runners](docs/runners.md) | The `PsseRunner` contract, the mock runner, selecting real PSS/E |
| [Background](docs/background.md) | Option 3's multi-stage trip table and what the validation tests settled |
| [models](docs/commands/models.md), [presets](docs/commands/presets.md), [params](docs/commands/params.md), [dyr](docs/commands/dyr.md), [export](docs/commands/export.md), [scenario](docs/commands/scenario.md), [run / validate / report](docs/commands/run_validate_report.md), [sweep](docs/commands/sweep.md), [PSS/E and black box](docs/commands/blackbox.md) | Per-command reference |

## Installation / invocation

The CLI comes with a source install (`uv sync` or `pip install -e .`); the Windows installer has the desktop app
only. There is one console entry point, `perc-studio` (`app.launcher:main`): when its first argument is a command
rather than an option, it hands the arguments to `dev.cli.main:main`. The CLI shares the engine with the GUI
(`src/load_models/`, `src/presets/ridethrough.py`, `src/export/dyr.py`) but never starts Qt, so it works headless
(CI, a container, an agent sandbox). `perc-studio help` lists the commands.

Without installing the entry point: `python -m dev.cli.main --help` from `src/`.

Every command is also a plain Python call - `dev/validation/case_model.py`, `psse/runner.py`,
`dev/validation/checks.py`, `dev/validation/sweep.py`, `editor/dyr_import.py` and `blackbox/*` are Click-independent
modules the CLI is built on. The CLI is one consumer of that library, not the only way in.

## Load models

Every case block names its load model (`model_id`). `perc1_dll` is the default for the `it`/`vfd` blocks and `clod`
for `motor`; every command dispatches through the block's model, so a newly registered model works with all of them
(see [ADDING_A_LOAD_MODEL.md](../../../docs/developer/ADDING_A_LOAD_MODEL.md)). Five are registered:

| `model_id` | CONs | Record | Notes |
|---|---|---|---|
| `perc1_dll` | 173 | `PERCBL` (+`OW`/`ZN`/`AR`/`AL`) | PERC1 DLL, PSS/E 34/35; the default |
| `perc2_dll` | 181 | `PERCBL` | PERC2 DLL v2.3 (179-CON record header) |
| `perc1_standard` | 30 | `PERCBL1U` | PSS/E 36.7 built-in; a `MAINxx10` + `USRLODC` pair |
| `perc2_standard` | 63 | `PERCBL2U` | PSS/E 36.7 built-in PERC2 |
| `clod` | 5 | `CLODBL` | Composite load; the motor block; no mock simulation |

Pass `--model` to `params generate` and `"model"` in a sweep spec to work with a model other than the default. The
standard models have no overvoltage, frequency or multi-stage trips, so a preset's overvoltage and frequency
scenarios are reported as "Not modelled" by `validate`, not as failures. See [models](docs/commands/models.md).
