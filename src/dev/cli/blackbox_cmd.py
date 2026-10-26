"""`perc-studio psse check` and `perc-studio blackbox` - the command-line side of
black-box validation (docs/black_box/BLACK_BOX_VALIDATION.md). Same work as the
app's Black-Box Validation tab, for scripts and the acceptance tests."""

from __future__ import annotations

from pathlib import Path

import click

from ._output import (
    RunnerUnavailableError,
    UsageError,
    ValidationMismatch,
    cli_result,
    pretty_option,
)


def _psse_options(fn):
    fn = click.option("--psse-version", required=True, help="PSS/E version, e.g. 35.6 or 36.7.")(fn)
    fn = click.option("--psse-dir", default="", help="Install folder (default: the version's standard path).")(fn)
    fn = click.option("--python", "python_exe", default="",
                      help="Python that runs psspy (default: found from the folder's PSSPYxx).")(fn)
    fn = click.option("--pspy", "pspy_folder", default="", help="PSSPYxx folder (default: the newest).")(fn)
    return fn


def _selection(psse_version, psse_dir, python_exe, pspy_folder):
    from blackbox.psse_install import (
        SUPPORTED_VERSIONS,
        PsseSelection,
        default_install_dir,
        parse_version,
    )

    try:
        major, minor = parse_version(psse_version)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    if f"{major}.{minor}" not in SUPPORTED_VERSIONS:
        raise UsageError(f"PSS/E {major}.{minor} is not supported: only 64-bit PSS/E 35.x and 36.x are "
                         f"(PSS/E 34 and earlier are 32-bit). Supported: {', '.join(SUPPORTED_VERSIONS)}")
    try:
        folder = psse_dir or default_install_dir(psse_version)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    return PsseSelection(psse_version, folder, python_exe, pspy_folder)


@click.group("psse")
def psse_group():
    """The PSS/E install black-box validation runs on."""


@psse_group.command("check")
@_psse_options
@pretty_option
def psse_check(psse_version, psse_dir, python_exe, pspy_folder, pretty):
    """Start PSS/E with this selection and report what it says."""
    from blackbox.psse_install import check_install

    with cli_result("psse check", pretty) as result:
        check = check_install(_selection(psse_version, psse_dir, python_exe, pspy_folder))
        if not check.ok:
            raise RunnerUnavailableError(check.message)
        result["data"] = check.to_dict()


@click.command("blackbox")
@_psse_options
@click.option("--dyr", "dyr_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--dll", "dlls", multiple=True, type=click.Path(exists=True, dir_okay=False), help="Repeatable.")
@click.option("--load", "load_index", type=int, default=None,
              help="Which load to test (1-based, from --list). Needed when the file has more than one.")
@click.option("--list", "list_only", is_flag=True, help="List the loads in the file and exit.")
@click.option("--level", type=click.Choice(["quick", "standard", "full"]), default="standard")
@click.option("--preset", "presets", multiple=True, help="Preset id to compare with (repeatable).")
@click.option("--delt", type=float, default=None, help="Force the time step (s).")
@click.option("--workers", type=int, default=4)
@click.option("--p-mw", type=float, default=100.0, help="Rig load MW.")
@click.option("--q-mvar", type=float, default=20.0, help="Rig load Mvar.")
@click.option("--out", "out_dir", required=False, type=click.Path(file_okay=False),
              help="Folder for report.html, validation.json and bundle.zip.")
@click.option("--include-dlls", is_flag=True, help="Put the DLLs themselves in the bundle (default: hashes only).")
@pretty_option
def blackbox_command(psse_version, psse_dir, python_exe, pspy_folder, dyr_path, dlls, load_index, list_only,
                     level, presets, delt, workers, p_mw, q_mvar, out_dir, include_dlls, pretty):
    """Characterize a load model as a black box in PSS/E and compare it with presets."""
    from blackbox.intake import load_targets, scan_dyr
    from blackbox.protocol import Validation, ValidationSetup
    from blackbox.psse_install import check_install
    from blackbox.report import write_outputs
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    with cli_result("blackbox", pretty) as result:
        text = Path(dyr_path).read_text(errors="replace")
        targets = load_targets(scan_dyr(text))
        listing = [{"load": i + 1, "label": t.label} for i, t in enumerate(targets)]
        if list_only:
            result["data"] = {"loads": listing}
            return
        if not targets:
            raise UsageError("the .dyr file has no load-model record to test")
        if load_index is None:
            if len(targets) > 1:
                raise UsageError("the file has more than one load; choose one with --load (see --list)")
            load_index = 1
        if not 1 <= load_index <= len(targets):
            raise UsageError(f"--load must be 1-{len(targets)}")
        unknown = [p for p in presets if p not in RIDE_THROUGH_PRESETS]
        if unknown:
            raise UsageError(f"unknown preset(s) {unknown}; known: {sorted(RIDE_THROUGH_PRESETS)}")
        if not out_dir:
            raise UsageError("--out is required")
        check = check_install(_selection(psse_version, psse_dir, python_exe, pspy_folder))
        if not check.ok:
            raise RunnerUnavailableError(check.message)
        out = Path(out_dir)
        setup = ValidationSetup(check.selection, text, target_index=load_index - 1, dlls=tuple(dlls),
                                preset_ids=tuple(presets), level=level, delt=delt, workers=workers, p_mw=p_mw,
                                q_mvar=q_mvar, dyr_name=Path(dyr_path).name)
        doc = Validation(setup, out / "work").run()
        paths = write_outputs(doc, out / "work", out, dyr_text=text, include_dlls=include_dlls)
        data = {"stopped": doc["stopped"], "overall": {k: v["overall"] for k, v in doc["comparison"].items()},
                "stats": doc["stats"], "report": str(paths["html"]), "json": str(paths["json"]),
                "bundle": str(paths["bundle"])}
        if doc["stopped"]:
            raise ValidationMismatch(f"the validation stopped: {doc['stopped']}", data)
        result["data"] = data
