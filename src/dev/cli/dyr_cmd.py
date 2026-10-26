"""`perc-studio dyr list|show|to-case` - read an existing PSS/E `.dyr` file: which model records it holds, their
CONs, and a LoadCase built from one (the CLI side of the app's Import .dyr)."""

from __future__ import annotations

from pathlib import Path

import click

from dev.validation.case_model import (
    BLOCK_NAMES,
    FacilityInfo,
    LoadComposition,
    case_from_model_defaults,
    case_with_overrides,
    to_dict,
    to_json,
)

from ._output import UsageError, cli_result, pretty_option


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise UsageError(f"could not read {path}: {exc.strerror or exc}") from exc


def _ref_dict(ref) -> dict:
    return {
        "record": ref.index, "model_id": ref.model_id, "scope": ref.scope, "number": ref.number,
        "load_id": ref.load_id, "inspectable": ref.inspectable, "error": ref.error, "label": ref.label,
    }


def _import(path: str, record: int | None):
    # Lazy: `dev` may not import `editor` at module level (tests/test_layering.py).
    from editor.dyr_import import import_record

    try:
        return import_record(_read(path), record)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


@click.group("dyr")
def dyr_group():
    """Read an existing .dyr file (PERC1/PERC2 DLL and standard records, CLOD)."""


@dyr_group.command("list")
@click.argument("dyr_file", type=click.Path(exists=True, dir_okay=False))
@pretty_option
def list_dyr(dyr_file, pretty):
    """The model records in the file, numbered for --record."""
    from editor.dyr_import import list_records

    with cli_result("dyr list", pretty) as result:
        records = [_ref_dict(r) for r in list_records(_read(dyr_file))]
        result["data"] = {"file": dyr_file, "records": records}


@dyr_group.command("show")
@click.argument("dyr_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--record", type=int, default=None, help="Record number from `dyr list` (optional with one record).")
@pretty_option
def show_dyr(dyr_file, record, pretty):
    """One record's CONs, with warnings for values outside the usual range."""
    with cli_result("dyr show", pretty) as result:
        imported = _import(dyr_file, record)
        result["data"] = {
            **_ref_dict(imported.ref),
            "cons": imported.cons,
            "extras": {k: v for k, v in imported.extras.items()},
        }
        result["warnings"] = list(imported.warnings)


@dyr_group.command("to-case")
@click.argument("dyr_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--record", type=int, default=None, help="Record number from `dyr list` (optional with one record).")
@click.option("--block", type=click.Choice(list(BLOCK_NAMES)), default="it", help="Block the record fills.")
@click.option("--facility-name", default="Imported .dyr")
@click.option("--bus-number", type=int, default=None, help="Defaults to the record's own bus number.")
@click.option("--bus-name", default="DC_POI")
@click.option("--total-mw", type=float, default=300.0)
@click.option("--case-id", default=None)
@click.option("--out", type=click.Path(dir_okay=False), default=None, help="Write the case JSON here.")
@pretty_option
def dyr_to_case(dyr_file, record, block, facility_name, bus_number, bus_name, total_mw, case_id, out, pretty):
    """A LoadCase with the record's CONs in one block (source "defaults"; every imported CON is in `overrides`)."""
    with cli_result("dyr to-case", pretty) as result:
        imported = _import(dyr_file, record)
        number = bus_number if bus_number is not None else (imported.ref.number if imported.ref.scope == "bus" else 100001)
        facility = FacilityInfo(name=facility_name, bus_number=number, bus_name=bus_name, use_case="AI Training",
                                use_case_pct=100, total_mw=total_mw, power_factor=0.99)
        try:
            case = case_from_model_defaults(
                imported.model_id, facility=facility, load_composition=LoadComposition(100.0, 0.0, 0.0, 0.0),
                block_name=block, case_id=case_id,
            )
            case = case_with_overrides(case, block, dict(imported.cons))
        except (KeyError, ValueError) as exc:
            raise UsageError(str(exc).strip('"')) from exc
        if out:
            to_json(case, out)
        result["data"] = {"case": to_dict(case), "out": out, "source_record": _ref_dict(imported.ref)}
        result["warnings"] = list(imported.warnings)
