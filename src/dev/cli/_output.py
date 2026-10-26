"""Shared output/exit-code conventions for every perc-studio subcommand.

Every command prints one JSON envelope to stdout by default:
    {"ok": bool, "command": str, "data": {...}, "errors": [...], "warnings": [...]}
and exits with one of the fixed codes below. See src/dev/cli/docs/output_contract.md
for the full reference aimed at an agent
integrator.

Usage inside a command function:

    @params_group.command("generate")
    @click.option(...)
    @pretty_option
    def generate(..., pretty):
        with cli_result("params generate", pretty) as result:
            ... business logic, raising UsageError/SchemaInvalidError/
            ... RunnerUnavailableError/ValidationMismatch as appropriate ...
            result["data"] = {...}
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import click

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_SCHEMA_INVALID = 3
EXIT_RUNNER_UNAVAILABLE = 4
EXIT_VALIDATION_MISMATCH = 5


class UsageError(Exception):
    """Bad arguments, unknown preset id, malformed override, missing file - exit 2."""


class SchemaInvalidError(Exception):
    """A LoadCase failed schema-level validation - exit 3."""


class RunnerUnavailableError(Exception):
    """The requested PsseRunner isn't implemented yet - exit 4."""


class ValidationMismatch(Exception):
    """The command ran to completion, but expected behavior != actual
    behavior - a real result, not a tool failure - exit 5. `data` still
    carries the full result payload."""

    def __init__(self, message: str, data: dict):
        super().__init__(message)
        self.data = data


pretty_option = click.option("--pretty", is_flag=True, default=False, help="Pretty-print JSON output.")


def _envelope(command: str, *, ok: bool, data=None, errors=None, warnings=None) -> dict:
    return {
        "ok": ok,
        "command": command,
        "data": data if data is not None else {},
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }


def _emit(env: dict, *, pretty: bool) -> None:
    click.echo(json.dumps(env, indent=2 if pretty else None))


@contextmanager
def cli_result(command: str, pretty: bool):
    """Yields a dict the caller fills with `result["data"] = {...}` on
    success (and optionally `result["warnings"] = [...]`). Any of the exceptions above (or an unexpected one) is caught
    here, emitted as a JSON envelope, and turned into the matching exit
    code - callers never need to format output or call sys.exit themselves."""
    result: dict = {}
    try:
        yield result
    except UsageError as exc:
        _emit(_envelope(command, ok=False, errors=[str(exc)]), pretty=pretty)
        raise SystemExit(EXIT_USAGE_ERROR) from None
    except SchemaInvalidError as exc:
        _emit(_envelope(command, ok=False, errors=[str(exc)]), pretty=pretty)
        raise SystemExit(EXIT_SCHEMA_INVALID) from None
    except RunnerUnavailableError as exc:
        _emit(_envelope(command, ok=False, errors=[str(exc)]), pretty=pretty)
        raise SystemExit(EXIT_RUNNER_UNAVAILABLE) from None
    except ValidationMismatch as exc:
        _emit(_envelope(command, ok=True, data=exc.data, warnings=[str(exc)]), pretty=pretty)
        raise SystemExit(EXIT_VALIDATION_MISMATCH) from None
    except click.ClickException:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort catch-all, exit 1 by design
        _emit(_envelope(command, ok=False, errors=[f"{type(exc).__name__}: {exc}"]), pretty=pretty)
        raise SystemExit(EXIT_ERROR) from None
    else:
        _emit(_envelope(command, ok=True, data=result.get("data", {}), warnings=result.get("warnings")), pretty=pretty)
