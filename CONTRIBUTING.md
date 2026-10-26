# Contributing

Thanks for your interest in perc-studio.

## Rules

- `main` is protected. Nobody pushes to it directly except the maintainer.
- All changes from contributors arrive as pull requests from a fork.
- Every pull request needs approval from the maintainer (the code owner) before it merges.
- Open an issue before starting large changes so we can agree on the approach.
- Keep pull requests small and focused on one thing.
- By contributing, you agree your work is released under the project's LICENSE.

## Workflow

1. Fork the repository and create a branch from `main`.
2. Make your change and test it.
3. Open a pull request and fill in the template.
4. Respond to review comments. The maintainer decides what merges.

## Development setup

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). The app is developed and tested on Windows.

```bash
uv sync                         # the app and its dev tools
uv run python src/main.py       # the app
uv run pytest -q                # the whole suite
uv run ruff check               # the lint
```

The suite takes about five minutes. Tests that need a licensed PSS/E skip without one, and CI runs without PSS/E.
A pull request must leave `uv run pytest -q` and `uv run ruff check` passing.

## Branches, commits and pull requests

- Name your fork branch for its kind: `feature/`, `fix/`, `refactor/` or `chore/`, followed by a short topic.
- Make one logical change per commit, with a message that says what changed and why. Do not add generated-by or
  co-author trailers.
- Fill in [the pull request template](.github/pull_request_template.md): what changed, why, how it was tested (with
  the test counts) and what was not done.
- If your change affects model behavior (a CON, a default, a simulator rule, a preset), say whether you checked it
  against a real PSS/E run, and which version.

## Where things go

| Adding | Start with |
|---|---|
| a ride-through preset | [docs/developer/ADDING_A_PRESET.md](docs/developer/ADDING_A_PRESET.md) |
| a load model | [docs/developer/ADDING_A_LOAD_MODEL.md](docs/developer/ADDING_A_LOAD_MODEL.md) |
| a script that is not part of the app | `utils/scripts/` |
| documentation | [docs/README.md](docs/README.md) says which folder |

The code layout is described in [docs/developer/ARCHITECTURE.md](docs/developer/ARCHITECTURE.md).

**The rule:** `utils/` and `tests/` never ship, and nothing under `src/` may import from them. The user documentation
(`docs/user/`) links only within `docs/user/`. The packaging step and `tests/test_user_docs.py` enforce this.

## Regenerating figures

The SVGs in `docs/user/figures/` are generated from the app's own data. After changing a preset, run:

```bash
uv run python utils/scripts/generate_envelope_figures.py
uv run python utils/scripts/generate_parameter_preset_figures.py
```

The PNGs in the same folder are frozen PSS/E results and are not regenerated here.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By taking part you agree to uphold it.
