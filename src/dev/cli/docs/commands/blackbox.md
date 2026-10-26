# PSS/E and black-box validation

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > PSS/E and black box

Black-box validation characterizes any load model from outside: its records run unchanged on a one-bus PSS/E rig, a
search finds its ride-through boundaries, and the result is compared with the presets you choose. Background:
[BLACK_BOX_VALIDATION.md](../../../../../docs/black_box/BLACK_BOX_VALIDATION.md). The commands here are the same work
as the app's Black-Box Validation tab, for scripts.

| Command | Needs PSS/E | Purpose |
|---|---|---|
| [`psse check`](#psse-check) | yes | Prove a PSS/E selection works |
| [`dll inspect`](#dll-inspect) | no | Check a model DLL before PSS/E loads it |
| [`blackbox`](#blackbox) | yes | Run the validation |
| [`results list/show/cases/plot`](#results) | no | Browse finished runs |

## `psse check`

Starts PSS/E with a selection and reports what it says: the exact version, the Python, and whether it initialized and
solved the test rig's power flow.

```bash
perc-studio psse check --psse-version 35.6
perc-studio psse check --psse-version 36.7 --psse-dir "D:/PTI/PSSE36/36.7" --python "C:/Python313/python.exe"
```

| Option | Default |
|---|---|
| `--psse-version` | required; 35.x and 36.x only (34 and earlier are 32-bit) |
| `--psse-dir` | the version's standard folder, e.g. `C:\Program Files\PTI\PSSE35\35.6` |
| `--python` | the interpreter the folder's `PSSPYxx` names, found with the `py` launcher |
| `--pspy` | the newest `PSSPYxx` folder |

Exit **4** when the selection does not work (wrong version in the folder, wrong Python, license refused);
`errors[0]` says which. All `blackbox` commands take the same four options.

## `dll inspect`

Reads one or more DLLs without loading them: architecture, exported symbols, imports, SHA-256, and which imports
cannot be found next to the DLL, in PSS/E's `PSSBIN` or on `PATH`.

```bash
perc-studio dll inspect PERC2_v35_v2p3.dll --psse-root "C:/Program Files/PTI/PSSE35/35.6" --model PERCBL
perc-studio dll inspect a.dll b.dll | jq -r '.data.dlls[] | "\(.path)\t\(.machine)\t\(.sha256)"'
```

`--model NAME` (repeatable) notes when the DLL does not export that model name. Exit **5** if any DLL has a problem
(not an x64 build - PSS/E 35 and later load only x64; unreadable; missing dependency); `data.dlls[].problems` says
what. `data.all_ok` is the summary.

## `blackbox`

```bash
perc-studio blackbox --psse-version 35.6 --dyr model.dyr --list
perc-studio blackbox --psse-version 35.6 --dyr model.dyr --dll model.dll --load 1 \
    --level standard --preset ercot_nogrr282 --preset pjm_lcl --out output/bbv
```

| Option | Meaning |
|---|---|
| `--dyr FILE` | The model's `.dyr` (required) |
| `--dll FILE` | The model's DLL; repeatable |
| `--list` | List the loads in the file and exit (no PSS/E needed) |
| `--load N` | Which load to test (1-based, from `--list`); required when the file has more than one |
| `--level quick\|standard\|full` | About 150, about 400, or 1500+ PSS/E runs (default `standard`) |
| `--preset ID` | A preset to compare with; repeatable |
| `--delt S` | Force the time step; otherwise the time-step check chooses |
| `--workers N` | Parallel PSS/E processes (default 4) |
| `--p-mw`, `--q-mvar` | The rig load (default 100 MW, 20 Mvar) |
| `--out DIR` | Required: gets `report.html`, `validation.json`, `bundle.zip` |
| `--include-dlls` | Put the DLLs in the bundle (default: hashes only) |

`bundle.zip` holds every case's job, trace and log, the worker, and a `rerun.py` that repeats them on any PSS/E
install. Exit **5** when the validation stopped before the end (for example PSS/E could not read the model);
`data.stopped` says why. `data.overall` maps each compared preset to its verdict (`meets`, `fails`, `at the edge`, ...).

```bash
perc-studio blackbox --psse-version 35.6 --dyr m.dyr --out out/bbv --preset ercot_nogrr282 | jq '.data.overall'
```

## `results`

Browse what `blackbox` (or the app) left on disk. None of these starts PSS/E.

```bash
perc-studio results list output/bbv_runs                 # every run under a root, newest first
perc-studio results show output/bbv_runs/20261012-140311 # one run's summary
perc-studio results cases output/bbv/bundle.zip          # its cases
perc-studio results plot output/bbv/bundle.zip --case 14ee1457ccdbecf92813e73a --channel V --out v.html
```

- `results list RUN_ROOT`: each run's title, date, level, case count, PSS/E version, DLLs, `overall` verdict, the
  verdict per compared preset and per event family, and `warnings`.
- `results show RUN_FOLDER`: the same plus `measured`, the "measured behaviour" table (for example
  `Undervoltage 0.3-0.4 pu | trips after | 0.273-0.289 s`).
- `results cases PATH`: PATH is a run folder, its `validation.json`, or a `bundle.zip`. Each case has a `key`, the
  test `group`, a `label` (the event), its `verdict` and the `event` window. `--group` filters by group title.
- `results plot PATH --case KEY ... --out FILE.html`: an interactive plot of the chosen cases' channels overlaid
  (`--channel` repeatable; default `V` and `P`; others recorded in the run, such as `F (Hz)`, are available). Zoom
  and hover come from the HTML; the event window is shaded.

To try these, run a Quick validation first (`perc-studio blackbox ... --out out/demo`) and point them at its run
folder.
