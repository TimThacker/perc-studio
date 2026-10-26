# PERC Studio

[![CI](https://github.com/TimThacker/perc-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/TimThacker/perc-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)

A desktop studio that accelerates data center modeling for transmission
planning engineers. It takes a facility's ride-through standard and equipment
type, or measured values for an as-built facility, and produces documented,
PSS/E-ready dynamic load models for a data center or similar large,
power-electronics-heavy load. From one window you can build and compare models
across several PSS/E load models, check them against published ride-through
standards, inspect existing `.dyr` files, and export a `.dyr` file plus an HTML
review report. The studio currently supports the PERC1 and PERC2 family (four
variants) and conventional motor load, and is built to take on more load models.

## Abstract

Large Electronic Loads (LELs), such as data centers, are rapidly becoming a dominant share of bulk power system load, with ride-through and reconnection behavior unlike conventional motor-driven load. NERC's May 2026 Level 3 Alert directs Transmission Planners and Planning Coordinators to use the PERC1 model, or an equivalent-or-better model, as the baseline for large load modeling, but these models' many parameters and cease/reconnect options make consistent parameterization difficult without facility-level power electronics data. This work presents a studio that accelerates data center modeling for transmission planning engineers. Given plain-language facility inputs (ride-through capability, trip and reconnect behavior, UPS/VFD front-end type), or full field-measured CON values for as-built facilities, the tool produces a ready-to-use PSS/E `.dyr` file and an HTML report documenting assumptions and plotting simulated ride-through performance live against a library of independently-sourced ride-through presets (three generic tiers plus utility-specific grid-operator standards such as ERCOT NOGRR282, MISO, SPP HILL, and NERC's own PRC-029-1/LLWG SAR proposals), letting planners quickly retrieve a defensible parameterization. This effort complements PNNL's Load Model Data Tool (LMDT), focusing on rapid model parameterization and checking for data-center-class loads.

## Project status

PERC Studio is research software under active development. Work in progress
(also see [docs/user/roadmap.md](docs/user/roadmap.md)):

- **Modular CMLD as a motor-load option.** Offer the modular composite load
  model (CMLD) as an alternative to CLOD for representing the motor share of a
  facility.
- **Faster black-box validation.** Cut the cost of a validation run, which is
  dominated by starting a PSS/E process for every case, by reusing processes
  (behind an equivalence check), scheduling searches asynchronously and using
  idle workers. The target is a Standard run in under 15 minutes.
- **Full-facility testing in a real system.** Upload a PSS/E case and test a
  whole facility, meaning several load models together that represent a data
  center, at its point of connection in that system, instead of one model on a
  single bus.

Future work: parameterize load models from the performance of a PSCAD (EMT)
model run against a benchmark.

The PSS/E validation libraries behind the models (several thousand cases on
PSS/E 35.6 and 36.7) are not part of this repository. Their results are
summarized in the model pages under [docs/user/](docs/user/model_overview.md).

## Features

| Feature | What it gives you |
|---|---|
| **Ride-through preset library** | Nine explicit, cited presets: three generic tiers (Extended, Standard, Minimal) and utility or grid-operator standards (ERCOT NOGRR282, PJM, MISO, SPP HILL, NERC PRC-029-1 and the NERC LLWG SAR proposal). Each preset has a page with its source, envelope plots and CON mapping. |
| **Multiple load models** | Four PSS/E models today: PERC1 DLL (PSS/E 34/35), PERC1 standard (PSS/E 36.5+), PERC2 standard (36.7) and PERC2 DLL v2.3 (34-36). Choose one per block; presets are carried over to each model as fully as the model allows, and the editor says what is left out. |
| **Facility composition** | Split a facility across IT/UPS, cooling VFD, conventional cooling motors and other load. Each block has its own model, preset, operating mode and editable parameters. |
| **Full parameter editing** | Every CON is editable, grouped into voltage ride-through, frequency ride-through, trip and reconnect fractions, ZIP exponents, current limits and other. Edited rows are marked and revert individually. Hovering a label shows its CON name. |
| **Live response chart** | A fast simulation of the block under a voltage sag/swell or a frequency excursion, shown against the selected preset's voltage envelope (and frequency table where the standard has one), with a TRIPS / RIDES THROUGH verdict, reconnect timing and a facility-wide response. It follows rules measured in PSS/E; it is not PSS/E. |
| **`.dyr` import** | Load a record from an existing `.dyr` file to see what it does before simulating it. Values are kept as written, and out-of-range values are flagged, not clamped. |
| **Exports** | A `.dyr` file in the exact CON layout of the vendor model, and an HTML report with the load, the assumptions, the preset citation, every parameter against its real mnemonic, a data-confidence label per block and the response plots. |
| **Built-in documentation** | A Documentation tab with a model comparison, a parameter reference, the PSS/E behaviors and limitations found in testing, and a page per preset. |
| **Validated against PSS/E** | Every model was run in real PSS/E (over 2,000 runs across the four models), and every shipped preset was run against the real model. The editor warns about each reproduced pitfall, such as a reconnect voltage that strands the load. The results are summarized in each model's page. |
| **Black-box validation** | Tests any PSS/E load model, with no knowledge of its internals, by searching for the voltage and frequency boundaries where it rides through, trips or never reconnects, and compares them with a standard. See [docs/black_box/](docs/black_box/BLACK_BOX_VALIDATION.md). |
| **Automation CLI** | `perc-studio` generates, runs and validates parameterizations from scripts (install from source). See [src/dev/cli/README.md](src/dev/cli/README.md). |

## How to use it

1. **Launch** the app (installer, portable ZIP, or `uv run perc-studio`
   from source; see [Install](#install)).
2. **Choose a starting point.** Use **Screening** for a quick single-block
   estimate, or **Post-Commissioning** for a full facility.
3. **Pick a model version and a ride-through preset** (for example ERCOT
   NOGRR282 or the generic Standard tier). Enter the load name, bus and MW/Mvar.
   For a facility, set the load split across blocks.
4. **Review and adjust.** Open any parameter row to edit it. Watch the live
   chart: choose a voltage or frequency event, set its depth and duration, and
   check the verdict and the position against the preset's envelope.
5. **Export** the `.dyr` with **Save .dyr...** and the HTML report with
   **Save report...**. To inspect an existing model instead, use **Import .dyr...**.
6. **Run it in PSS/E.** Add a matching static Load record (same bus and ID) to
   your power-flow case, load the `.dyr`, and confirm the model ordering
   against your installed Model Library. The app does not include PSS/E or the
   PERC DLLs.

[docs/user/getting_started.md](docs/user/getting_started.md) walks through each
screen in detail.

## What the app does

A data center's load is not a single lump of MW - it is a mix of IT/compute
load behind UPS power electronics, cooling load behind VFDs, conventional
cooling motors, and other miscellaneous load, each of which responds
differently to a voltage sag on the bulk power system. This studio helps a
transmission planning engineer:

1. Describe each block of the facility with a ride-through preset - one of
   three generic tiers or a specific utility/RTO/ISO standard (ERCOT, SPP,
   PJM, MISO, NERC) from an explicit, cited library - and its equipment type
   (UPS operating mode, VFD front end), or with field-measured values.
2. Have those choices translated into numeric PSS/E model parameters by a
   documented, inspectable rule set (`src/presets/ridethrough.py`, each
   model's `cons.py` and `presets.py` under `src/load_models/`).
3. Get back a ready-to-use `.dyr` file - built to the **exact CON layout of
   the vendor model**, not an approximation - plus an HTML report that
   documents every assumption, shows the parameters against their real model
   mnemonics, and plots the block's simulated response to a voltage sag/swell
   or a frequency excursion live against the selected standard's own voltage
   envelope and (where the standard publishes one) frequency ride-through
   table.

It is an engineering aid for constructing a documented, defensible starting
model - not a certified vendor export. Confirm CON ordering against your
installed PSS/E Model Library and treat placeholder values as placeholders
until field-validated (the app tracks and displays this confidence level
explicitly).

## Workflows

The app bar at the top of the window switches between:

- **Screening** - a single-page form (load, bus, ride-through preset) for a
  quick, preliminary estimate with a live response chart.
- **Post-Commissioning** - the full facility (IT/UPS, cooling VFD,
  conventional motors), with every block's parameters editable in its
  parameter rows.
- **Documentation** - the user documentation library
  ([docs/user/](docs/user/library.yaml)); each block's **Preset docs** link opens
  its page there. A source checkout adds a **Developers** group with the
  contributor documentation.
- **Black-Box Validation** - runs any PSS/E load
  model through a ride-through test protocol in your own PSS/E; see
  [docs/black_box/BLACK_BOX_VALIDATION.md](docs/black_box/BLACK_BOX_VALIDATION.md).

## Requirements

- **Python 3.13** to run from source. The app is developed and tested on
  Windows; the installer and portable ZIP are Windows 10/11 (64-bit) only.
- **PSS/E is not required** to build, edit and export models. Only black-box
  validation and the real PSS/E runner need a licensed PSS/E (35.x or 36.x).
- The PERC1 and PERC2 user-defined model DLLs belong to ISO-NE and are not
  distributed with this app; PERC1 standard and PERC2 standard are built into
  PSS/E 36.

## Install

**Windows installer or portable ZIP.** Download them from the
[Releases](https://github.com/TimThacker/perc-studio/releases) page. Both are
the full app and need no Python.

**From source**, with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/TimThacker/perc-studio.git
cd perc-studio
uv sync
uv run pytest -q
```

Or without uv:

```bash
git clone https://github.com/TimThacker/perc-studio.git
cd perc-studio
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -e .
pip install pytest ruff
pytest -q
```

## Running the app

```bash
uv run perc-studio                            # opens on Screening
uv run perc-studio --mode post-commissioning  # opens on Post-Commissioning
uv run python src/main.py                     # the same app, as a script
```

Without uv, run `perc-studio` (or `python src/main.py`) with the virtual
environment activated.

## Installer and source install

The installer and portable ZIP contain the desktop app: every workflow,
black-box validation and the user documentation. Installing from source gives
the same desktop app plus the `perc-studio` automation CLI, the test suite and
the contributor documentation (the Documentation tab's **Developers** group).
Building the installer and ZIP: [packaging/README.md](packaging/README.md).

## Automation CLI

The same `perc-studio` command, given a command instead of options, is a
scriptable command-line tool (from a source install) for generating
parameterizations programmatically, running them (a built-in analytic mock,
or real PSS/E once a PSS/E install is selected), and validating the result
against what a ride-through preset's own envelope says should happen.
`perc-studio help` lists the commands:

```bash
uv run perc-studio params generate --source preset --preset-id ercot_nogrr282 --out case.json
uv run perc-studio dyr to-case vendor.dyr --out vendor_case.json   # load an existing .dyr
uv run perc-studio sweep my_sweep_spec.json --output-dir output/my_run
```

It requires no PySide6/Qt runtime and prints structured JSON by default. See
[src/dev/cli/README.md](src/dev/cli/README.md) for the command map, a
reference page per command group, the JSON output contract, and a
[cookbook](src/dev/cli/docs/cookbook.md) of worked examples.

## Documentation

Indexed in [docs/README.md](docs/README.md):

| Document | What's in it |
|---|---|
| [docs/user/model_overview.md](docs/user/model_overview.md) | **Start here for load models.** Every supported model compared side by side (PSS/E versions, what each can represent, pitfalls, validation), with a page per model: [PERC1 DLL](docs/user/model_perc1_dll.md), [PERC1 standard](docs/user/model_perc1_standard.md), [PERC2 standard](docs/user/model_perc2_standard.md) and [PERC2 DLL v2.3](docs/user/model_perc2_dll.md). |
| [docs/user/](docs/user/library.yaml) | The user documentation library shipped with the app: getting started, generic parameter tiers, a user-level model reference, the PSS/E model behavior and limitations page, the ride-through preset pages (one per standard, with citations, envelope plots and CON mapping) and the roadmap. |
| [docs/developer/PERC1_MODEL.md](docs/developer/PERC1_MODEL.md) | Deep reference for the PERC1 and CLOD models: the full 173-CON DLL layout, what each CON does, the three cease/reconnect Options, the DLL-vs-Standard variant gap, and the exported `.dyr` record format. |
| [docs/developer/PERC2_MODEL.md](docs/developer/PERC2_MODEL.md) | The PERC2 standard model (PSS/E 36.7's built-in `PERCxx2U`): six cease checks with their own reconnect settings, how presets map onto them, and the PSS/E 36.7.1 issues the app works around. |
| [docs/developer/PERC2_DLL_MODEL.md](docs/developer/PERC2_DLL_MODEL.md) | The PERC2 DLL v2.3 (ISO-NE's `PERC2_v3x_v2p3.dll`, PSS/E 34-36): how the app tells its `PERCBL` records from the PERC1 DLL's, carries presets over, and what the v35 and v36 builds do that the document does not say. |
| [docs/developer/ADDING_A_PRESET.md](docs/developer/ADDING_A_PRESET.md) | Adding or editing a ride-through preset (the whole library is one dict in [`src/presets/ridethrough.py`](src/presets/ridethrough.py)) and regenerating the preset plots. |
| [docs/developer/ADDING_A_LOAD_MODEL.md](docs/developer/ADDING_A_LOAD_MODEL.md) | Registering a new PSS/E load model in `src/load_models/` and running it through `perc-studio`'s generate -> export -> run -> validate -> sweep loop. |
| [docs/developer/ARCHITECTURE.md](docs/developer/ARCHITECTURE.md) | Project layout and what each source module is responsible for - start here if you're contributing code. |
| [docs/black_box/BLACK_BOX_VALIDATION.md](docs/black_box/BLACK_BOX_VALIDATION.md) | Black-box model validation: how to run it, how it works inside, how to read the results, and its limits. |
| [src/dev/cli/README.md](src/dev/cli/README.md) | The `perc-studio` automation CLI. |
| [packaging/README.md](packaging/README.md) | Building the production installer and portable ZIP, code signing, and the release checklist. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Set up, test, and contribute. |

## Notes for engineering use

- This is an engineering aid for constructing a documented starting model,
  not a final vendor-certified model export.
- Always confirm model ordering and assumptions against the installed PSS/E
  Model Library before final study use - `.dyr` output includes a reminder
  comment to this effect.
- Every IT/UPS and VFD block carries an explicit data-confidence label
  (**Field-validated**, **Vendor nameplate/spec sheet**, or **Placeholder**); the HTML report shows this per block and
  adds a warning banner if any block is still using placeholder values.
- The PERC and CLOD records are `USRLOD`/`USRLODC` models and carry no MW/Mvar
  themselves - a matching static Load record (by bus + ID) must exist in the power flow
  case.
- The response plots in the HTML report are an illustrative fixed scenario,
  not a substitute for a full EMT/stability simulation.

## License

MIT; see [LICENSE](LICENSE). Bundled third-party components and their
licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Neither PSS/E nor the PERC1 or PERC2 user-defined model DLLs are included.

## Acknowledgements

Developed at CURENT, The University of Tennessee, Knoxville, in partnership
with the Tennessee Valley Authority.

## Citing

If you use PERC Studio in your work, please cite it using the metadata in
[CITATION.cff](CITATION.cff) (GitHub's "Cite this repository" button reads it).

## Contact

Point of contact: Tim Thacker, <tthacke3@vols.utk.edu>.

Bug reports and feature requests:
[GitHub Issues](https://github.com/TimThacker/perc-studio/issues). For
security issues, see [SECURITY.md](SECURITY.md).
