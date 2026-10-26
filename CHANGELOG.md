# Changelog

Versions follow [Semantic Versioning](https://semver.org). The **User-facing**
section of each release is its release note for the production edition;
**Developer** lists changes that only affect the development edition and the
build.

## 1.2.1 - 2026-10-26

### User-facing

- **Voltage card: timer bars.** On the live preview's Voltage at the load bus card (and the saved report, which shares
  it), each voltage trip or cease point is now a short red bar at its level, starting with the event and as long as
  its delay, in place of a dashed line across the whole plot. The point that tripped or ceased the load is solid, the
  points the event reaches are half strength and the rest faint; hover a bar for its CONs, delay and what it did in
  this event. The legend reads "Trip thresholds", and the green dashed reconnect line is unchanged.
- **PERC1 DLL and PERC2 DLL: every trip stage on the voltage card.** All 4 stages per direction (`VDPA`-`VDPA3`,
  `VDUA`-`VDUA3`) are drawn, each as long as its delay plus `CMTDELAY`; before, only stage 1 (`VDPA`, `VDUA`) was.
  The PERC2 DLL also shows `VLBLK`/`VUBLK` when momentary cessation is on. Repeated stages (presets pad the tables)
  appear once.
- Qt for Python (PySide6) 6.12. The only visible change is slightly less left padding on the text in numeric fields.

### Developer

- `preview.page.voltage_cease_points()` lists the drawn points for PERC2, the PERC1 DLL and the PERC2 DLL, matched to
  the simulator's `trip_events`.
- Tooling updates: ruff 0.17.2, `actions/checkout` 7, `astral-sh/setup-uv` 7.

## 1.2.0 - 2026-10-26 (open-source release)

### Open-source release

- PERC Studio is now open source under the MIT License, at <https://github.com/TimThacker/perc-studio>. Questions and
  bug reports go to GitHub Issues; the About page, the documentation and the ZIP's README point there.
- One command, `perc-studio`, replaces both `perc1-param-app` (the desktop app) and `perc1-dev` (the CLI):
  `perc-studio` opens the app, `perc-studio <command>` runs the automation CLI and `perc-studio help` lists the
  commands. The distribution is renamed `perc-studio` too.
- The app-wide environment variables are renamed `PERC_STUDIO_*`: `PERC_STUDIO_PSSE_VERSION`, `_PSSE_DIR`,
  `_PSSE_PYTHON`, `_PSSE_PSPY`, `_PSSE_DLLS` (the PSS/E selection) and `PERC_STUDIO_SIGN_ARGS`, `PERC_STUDIO_SIGNTOOL`
  (code signing).
- The settings folders are now `%LOCALAPPDATA%\perc-studio` and `%APPDATA%\perc-studio`. An existing
  `perc1-param-app` folder is moved there on first start, so settings and black-box runs carry over.
- Removed the development-only Questionnaire and the legacy two-input screening derivation (trip magnitude x reconnect
  time). The PERC1 DLL's default parameters are now a literal set (`PERC1_DEFAULT_CONS`), identical to the values the
  derivation produced; Screening and Post-Commissioning are unchanged.
- The PSS/E validation libraries, the rigs that ran them and their tooling are not part of the public repository. Their
  results are summarized in the model pages, and the figures are kept as frozen PSS/E results.
- One app for everyone: the installer and portable ZIP now include Black-Box Validation, user-defined model blocks
  and the black-box guide. The production/development edition split (and `PERC1_EDITION`) is gone. The
  automation CLI and the test suite are part of the project and install from source.
- Dropped the unused `requests` dependency.
- New: GitHub Actions CI (tests and lint on Windows), a code of conduct, `CITATION.cff` and Dependabot version updates.

### User-facing

- **PERC Studio.** The app is now named PERC Studio: window title, app bar, About page, installer, portable ZIP and the `.dyr` header comment.
  Titles no longer say PERC1 or CLOD (the Cooling motors step, the review table rows, the model-version caption); each report names the models it
  actually used.
- **HTML report restyled to match the app.** The report uses the app's fonts, colours and cards, and draws each block with the same three
  charts as the live preview (event, power and state strip, comparison with the standard) under a TRIPS / RIDES THROUGH strip, in place of the
  old 2x2 chart. The title is "Screening Report" or "Data Center Load Model Report", with the models listed under it.

- **Documentation figures redrawn.** The PERC1 standard and PERC1 DLL validation figures on the model pages (cease cycle, `Tdelay`
  NaN, `Vrecon` stranding, post-fault spike, exponents and droop, `Vcease` knife edge, `Tdelay` window, multi-stage undervoltage) use the
  same style as the PERC2 ones: a conclusion title, a how-to-read line, one panel per quantity and the legend beside the panels. The
  data and the claims are unchanged.
- **Documentation: the PERC1 standard `Tdelay` hazard is described as intermittent.** A dip that ends while `Tdelay` is running
  always drops the model's load fraction to almost zero; the network then returns not-a-number, a wrong load or a normal result at
  random (not-a-number in 71 of 470 repeated PSS/E runs). The model pages and the behavior page now say so, with the measurements.

- **Documentation: a "Load models" group.** A model overview comparing the PERC1 DLL, PERC1 standard,
  PERC2 standard and PERC2 DLL v2.3 (capabilities, PSS/E versions, dependencies, hazards and validation
  coverage), and one page per model with its PSS/E validation results and plots.
- **PERC2 standard model (PSS/E 36.7 `PERCxx2U`).** A third model version for IT, VFD and
  Screening blocks: momentary and 4-point long cease for low and high voltage with their own
  reconnect settings, a low/high-frequency cease that never reconnects, droop, voltage exponents
  and current limits with a total-current limit. Presets fill it from their full multi-stage
  tables; the editor warns about every value PSS/E 36.7.1 would change or mishandle (including
  its third long-cease point using the first point's time). `.dyr` export and import, the live
  preview and the HTML report support it. Documented in the model reference and the model
  behavior page.

- **PERC2 DLL v2.3 (ISO-NE `PERC2_v3x_v2p3.dll`).** A fourth model version: the PERC1 DLL with a
  reactive-power lead-lag and momentary cessation's own reconnect band and ramps (179 values).
  Presets carry over from the PERC1 DLL with the voltage reconnect ramps adjusted for the load
  factor (v2.3 stretches them; the PERC1 DLL does not) and the reconnect voltage capped at
  0.95 pu. `.dyr` export and import tell its `PERCBL` records from the PERC1 DLL's by their value
  count. The editor warns about what PSS/E showed the DLL does: the PSS/E 36 build stopping PSS/E
  after a high-voltage momentary cessation and returning not-a-number for any `TA`/`TB`, the
  ignored 50 Hz flag, unchecked out-of-range values, and momentary cessation being taken over by
  a trip stage. Documented in the model reference and the model behavior page.

- **Redesigned window.** A new app bar with the workflow tabs and a version pill, a lighter
  theme with IBM Plex fonts (bundled, SIL OFL), and the same layout on Screening and each
  Post-Commissioning block: a model bar on top, the load and parameters on the left, the test
  event and charts on the right.
- **Model bar.** PERC1 model version, PSS/E record format (Screening), ride-through preset with
  an **Internal** / **Published standard** badge and **Preset docs**, and **Import .dyr…**.
- **Edits are tracked.** Parameters are shown as rows with a one-line summary each; click a row
  to edit it. Edited rows are shaded and bold and counted ("2 edited"), **Reset** is available
  only when something changed, and **Revert this row** undoes one row. Changing preset, file or
  model with edits asks first. **ZIP exponent** and **Current limits** are separate rows.
- **Live preview.** A verdict strip (TRIPS / RIDES THROUGH, load tripped, reconnects, ramp) above
  three charts: the voltage (or frequency) at the bus, power output with an Online / Ceased /
  Reconnecting strip and the fraction that ceased, and a full-width **Voltage vs. standard** card
  that says where the event falls on the preset's envelope.
- **Post-Commissioning.** Steps along the top with each block's MW and the load split; each
  block has its own model strip (blocks can use different PERC1 versions); **Facility response
  to this event** shows every block's response to the same event; Review & export lists each
  block's model, source and edits.
- **Import .dyr.** Each block (Screening, IT, VFD) has an **Import .dyr…** button that loads a PERC1
  record from an existing `.dyr` file so you can inspect it in the live chart before any simulation.
  The block switches to the file's model (DLL or standard), every CON appears in the editor, and the
  chart shows the model without a preset envelope. A file with several records asks which to load.
  Values outside the editor's usual range are kept, not clamped, and flagged. The file's name
  replaces the preset field; **Reset to file** restores the file's values (the block stays on the
  file), and **Use a preset instead** or choosing a preset replaces the imported record. CLOD records
  are recognized but cannot be inspected.

## 1.1.0 - 2026-10-10

### User-facing

- **PERC1 model version selector.** Each block (Screening, IT, VFD) can now be written
  for the PERC1 DLL model (PSS/E 34/35) or the PSS/E 36.7 built-in standard model. The
  editor swaps to that model's own parameters, limits and warnings; the exported
  `.dyr`, the review table, the report and the live chart follow the choice. The standard
  model's chart matches the DLL chart's layout: the TRIPS / RIDES THROUGH heading, the
  preset's voltage and frequency ride-through envelopes, and the model's cease region
  overlaid on the voltage envelope (overvoltage and frequency trips are marked not modelled).
- The standard model's editor and report warn when a constant-power block could draw more
  than 110% of its power right after a fault clears (`Ipmax / Ldfact`).
- The Model behavior page documents the standard model's edge cases (a dip ending during
  `Tdelay`, a stranded `Vrecon`, the power spike when a fault clears) with PSS/E plots.
- The live chart now follows the PERC1 behavior measured in PSS/E:
  - **Current limits.** Constant-power blocks (`NPA = 0`) are limited to
    V·`IPMAXA`/`LFM` in a sag (ERCOT at 0.30 pu draws 0.47 pu, not 1.0),
    with the dip at sag onset, the overshoot on recovery and the decay after
    a trip.
  - **Reconnect window.** A block reconnects only while the voltage is
    strictly between `VRPA` and `VRUPA` (frequency: `FUFRN1`-`FOFRN1`). The
    five presets with `VRPA = 1.00` now show the block staying tripped, and
    the status line and recovery strip say why. A `VRPA` below a trip stage
    shows the block cycling.
  - **Frequency droop.** Frequency events apply `DROOPA`/`DBA`: -25% load at
    58.5 Hz with `DROOPA = 10`.
  - **Trip timing** uses the `TVM`/`TFRQ`-filtered voltage and frequency,
    and `CMTDELAY`/`CMTDELAYC`. Trips land within three PSS/E time steps
    of PSS/E's.
  - A block with `IPMAXA` below `LFM` starts at `IPMAXA`/`LFM` and the
    status line says so.
- Model behavior and limitations: the figures now compare PSS/E with the
  new simulator.

### Developer

- New load model `perc1_standard`: PSS/E 36.7's built-in `PERCxx1U` power-electronic
  load component (30 CONs, `MAINxx10` + `USRLODC` records, validated limits,
  preset mapping, analytic simulator for the mock runner and sweeps).
- `src/model_ui.py` (per-model editor spec) and `src/standard_preview.py` (the standard
  model's response page); `ui.py` builds its Advanced editor from the spec.
- `case_to_ui_state`/`ui_state_to_case` and the `perc1-dev` CLI (generate, export, run,
  validate, report, sweep) work on `perc1_standard`; `validate` reports overvoltage and
  frequency scenarios as not modelled for it.
- PSS/E validation evidence reorganized one folder per model: the PERC1 DLL
  (moved) and PERC1 standard (new: 435 PSS/E 36.7.1 tests, no DLL).
- `simulate_perc1_response`/`simulate_perc1_frequency_response` take an
  optional recovery level, and return every trip and reconnect
  (`trip_events`, `reconnect_events`), `reconnects`, `cycles`,
  `stays_tripped_reason` and `initial_power_pu`. A trip without a reconnect
  has no `reconnect_start`/`reconnect_end` markers.
- The mock runner no longer adds an extra resampled point when `sim_end`
  isn't a round number.

## 1.0.1 - 2026-09-30

First published production release, for distribution to CURENT members.
(1.0.0 was an internal draft that was never published; everything below is
new relative to the development-only v0.1.0-alpha.)

### User-facing

- Windows installer (per-user, no admin rights) with a desktop shortcut and
  Start-menu entry, and a portable ZIP with a shortcut script. The app
  icon is the CURENT mark on white.
- Screening, Post-Commissioning and Documentation tabs. The live charts work
  offline: plotly.js is bundled instead of loaded from the web.
- New documentation library: Getting started, Generic parameter tiers,
  PERC1 model reference, **Model behavior and limitations** (the PSS/E
  validation results, with nine figures including the current-limit and
  droop rules), the ride-through preset pages, and Under development /
  Future work.
- About page with the version, build and license texts.
- Reports no longer describe preset-based blocks as "questionnaire answers".
  The Screening report is a short, PERC1-only report; Post-Commissioning
  keeps the full facility report.
- Feedback contact on the About page, in Getting
  started and in the ZIP's README.
- MIT License.

### Developer

- `src/build_info.py` (version and edition) and `src/resources.py`
  (data-file paths that also work frozen). The Questionnaire moved to
  `src/ui_questionnaire.py` and is development-only.
- User documentation moved to `docs/user/` (the only documentation the build
  ships), with `docs/user/library.yaml` driving the Documentation tab. The
  developer material split out into `docs/developer/ADDING_A_PRESET.md` and
  `docs/developer/QUESTIONNAIRE_TIERS.md`.
- `packaging/`: PyInstaller spec, Inno Setup script, icon generator and
  `build_release.py` (staging, leak scan, smoke test, ZIP, installer,
  checksums, optional code signing).
- `docs/scripts/generate_model_behavior_figures.py` builds the behavior
  figures from the raw PSS/E traces.
- Tests for the edition split, the user-docs link rules and resource paths.
