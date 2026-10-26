"""The automation CLI behind `perc-studio <command>`.

`app.launcher.main` hands any `perc-studio` invocation whose first argument is a
command (not an option) to `main()` here. See src/dev/cli/README.md for the full
command reference and JSON output contract. This module never imports PySide6.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

import click

from app.build_info import __version__
from load_models import LOAD_MODELS
from presets.ridethrough import RIDE_THROUGH_PRESETS

from ._output import cli_result, pretty_option
from .blackbox_cmd import blackbox_command, psse_group
from .dyr_cmd import dyr_group
from .models import models_group
from .params import params_group
from .pipeline import export_group, report_group, run, sweep_command, validate_group
from .presets_cmd import presets_group
from .results_cmd import dll_group, results_group
from .scenario_cmd import scenario_group

PSSE_ENV_VARS = ("PERC_STUDIO_PSSE_VERSION", "PERC_STUDIO_PSSE_DIR", "PERC_STUDIO_PSSE_PYTHON", "PERC_STUDIO_PSSE_PSPY", "PERC_STUDIO_PSSE_DLLS")


@click.group()
@click.version_option(__version__, prog_name="perc-studio")
def cli():
    """Automation CLI for PERC Studio: generate
    parameterizations, run them (the built-in mock or real PSS/E), and validate
    actual behavior against each parameterization's own stated ride-through
    envelope. Every subcommand prints one JSON envelope to stdout by default
    - see src/dev/cli/README.md for the full contract."""


@cli.command("info")
@pretty_option
def info(pretty):
    """Version, registered load models, preset count and the PSS/E selection the environment names."""
    with cli_result("info", pretty) as result:
        result["data"] = {
            "version": __version__,
            "python": sys.version.split()[0],
            "models": sorted(LOAD_MODELS),
            "presets": len(RIDE_THROUGH_PRESETS),
            "psse_environment": {k: os.environ[k] for k in PSSE_ENV_VARS if k in os.environ},
        }


cli.add_command(models_group)
cli.add_command(presets_group)
cli.add_command(dyr_group)
cli.add_command(scenario_group)
cli.add_command(results_group)
cli.add_command(dll_group)
cli.add_command(params_group)
cli.add_command(export_group)
cli.add_command(run)
cli.add_command(validate_group)
cli.add_command(report_group)
cli.add_command(sweep_command)
cli.add_command(psse_group)
cli.add_command(blackbox_command)


def main(argv: Sequence[str] | None = None) -> int:
    return cli.main(args=list(argv) if argv is not None else None, prog_name="perc-studio")


if __name__ == "__main__":
    sys.exit(main())
