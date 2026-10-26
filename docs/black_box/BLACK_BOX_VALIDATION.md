# Black-box model validation

This document is for someone who has a PSS/E load model (a `.dyr` file, and a DLL if the model needs one) and
wants to know **how it behaves**: when it trips, when it rides through, whether and how fast it comes back, and
how that compares with the ride-through presets in this app. Sections 1 to 4 say what the tests are and how to
run them; section 5 says exactly what the code does, with function names so each statement can be checked;
sections 6 to 9 cover reading the results, PSS/E versions, the FAQ and troubleshooting.

It runs from the app's Black-Box Validation tab, or from the `perc-studio` automation CLI (installed from source).

Related document: [BINARY_SEARCH_LIMITS.md](BINARY_SEARCH_LIMITS.md) (what the boundary search cannot see). The
checklist, run log and findings from the first runs on real PSS/E are kept in the PSS/E validation library, which is
not published; what they found is summarized in this page.

---

## 1. What it is, and what it is not

**It is** a measurement of a model as a whole. The model is treated as unknown:

- **what the app controls:** the voltage and frequency at one bus, played back as a profile;
- **what it observes:** the bus voltage and frequency, and the load's active and reactive power (P, Q);
- **what it concludes:** whether the load tripped, when and how it reconnected, and where its ride-through
  boundaries lie. Everything is inferred from P after a disturbance.

The app runs your model, unchanged, on a one-bus test system in **your own PSS/E** and reports:

- where the model trips (the longest disturbance it rides through and the shortest it trips on, for each sag
  depth, swell level and held frequency);
- whether and when it reconnects, and how fast it ramps back;
- whether its behavior depends on the simulation time step or on how the study calls PSS/E;
- how those measured boundaries compare with each ride-through preset in the app.

**It is not**
- a parameter study. The model's CONs are never read, edited, swept or interpreted. A record runs as written;
  only the bus number is mapped to the rig. Only the *disturbance* moves.
- a compliance statement. Comparisons are worded "compared with the preset as encoded in this app", never
  "compliant". Only the ride-through requirement is checked; tripping where a preset allows it is never a failure.
- a network study. The test system is one bus; it tests the model, not model-network interaction.
- a replacement for PSS/E. Every number comes from a real PSS/E simulation. The app has a mock runner for its own
  tests, but this feature never uses it.

---

## 2. Before you start

| You need | Notes |
|---|---|
| PSS/E **35.x or 36.x**, 64-bit | The versions offered are 35.0 to 35.6 and 36.0 to 36.7. Checked on **35.6.4** and **36.7.1** (section 7). |
| A PSS/E license seat per worker | The default is 4 workers (4 simulations at once). If PSS/E refuses a seat, the app runs fewer at once and says so. |
| The Python that matches the install | Found automatically from the install's `PSSPYxx` folder (for example `PSSPY311` means Python 3.11). The tab shows which one it picked. |
| The model's `.dyr` | Any load model. For a composite model, the whole set of records for that load. |
| The model's DLL(s), if it is a user-written model | For example `PERC2_V35.dll` for the PERC1 DLL. It must be built for **your PSS/E version** (section 7). |
| This app | The installer or portable ZIP, or from source: `uv sync`, then `uv run perc-studio`. |

Nothing is uploaded anywhere. There are no tokens or online services.

---

## 3. Quick start

### In the app

1. Open the **Black-Box Validation** tab.
2. **1 · PSS/E install**: choose the version. The install folder fills in with the standard path; change it if
   yours is elsewhere (a folder that does not exist is marked red, with the reason). Press **Check install**: it
   starts PSS/E and reports `PSS/E 35.6.4 with Python 3.11.9: ready` or says what is wrong. The selection is
   remembered and re-checked next time.
3. **2 · Model**: **Browse...** to the `.dyr`. The first load in the file is picked under *Load to test*; change it
   only if the file holds several. Add the DLL(s) under *Model DLLs*. *Records as they will run* shows exactly
   what PSS/E will be given (the bus number is replaced with the rig's).
4. **3 · Tests**: choose a level (section 4.2; the list under it says what the level runs) and, under *Compare
   with*, the presets to compare against. *Run folder* is where runs go (each in its own date-and-time
   subfolder); it is remembered. *Advanced options* holds the time step, parallel runs and rig load.
5. **Run tests** (it says what is missing while it cannot run). The running page shows the stage, cases done
   against the level's estimate, elapsed time, any cases that did not complete, and the log. **Cancel** stops
   after the cases already running.
6. When it ends, the **summary** shows on the tab: the comparison with each standard, warnings, the
   **tolerance curve** (section 6.4), the measured behaviour, and the run folder with its files. **Open run tab**
   opens the run in a tab of its own with the **Test explorer** (section 6.2), the **Report** and each case's
   **PSS/E log**. **Previous runs** on the left reopen earlier runs; **Edit setup** and **Run again** start from
   the shown run's setup.

### From the command line

```powershell
# is PSS/E usable? (also tells you which Python and version it found)
uv run perc-studio psse check --psse-version 35.6 --pretty

# what loads does the file contain?
uv run perc-studio blackbox --psse-version 35.6 --dyr model.dyr --list

# run it
uv run perc-studio blackbox --psse-version 35.6 --dyr model.dyr --dll "C:\path\PERC2_V35.dll" `
    --level standard --preset ercot_nogrr282 --out out\my_run --pretty
```

Useful options: `--load N` (when the file has several loads), `--preset ID` (repeat for several),
`--workers N`, `--delt SECONDS` (force the time step), `--p-mw` / `--q-mvar` (the rig load), `--include-dlls`
(put the DLLs in the bundle instead of only their hashes), `--psse-dir`, `--python`, `--pspy` (when the install is
not in the standard place).

The exit code tells you what happened: **0** the validation ran to the end; **4** the PSS/E selection is
wrong (for example the folder holds another version); **5** the validation stopped early (the message says
why: model not read, DLL not loadable, does not initialize, and so on).

Everything the run produced is in `--out` (section 6.3).

---

## 4. What tests are performed

### 4.1 The stages

A validation is a fixed protocol of stages (`protocol.py`, `Validation.run`). Each stage gates the next: a model
that cannot sit still at nominal voltage stops at stage 1, because there is nothing meaningful to characterize.
Every automatic action (a retry, a halved time step) is logged under `diagnosis` and never changes a CON.

| # | Stage | What it does | Runs | Stops the run if |
|---|---|---|---|---|
| 0 | **Intake** | Reads the `.dyr`, picks the load, places it on the rig, inspects any DLL (section 5.1). No simulation. | 0 | the file has no load-model record, the chosen load does not exist, or a DLL is unreadable, not a Windows DLL, or built for the wrong machine type |
| 1 | **Initialization** | Three 10 s runs with **no disturbance**, at 1.00, 0.95 and 1.05 pu (section 5.5). | 3 | the model trips with no disturbance, drifts more than 10% (a warning above 1%), or PSS/E cannot read it (section 4.4) |
| 2 | **Time step** | Four reference events at the time step, half of it and a quarter; keeps the largest step that matches the next finer one (section 5.5). | 12 | never; a model whose result still changes at 1/960 s is flagged *time-step sensitive* and every result carries that warning |
| 3 | **Characterization** | The probe families of section 4.3, each searched for where the outcome changes (section 5.7). | most | never |
| 4 | **Robustness** | Repeats one boundary case in a fresh process; re-runs boundary points at half the step; re-runs one trip-and-reconnect case calling `run()` at every step (section 5.9). | a few | never; differences are flagged in the report |
| 5 | **Diagnosis** | When a case fails, a table maps what PSS/E said to an explanation and an automatic retry (rerun in a fresh process, halve the step). | as needed | the retries are used up |

Afterwards the measured boundaries are compared with each selected preset (section 5.8), and `validation.json`,
`report.html` and `bundle.zip` are written. The default time step is 1/240 s (a quarter cycle).

### 4.2 Test levels

`families.py` (`LEVELS`):

| | Quick | Standard | Full |
|---|---|---|---|
| Sag depths (pu) | 0, 0.5, 0.8 | 0 to 0.9, step 0.1 (10) | 0 to 0.9, step 0.05 (19) |
| Swell levels (pu) | 1.1, 1.2 | 1.05 to 1.30 (6) | 1.05 to 1.30 (9) |
| Held frequencies (Hz) | 58, 62 | 57 to 62 (10) | 57 to 62, step 0.25 (20) |
| Families | undervoltage, overvoltage, frequency | all six | all six, with 4 repeated-sag depths |
| Longest event, voltage / frequency | 10 s / 30 s | 20 s / 60 s | 30 s / 300 s |
| Duration tolerance | 10% | 5% | 2% |
| Interior checks | 3 | 4 | 8 |
| Runs, about | 150 | 400 | 1,500+ |

Every voltage or frequency at which a **selected preset's requirement changes** is added to the grid at any
level (`preset_breakpoints`), because that is where a model is most likely to fall short. This is why a Quick run
also tests 0.2 and 0.9 pu when ERCOT is selected. Fixed cost at every level: 3 initialization runs, 12 time-step
runs and a few robustness runs.

Measured on this project's machine with 4 workers: Quick (137 cases) **684 s**; Standard **1,924 s** (396 cases,
PERC1 DLL on 35.6) and **1,593 s** (374 cases, PERCxx1U on 36.7). A long case (a reconnection with a 60 s delay)
takes minutes by itself.

### 4.3 The probe families

Each family holds an **outer** value fixed and searches an **inner** axis for the point where the outcome changes
(`search.py`, `BoundarySearch`). On a log axis the midpoint is the geometric mean of the bracket ends; on a
linear axis it is the arithmetic mean.

| Family | Outer value (steps through a grid) | Inner value (searched) | Axis | "Good" means | What it shows |
|---|---|---|---|---|---|
| Undervoltage ride-through | sag depth | duration, 1/60 s to the level's maximum | log, relative tolerance | rode through | the measured low-voltage ride-through curve |
| Overvoltage ride-through | swell level | duration, 1/60 s to maximum | log | rode through | the high-voltage curve |
| Frequency ride-through | held frequency | duration, 0.1 s to maximum | log | rode through | the frequency curve |
| Reconnection window | one trip event | recovery voltage, 0.80 to 1.10 pu | linear, 0.005 pu | reconnected | whether and when the model comes back, and at which voltages it never does |
| Repeated sags | sag depth | gap between two sags, 0.02 to 5 s | log, 10% | rode through | how internal timers reset between events |
| Rate of change of frequency | final frequency | ramp rate, 0.1 to 10 Hz/s | log, 10% | rode through | ramp-driven trips |

"Rode through" includes momentary cessation (section 5.6). Initialization, the time step and the robustness
checks are fixed runs, not searches.

**Families built from earlier results.** The last three run at Standard and Full, and skip themselves with a
stated reason when the earlier results do not support them.

- **Reconnection** (`_recovery`). Takes the shallowest sag that tripped, at the shortest tripping duration (at
  least 0.05 s). Holds the bus at 1.00, 1.02, 0.97 and 1.04 pu to size the observation window (at most 120 s),
  then bisects the recovery voltage. Skipped if the load never tripped on a sag.
- **Repeated sags** (`_repeat`). Each sag lasts 60% of the longest single sag the load rode through at that
  depth; two sags are separated by a searched gap. 2 depths at Standard, 4 at Full.
- **Rate of change** (`_rocof`). Targets 59 and 61 Hz, only if the load rides through that frequency held for
  2 s or more. Ramps there, holds 1 s and ramps back.

### 4.4 Cases that stop the validation early

These are input problems, not model behavior, and the report says which:

| What happened | How the app knows | Exit |
|---|---|---|
| The model is not known to PSS/E (missing DLL, built for another version, wrong name) | PSS/E 35.6 does **not** reject it: it prints `RECORD IGNORED`, returns no error, and simulates the load with no model. The app recognizes that message. | 5 |
| The DLL cannot be loaded | `addmodellibrary` returns an error | 5 |
| The model does not initialize | PSS/E reports `INITIAL CONDITIONS SUSPECT`, or the load drifts at nominal | 5 |
| The PSS/E process crashes or hangs | a per-case timeout (at least 60 s, and 20 s per simulated second); the process is killed, with no error dialog | 5 |

---

## 5. How it works inside

This section follows `src/blackbox/` and `src/psse_worker/psse_worker.py`.

### 5.1 Reading a model we know nothing about

`intake.py`:

1. **Tokenize.** `_split_records` splits on `/` outside quotes after dropping `@!` and `//` comment lines.
2. **Classify** (`_classify`). The type comes from the record header only: a user model (`USRLOD`, `USRLODC`,
   `USRMDL`, ...) read by its `IC IT NI NC NS NV` header, a library load (a four-letter family such as
   `CLOD`, `CMLD`, `MAIN`, `PERC` plus `BL/OW/ZN/AR/AL`), a playback model, or other.
3. **Group** (`load_targets`). The unit under test is a load target: every load-model record that attaches to
   the same scope, number and load ID. A composite model such as `MAINBL10` + `PERCBL1U` runs together.
4. **Place** (`place_on_rig`). For a bus-scoped record the first field becomes `{BUS}`. For owner, zone or
   area scope the rig's load is put in that owner, zone or area. An ICON equal to the record's own bus
   becomes `{BUS}`; an ICON that matches another bus in the file is flagged and never changed.

DLLs are inspected by `dll_inspect.py` (machine type, exported model names, imported runtimes, SHA-256).

### 5.2 The PSS/E test case

Built for every case, from nothing, by `_build_rig` and `_prepare_dynamics`. No case file is used.

| Element | PSS/E call | Value |
|---|---|---|
| Case | `newcase_2` | 100 MVA base, 60 Hz |
| Bus 100001 "SRC" | `bus_data_4` | type 3 (swing), 138 kV, V = 1.0 pu, limits 0.9 to 1.1; area, zone, owner 1 |
| Load (ID of the target) | `load_data_6` | 100 MW + j20 Mvar (`--p-mw`, `--q-mvar`), converted to constant power with `conl(100, 0, 0, 100)` |
| Machine | `plant_data_4`, `machine_data_2` | at the bus: 100 MW, 20 Mvar, MBASE 10,000 MVA, ZSORCE 0.01 pu |
| Power flow | `fnsl` | full Newton solution before dynamics |
| Dynamics prep | `cong`, `conl`, `ordr`, `fact`, `tysl` | convert generators and loads, order, factor, flat solve |
| Source model | `dyre_new` on `case.dyr` | `PLBVF1` on the machine (file `pbvalid`), then the load's records |
| Solution | `set_netfrq(1)`, `dynamics_solution_param_2` | frequency dependence on; DELT 1/240 s; frequency filter 0.033333 s |

Four channels are recorded at every time step: **V** (`voltage_channel`, bus voltage, pu), **F**
(`bus_frequency_channel`, frequency deviation, pu of 60 Hz), **P** and **Q** (`load_array_channel`, the load's
power, per unit of the rig base), written to `case.outx` by `strt_2`. PSS/E also records two samples *before*
t = 0, so traces begin at a small negative time.

At the load bus PSS/E's voltage settles about 0.00002 pu below the commanded value (0.49998 pu for a "0.5 pu"
sag). That matters for thresholds exactly at a stage voltage (FAQ 7).

### 5.3 Applying a disturbance

`PLBVF1` plays a table of time, voltage and frequency into the machine, so the bus follows the profile exactly.

- A profile is a list of segments `(t_start, V_pu, f_Hz)`; each holds until the next. A segment marked
  `"ramp"` is reached along a straight line (used for rate-of-change tests).
- A step is written as two rows: the previous value at `t`, then the new value at `t + 1e-4 s`
  (`_profile_points`).
- `PLBVF1` multiplies the voltage it plays by per-unit frequency, so `_write_plb` writes `V / f_pu`.
- The event starts at t = 1.0 s (`EVENT_START`), so the model settles for a second first. The run then
  continues for at least 2 s after the event (the prompt window plus 1 s if that is longer; up to 120 s for
  reconnection).
- `psspy.run` is called only at the profile's breakpoints (`_run_times`). With `run_every_step` it is called
  every time step instead; stage 4 compares the two.

Example: a 0.5 pu sag lasting 0.45 s is `[(0, 1.0, 60), (1.0, 0.5, 60), (1.45, 1.0, 60)]`.

### 5.4 Running one case

`supervisor.py`. Every case is **one PSS/E process**, started fresh.

1. The app writes `job.json` (records, segments, step, DLLs, rig).
2. `psse_worker.py` is started with the install's own Python (`-I`). It builds the rig, adds the DLLs
   (`addmodellibrary`), reads the records (`dyre_new`), defines the channels, runs the simulation, reads
   `case.outx`, and writes `result.csv`, `meta.json` and `psse.log`.
3. The process runs in a Windows Job Object that kills its whole tree, with a timeout of
   `max(60 s, 20 s per simulated second)`, a 4 GB memory limit and crash dialogs suppressed.

Why a separate process per case: a crashing or hanging DLL then cannot take the app or other cases with it, and no
state can leak from one case into the next. PSS/E 36.7 keeps model memory across `psseinit`, and 35.6 aborts a
session after about 190 cases. PSS/E is never imported into the app itself.

**Cache.** A case's folder is named by a hash of the job, the DLL hashes, the PSS/E selection and the worker
and reader source (`Session.case_key`). A repeated case, a resumed run or a rebuilt report costs nothing for
cases already done. Several cases run in parallel (4 workers by default); a refused PSS/E license shrinks the
pool and is not cached.

### 5.5 Steady state and time step

**Stage 1** runs 10 s with no disturbance at 1.00, 0.95 and 1.05 pu. It stops the run if P falls below half
its starting value or drifts more than 10%, and warns above 1%.

**Stage 2** runs four reference events at 1/240, 1/480 and 1/960 s (12 runs):

| Reference event | Why |
|---|---|
| 0.9 pu for 0.05 s | mild; certainly rides through; sets the settling time |
| 0.5 pu for 0.1 s | a deep, short sag |
| 1.15 pu for 0.5 s | a swell |
| 58.5 Hz for 5 s | a frequency excursion |

A step passes if, on every reference event, P matches the next finer step within 2% RMS (`traces_match`) and
the outcome class agrees. The largest passing step is used. If none passes, the finest is used and every
result is flagged time-step sensitive.

The same stage measures the model's own settling time on the mild event. The classifier's **prompt window**
is `max(0.15 s, 2 x settle + 0.05 s)`.

### 5.6 Deciding what happened

`classify.py`. Only P and Q are used, because every load model has them. P is divided by its mean over the
0.2 s before the event, and the run is classified from what happens **after the disturbance ends**.

| Class | Rule |
|---|---|
| rode through | P is back to 90% within the prompt window after the bus returns to normal, and stays there to the end of the run |
| momentary cessation | P fell below 10% while V was still 0.5 pu or more, then recovered promptly |
| tripped, reconnected | P is below 90% after the window and later climbs back; the delay and ramp are reported (the ramp is the time to within 2% of the final value) |
| tripped, partly reconnected | P settles between 10% and 90% of its pre-event value |
| tripped, did not reconnect | P never comes back within the observation window |
| unstable | at least four reversals in the second half of the run that are not dying out |
| numerical failure | P is NaN or infinite, no power before the event, or the run failed (PSS/E error, timeout) |

"Back" for reconnection means at least 25% of pre-event power. In the searches, "good" means rode through
(or momentary cessation).

This needs no model of the load during the event, so a current-limited or constant-impedance load that draws
little power in a deep sag is still classified correctly. A load that trips the instant the voltage recovers
shows full power for an instant first, so ride-through needs P to be back **and stay** there.

### 5.7 Finding a boundary

The phases of one search:

1. **Ends.** Run both ends of the axis.
2. **Uniform check.** If the ends agree, run interior points (`interior_checks`, evenly spaced). A
   disagreement means the outcome flips somewhere.
3. **Bisect.** Halve every open bracket until its ends are within the tolerance.
4. **Region check.** Run points inside each settled region. A second flip marks the axis **non-monotonic**.
5. **Dense scan.** For a non-monotonic axis, run 12 points across the axis, then bisect every flip.

A search stops at 60 points. Many searches advance in lockstep: each round is one batch of runs sent to the
workers together (`run_searches`). The result for each outer value is a **bracket**: the longest duration seen
riding through and the shortest seen tripping.

**A worked example.** The real `BoundarySearch` on a synthetic model that rides through a 0.5 pu sag up to
0.45 s and trips beyond it (Standard level: axis 1/60 s to 20 s, tolerance 5%, four interior checks):

| Round | Runs | Durations tried (s) |
|---|---|---|
| 1 | 2 | 0.0167 (rides through), 20 (trips) |
| 2 to 9 | 8 | 0.577, 0.098, 0.238, 0.371, 0.463, 0.414, 0.438, 0.450 |
| 10 | 8 | 0.032, 0.062, 0.120, 0.233, 0.983, 2.09, 4.43, 9.42 |

18 runs. Longest ride-through 0.450 s, shortest trip 0.463 s, monotonic.

**What it can miss.** If both ends of an axis agree and a trip window falls between the interior checks, the
window is missed. With the same engine, a model that trips only for sags lasting between 0.3 s and 1.0 s is
reported as riding through everything: the ends ride through, and the four interior checks fall at 0.069, 0.284,
1.173 and 4.844 s. A denser level (8 interior checks at Full) narrows the gap. The report's Method section states
the limit.

**What a one-bit outcome cannot see.** The search asks only "rode through or not". Models with several cease levels
(a momentary cease that escalates to a long one with a slower reconnect), cycling during a long event, a cease during the
reconnect ramp, a permanent cease, or logic that depends on voltage and frequency together (PERC2 has all of these) are
only partly characterized. [BINARY_SEARCH_LIMITS.md](BINARY_SEARCH_LIMITS.md) works through each with a PERC2 run in
PSS/E and proposes the changes.

### 5.8 Comparing with a preset

At each outer value the preset requires the load to ride through up to some duration (possibly forever).
`scoring.py` reads that duration and gives a verdict from the bracket:

| Verdict | Meaning |
|---|---|
| **meets** | the load was seen riding through at least the required duration |
| **fails** | the load was seen tripping on a disturbance shorter than required |
| **at the edge** | the requirement falls inside the bracket, so the answer is within the search resolution |
| **not solvable** | a case at this value failed to solve in PSS/E (an exact 0 pu bus gives "Network not converged" and NaN); the search reads a failure as a trip, so the row has no boundary and is not scored |
| **beyond tested range** | the requirement is longer than the longest disturbance run, and the load rode through everything |
| **no requirement** | the preset has no ride-through requirement there (it allows tripping) |

Only the ride-through requirement is checked; tripping where a preset permits it is never a failure. The
wording is "compared with the preset as encoded in this app", never "compliant".

### 5.9 Is the answer itself trustworthy

Stage 4 (`_robustness`):

- **Repeatability.** The first boundary case runs again in a fresh process; traces must match within 0.01%
  RMS.
- **Half time step.** Up to six boundary transitions, both sides, are rerun at half the step; the outcome
  class must be unchanged.
- **`run()` cadence.** One trip-and-reconnect case is run with `run()` every step instead of event to event.
  A difference is flagged. Measured: the PERC1 DLL on PSS/E 35.6.4 fails (ramp 14.4 s against 28.8 s);
  PERCxx1U on 36.7.1 meets it.

### 5.10 What it cannot see

- **One operating point per run.** 100 MW / 20 Mvar on one bus unless changed; a different load level needs
  a different run.
- **Only P and Q judge the model.** Internal states are not used, so the cause of a trip is not reported.
- **One disturbance at a time.** Voltage or frequency, not both together; no phase jumps.
- **Narrow windows can be missed** (section 5.7).
- **0 pu is unreliable.** An exact 0 pu bus gives non-convergence or NaN; those rows are failures, not
  trips (FAQ 8).
- **Strict thresholds.** A sag at exactly a stage voltage is decided by about 1e-5 pu; read depths away from
  it (FAQ 7).
- **`.outx` channel files only** in the app's own reader. Anything else goes through `dyntools` (section 7.3).
- **A user DLL is native code.** Each case runs in its own process under Windows Job Object limits, but the app
  cannot fully sandbox a DLL; every report records its hash.
- **Not compliance evidence.** The comparison is with the preset as encoded in the app. Check each preset's
  source before relying on a verdict.

---

## 6. Reading the results

### 6.1 The report

`report.html` (plotly is embedded, so it opens offline). Sections: **Summary**, **Environment** (PSS/E version,
Python, time step, license and worker notes), **The model** (the records, any DLL hash), **Time step**,
**Characterization** (one figure per family, with a table of the brackets), **Comparison with presets**,
**Robustness of the results**, **Method**, and a **Diagnosis** list when something was retried. A stopped
validation still writes a report: it says where it stopped and shows the PSS/E log's key lines.

`validation.json` holds the setup, the environment, one entry per stage, one entry per family (each search's
points as `[x, good]`, its transitions and whether it was monotonic), the comparison with each preset, the
diagnosis log, and one record per case (`points`) with its classified outcome.

### 6.2 The results explorer

The **Test explorer** of a run's tab lets you look at the actual simulated traces:

- the left list has every case, **grouped by benchmark test** (undervoltage, overvoltage, frequency, ...) with
  its verdict; type in the filter to narrow it (`tripped`, `0.5 pu`);
- **tick one or more tests** and they are overlaid on one plot, one colour per test, with the disturbance window
  shaded (for the first ticked test);
- **tick the channels** to show; each gets its own panel on a shared time axis. V and P are shown first; every
  channel PSS/E recorded is offered;
- drag to zoom, double-click to reset, hover for values, click a legend entry to hide a test;
- **Source files for the ticked cases** gives the full path of each ticked case's `case.outx`, with **Copy path**
  and **Show in folder**.

**Open results...** (under *Previous runs*) loads a previous run: a run folder, its `validation.json`, or a
`bundle.zip` that came from another machine. **No PSS/E is needed to explore results.**

### 6.3 What is saved

```
<run folder>/
  report.html          the report (plotly embedded)
  validation.json      everything, machine-readable
  bundle.zip           a self-contained record
  work/cache/<case key>/
    job.json           what was run
    case.dyr           the records as PSS/E read them
    pbvalid.plb        the played-back profile
    psse.log           PSS/E's own output
    case.outx          every recorded channel
    result.csv         time, V, F_HZ, P, Q
    meta.json          status, version, model name, CON read-back, sampling
```

- **`result.csv` is compressed.** A row is kept only when a channel moves by more than 1e-6, plus the row
  before it, so flat stretches cost two rows and interpolation reproduces the full-rate data.
- **Checks on every case.** `meta.json` records `model_name`, the CONs PSS/E read back (`con_readback`), the
  sampling mode and the number of `run()` calls.
- **Failures become findings.** `logparse.py` maps log patterns to causes, for example `RECORD IGNORED` for a
  model PSS/E does not know.

**The bundle.** `bundle.zip` holds `validation.json`, `report.html`, the `.dyr`, the worker and its reader,
every case's `job.json`, `meta.json`, `result.csv`, `psse.log` and `case.outx`, and `rerun.py`. Send it to
someone to look at (they can open it in the explorer), or run `rerun.py` with a PSS/E Python to re-run every
case and compare with the stored results. DLLs are not included unless you pass `--include-dlls` (their hashes
are).

### 6.4 The tolerance curve

The summary's tolerance curve (`tolerance.py`) shows how long the model rides through each voltage and frequency,
drawn from the measured boundaries. It is stepped, never interpolated: a band runs from one tested value to the
next and uses the boundary measured at its end farther from nominal (for undervoltage, its lower voltage).

**Overlay standard** lays a standard over it: its requirement as a dashed line, and in red hatching every band
where it requires ride-through and the model was seen to trip, with a sentence listing them. No re-run is needed:
the standard is a curve and the model's curve is measured. It starts with no standard, the choice is not saved,
and a standard without a frequency table says so instead of drawing one. The written report always has the plain
curve.

---

## 7. Different PSS/E versions

### 7.1 What changes with the version

| | PSS/E 35.x | PSS/E 36.x |
|---|---|---|
| Python | the install's `PSSPYxx` folder; the 35.6 install here has several and the app uses **3.11** | likewise; the 36.7 install here has `PSSPY313` and `PSSPY314` and the app picked **3.14** |
| User-written DLL models (the PERC1 DLL) | load with `addmodellibrary`; the DLL must be built for 35 | a DLL built for 35 **does not load** in 36 (the app stops with `dll_error`) |
| Built-in PERC model (`PERCxx1U`, 30 CONs, with a `MAINxx10` record) | not available | PSS/E 36.7 only |
| Unknown model name | `RECORD IGNORED`, return code 0 (section 4.4) | not observed yet |
| Channel file layout | identifiers at byte 3008, long header | identifiers at byte 20, short header |

### 7.2 What has been verified, and what has not

| | Verified | Not verified |
|---|---|---|
| PSS/E 35.6.4 (Python 3.11.9) | the check; a 137-case Quick and a 396-case Standard validation of the PERC1 DLL; the missing-model and DLL-error stops; the app's regression test against the real DLL | the license-refusal path |
| PSS/E 36.7.1 (Python 3.14.6) | the check (and the wrong-folder message); a 374-case Standard validation of the built-in `PERCBL1U` model; the channel reader against its files | the license-refusal path; Python 3.13 |
| Any other 35.x or 36.x | nothing | everything; see below |

If you are on another version, run `perc-studio psse check` first, then a Quick validation of a model whose
behavior you know. If the channel file does not read, the worker falls back to PSS/E's `dyntools` and says so in
`meta.json` (`sampling_reader`); send one `case.outx` so the reader can be taught the layout.

### 7.3 The two ways of reading results

The worker reads each case's channel file with the app's own reader (`src/blackbox/outx.py`). It needs nothing
but the file and was verified equal to PSS/E's `dyntools` on 35.6 and 36.7 files. If it does not recognize a
file it refuses rather than guessing, and the worker falls back to `dyntools`, which needs PSS/E's DLLs on the
path, reports an unrelated `NameError` when anything is missing, and cannot read a file containing NaN or
infinity (which PSS/E writes for an unsolvable 0 pu bus). If neither can read the file, the trace is built from
one point per `run()` call and the report says the data is coarse.

---

## 8. FAQ

**1. Does it change my model?** No. The records run exactly as written. Nothing edits, sweeps or interprets a
CON. What moves is the disturbance.

**2. Which models can it test?** Any load model PSS/E can attach to a load: user-written (`USRLOD`, `USRLODC`) with
a DLL, built-in library loads (`CLOD`, `CMLD`, ...), and composite models such as `PERCxx1U` (a `MAINxx10` record
plus its component). The unit under test is "the load": every record that attaches to the same load is run
together. Records that are not load models are reported and left out.

**3. What does "tripped" mean for a model that has no trip flag?** Only P is used. A load "tripped" if its power
did not come back to 90% of its pre-event value within the prompt window after the bus returned to normal
(section 5.6). That works for any model.

**4. How long does it take?** Quick about 11 minutes, Standard about 32 minutes, on 4 workers (measured here). More
workers is faster if your licenses allow (`--workers 8`). Cancelling keeps what finished, and a re-run reuses it.

**5. Why a single bus?** Because the question is "what does the model do given this voltage and frequency", not
"what does the network do". A one-bus rig with the disturbance played back exactly isolates the model.

**6. Does it need internet, or send my model anywhere?** No. Everything runs on your machine, and the report is a
local file.

**7. A model should trip at 0.25 s but the report says 0.45 s. Is that wrong?** Often not. A threshold exactly at
the test voltage is a knife edge: the rig holds a "0.5 pu" sag at 0.49998 pu, and a model's voltage filter then
needs about `T x ln(0.5/0.00002)` (about 10 time constants) to cross it. For a 0.02 s filter that is 0.2 s extra,
which is what is measured (0.25 s stage reads 0.45 s). The same applies at 0.2, 0.8 and 0.9 pu for the PERC1 record
in the checklist. Look at a depth that is *not* a stage voltage to read the stage time.

**8. 0 pu gives odd results.** An exact 0 pu bus is unsolvable for many models (PSS/E reports `Network not
converged`, or the model returns NaN). Those cases are recorded as numerical failures, not trips, and boundary
rows at 0 pu mix failures with real outcomes and should not be read as a measurement. (In the first Quick run a
0 pu boundary of 0.03 s disagreed with the Standard run's 0.18 s; the cause was not established.)

**9. Can it tell me my model is compliant?** No, by design. It reports measured behavior and compares it with a
preset *as encoded in this app*; only the ride-through requirement is checked.

**10. Why does it stop with "PSS/E could not read the model" when PSS/E returned no error?** Because PSS/E 35.6
silently ignores a model it does not know. The app reads PSS/E's own message (`RECORD IGNORED`) and stops, rather
than run hundreds of cases on a load with no model. Check the DLL's version, its path, and the model name.

**11. Can I look at the results on a machine without PSS/E?** Yes. Copy the run folder (or unpack `bundle.zip`)
and use **Open results...** on the Black-Box Validation tab. The explorer and the report need only this app.

**12. What do I do with a bundle from someone else?** Open it in the explorer to see their cases, or run its
`rerun.py` with a PSS/E Python to re-run everything and diff against their stored results.

**13. Can I use my own DELT?** Yes: `--delt`, or the time step is chosen for you in stage 2 (1/240 s, refined to
1/480 or 1/960 s if results depend on it). A forced step is honored, and its convergence is still reported.

**14. What if my model gives a different answer when `run()` is called every step?** The robustness stage tests
exactly that and flags it. The PERC1 DLL does this (its ramp is twice as fast when `run()` is called every step),
so a study script's calling pattern changes the model's behavior. The built-in `PERCxx1U` ramps in simulated time
and does not (checked on 36.7: identical results either way).

**15. Where is everything saved?** In `--out` (or the tab's run folder); see section 6.3. `out/` is ignored by git.

**16. Is it in the installed app?** Yes: the Black-Box Validation tab ships in the installer and the portable ZIP.
The `perc-studio` commands come with a source install.

**17. How do I check a new PSS/E version?** Run `perc-studio psse check`, then a Quick validation of a model whose
behavior you know (section 7.2). The step that catches a layout change is reading a `case.outx`; if the reader refuses
a file, open an issue with the file attached so the reader can be extended (and the file added to
`tests/fixtures/outx/`).

---

## 9. When something goes wrong

| What you see | Most likely cause | What to do |
|---|---|---|
| **Check** shows red: "this folder holds PSS/E 35.6.x, not 36.7" | the version box and the folder disagree | choose the matching folder, or the matching version |
| **Check** fails at start-up | no license seat, or the Python interface does not match | start PSS/E once by hand; pick another `PSSPYxx` |
| The run stops: "PSS/E could not read the model" | the model is unknown to PSS/E, or the DLL is for another version | see FAQ 10; check the DLL, the name, the PSS/E version |
| The run stops with `dll_error` | the DLL cannot be loaded | it must be 64-bit and built for this PSS/E version; its runtime DLLs (for example the Intel Fortran runtime) must be findable; the report lists what the DLL imports |
| The run stops: "does not initialize" | PSS/E reports initial conditions suspect, or the load drifts at nominal | the report lists the states PSS/E named; the model cannot be characterized until it sits still |
| Traces have very few points, `sampling` is `run_calls` | the channel file could not be read | check that PSS/E recorded channels (`case.outx` should be tens of kB, not 148 bytes); send one file |
| `sampling_reader` is `dyntools` on a real run | the internal reader does not know this PSS/E layout | send one `case.outx`; results are still correct, via PSS/E's own reader |
| Many "numerical failure" cases at 0 pu | an exact 0 pu bus is unsolvable | expected (FAQ 8) |
| `PermissionError ... Access is denied` in the log | antivirus or an indexer held a file | the app retries; if it persists, exclude the output folder from scanning |
| A run takes much longer than the table in 4.2 | long reconnection cases (60 s delays), or fewer licenses than workers | check the log for "PSS/E refused a license; now running N at a time" |
| A DLL error dialog appears | should not happen | the app suppresses crash dialogs and kills a hung process; report it with the bundle |

---

## 10. For developers

| Where | What |
|---|---|
| `src/blackbox/protocol.py` | the stages |
| `src/blackbox/intake.py`, `dll_inspect.py` | reading the `.dyr`, placing it on the rig; DLL inspection |
| `src/blackbox/families.py` | the probe families and the level grids (data) |
| `src/blackbox/search.py` | the boundary search |
| `src/blackbox/classify.py`, `scoring.py` | the classifier; the preset comparison |
| `src/blackbox/tolerance.py` | the tolerance curve |
| `src/blackbox/supervisor.py` | one PSS/E process per case, timeouts, cache, license back-off |
| `src/psse_worker/psse_worker.py` | the script that runs inside PSS/E's Python (stdlib only) |
| `src/blackbox/outx.py`, `explorer.py` | the channel-file reader; the results listing and plot figure |
| `src/blackbox/report.py`, `runs.py` | the HTML report, JSON and bundle; previous runs |
| `src/ui/blackbox/tab.py`, `ui/blackbox/runs.py`, `ui/blackbox/explorer.py` | the tab, the run summary and run tabs, the explorer |
| `tests/fixtures/fake_psse/` | a fake `psspy` the tests run against (no PSS/E needed) |

How it is tested: the logic is tested against the fake PSS/E (`tests/test_blackbox_*.py`, `tests/test_ui_blackbox.py`),
which models the behaviors real PSS/E was seen to have (an unknown model returning no error, zero monitored channels
producing an empty file, a hanging or crashing model). The channel reader is tested against real files from PSS/E
35.6 and 36.7 with `dyntools`' own numbers as the expected values, plus corrupted and truncated files. What needs real
PSS/E is recorded as a checklist and a run log (kept with the unpublished PSS/E validation library), not as tests
that skip silently. Every defect found that way has a regression test.

To add a probe family, add it to `families.py` (the outer and inner axes and the event builder) and to the
level tuples; the search, classifier, report and explorer need no change.
