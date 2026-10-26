# Documentation

Where each document lives. The [main README](../README.md) covers what the app does and how to run it.

| Folder | Audience | What is in it |
|---|---|---|
| [`user/`](user/library.yaml) | app users | The in-app Documentation tab. Ships with the app. |
| [`developer/`](developer/ARCHITECTURE.md) | contributors | How the code is organized and how the models work. Source checkout only. |
| [`black_box/`](black_box/BLACK_BOX_VALIDATION.md) | users and contributors | Black-box model validation. Ships with the app and is listed in the Documentation tab. |

## User documentation (`user/`)

Listed in [`user/library.yaml`](user/library.yaml), which sets the Documentation tab's contents. Pages here
must not link outside `user/` (checked by `tests/test_user_docs.py`).

The **Load models** group is the model overview ([model_overview.md](user/model_overview.md), a comparison of all four
models) and one page of PSS/E validation results and plots per model. Update the overview when a model's
capabilities, PSS/E versions or test counts change.

**Figures.** The PNGs in `user/figures/` are frozen PSS/E 35.6 and 36.7 results from the PSS/E validation library,
which is not part of this repository, so they cannot be regenerated here. The SVGs (ride-through envelopes, the
generic tiers, the CLOD composition) are regenerated from the app's own data by
[`utils/scripts/generate_envelope_figures.py`](../utils/scripts/generate_envelope_figures.py) and
[`utils/scripts/generate_parameter_preset_figures.py`](../utils/scripts/generate_parameter_preset_figures.py).

## Developer documentation (`developer/`)

| Document | What is in it |
|---|---|
| [ARCHITECTURE.md](developer/ARCHITECTURE.md) | Project layout and what each module is responsible for. Start here. |
| [Model overview](user/model_overview.md) | Start here for load models: every supported model compared, with links to each model's page and developer reference below. |
| [PERC1_MODEL.md](developer/PERC1_MODEL.md) | The PERC1 DLL and standard models and CLOD: CON layout, the cease/reconnect Options, the exported `.dyr` record. |
| [PERC2_DLL_MODEL.md](developer/PERC2_DLL_MODEL.md) | The PERC2 DLL v2.3 (ISO-NE `PERC2_v3x_v2p3.dll`): the PERC1 DLL plus six CONs, how its records are told from PERC1 DLL records, the ramp and momentary-cessation rules, the v36 build's defects. |
| [PERC2_MODEL.md](developer/PERC2_MODEL.md) | The PERC2 standard model (PSS/E 36.7 `PERCxx2U`): flags and CONs, the cease/reconnect machine, preset mapping, the PSS/E 36.7.1 issues the app works around. |
| [ADDING_A_PRESET.md](developer/ADDING_A_PRESET.md) | Adding or editing a ride-through preset. |
| [ADDING_A_LOAD_MODEL.md](developer/ADDING_A_LOAD_MODEL.md) | Registering a new PSS/E load model. |

## Black-box validation (`black_box/`)

| Document | What is in it |
|---|---|
| [BLACK_BOX_VALIDATION.md](black_box/BLACK_BOX_VALIDATION.md) | How to run a validation, what the code does inside, how to read the results, and its known limits. |
| [BINARY_SEARCH_LIMITS.md](black_box/BINARY_SEARCH_LIMITS.md) | What the boundary search cannot see, worked through on PERC2, and the proposed changes. |

## Elsewhere

| Document | What is in it |
|---|---|
| [CHANGELOG.md](../CHANGELOG.md) | Release notes. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | How to set up, test and contribute. |
| [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | Licenses of bundled components (shown in the app's About page). |
| [packaging/README.md](../packaging/README.md) | Building the installer and portable ZIP, signing, the release checklist. |
| [src/dev/cli/README.md](../src/dev/cli/README.md) | The `perc-studio` automation CLI: command map, with reference pages, a cookbook and the output contract under `src/dev/cli/docs/`. |
| [assets/branding/SOURCES.md](../assets/branding/SOURCES.md) | Where the logos come from. |
