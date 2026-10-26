"""`perc-studio results list|show|cases|plot` and `perc-studio dll inspect` - the command-line side of the app's
Black-Box Validation results explorer and DLL check. They read what `perc-studio blackbox` (or the tab) left on disk;
none of them needs PSS/E."""

from __future__ import annotations

import click

from ._output import UsageError, ValidationMismatch, cli_result, pretty_option


def _summary_dict(summary) -> dict:
    return {
        "folder": str(summary.folder), "title": summary.title, "generated": summary.generated,
        "level": summary.level, "cases": summary.cases, "model": summary.model, "dyr_name": summary.dyr_name,
        "dlls": list(summary.dlls), "psse_version": summary.psse_version, "workers": summary.workers,
        "wall_seconds": summary.wall_seconds, "delt": summary.delt, "stopped": summary.stopped,
        "overall": summary.overall,
        "compared": [{"preset": label, "overall": overall, "families": families}
                     for label, overall, families in summary.compared],
        "warnings": list(summary.warnings),
    }


@click.group("results")
def results_group():
    """Browse black-box validation runs (the folders `perc-studio blackbox --out` writes)."""


@results_group.command("list")
@click.argument("run_root", type=click.Path(exists=True, file_okay=False))
@pretty_option
def list_results(run_root, pretty):
    """Every run under RUN_ROOT, newest first, with its verdict per preset."""
    from blackbox.runs import list_runs

    with cli_result("results list", pretty) as result:
        result["data"] = {"run_root": run_root, "runs": [_summary_dict(r) for r in list_runs(run_root)]}


@results_group.command("show")
@click.argument("run_folder", type=click.Path(exists=True, file_okay=False))
@pretty_option
def show_results(run_folder, pretty):
    """One run's summary: setup, verdicts, warnings and the measured-behaviour table."""
    from blackbox.runs import measured_rows, read_run

    with cli_result("results show", pretty) as result:
        try:
            doc, summary = read_run(run_folder)
        except (OSError, ValueError) as exc:
            raise UsageError(f"{run_folder} is not a black-box run folder: {exc}") from exc
        result["data"] = {
            **_summary_dict(summary),
            "measured": [{"test": test, "result": res, "boundary": boundary}
                         for test, res, boundary in measured_rows(doc)],
        }


@results_group.command("cases")
@click.argument("path", type=click.Path(exists=True))
@click.option("--group", default=None, help="Only cases in this test group (a family title, as listed).")
@pretty_option
def list_cases(path, group, pretty):
    """The cases of a run folder, validation.json or bundle.zip, with each case's verdict."""
    from blackbox.explorer import ResultsError, open_results

    with cli_result("results cases", pretty) as result:
        try:
            results = open_results(path)
        except ResultsError as exc:
            raise UsageError(str(exc)) from exc
        try:
            cases = [c for c in results.cases if group is None or c.group == group]
            result["data"] = {"path": path, "cases": [
                {"key": c.key, "group": c.group, "label": c.label, "verdict": c.verdict,
                 "event": list(c.event) if c.event else None} for c in cases]}
        finally:
            results.close()


@results_group.command("plot")
@click.argument("path", type=click.Path(exists=True))
@click.option("--case", "case_keys", multiple=True, required=True, help="Case key from `results cases`. Repeatable.")
@click.option("--channel", "channels", multiple=True,
              help="Channel to plot (V, P, Q, F (Hz), or any recorded channel). Repeatable; default V and P.")
@click.option("--out", type=click.Path(dir_okay=False), required=True, help="Write the interactive plot here (HTML).")
@pretty_option
def plot_results(path, case_keys, channels, out, pretty):
    """Overlay the chosen cases' channels in one interactive plotly page."""
    from blackbox.explorer import (
        ResultsError,
        build_figure,
        channel_names,
        load_case,
        open_results,
    )

    with cli_result("results plot", pretty) as result:
        try:
            results = open_results(path)
        except ResultsError as exc:
            raise UsageError(str(exc)) from exc
        try:
            by_key = {c.key: c for c in results.cases}
            unknown = [k for k in case_keys if k not in by_key]
            if unknown:
                raise UsageError(f"unknown case key(s) {unknown}; see `perc-studio results cases`")
            selected, missing = [], []
            for key in case_keys:
                data = load_case(by_key[key])
                (selected.append((by_key[key], data)) if data is not None else missing.append(key))
            if not selected:
                raise UsageError("none of the chosen cases has channel data (case.outx or result.csv)")
            available = channel_names([d for _, d in selected])
            chosen = list(channels) or [c for c in ("V", "P") if c in available] or available[:2]
            bad = [c for c in chosen if c not in available]
            if bad:
                raise UsageError(f"unknown channel(s) {bad}; available: {available}")
            build_figure(selected, chosen).write_html(out, include_plotlyjs="cdn")
        finally:
            results.close()
        result["data"] = {"out": out, "cases": [e.key for e, _ in selected], "channels": chosen}
        result["warnings"] = [f"case {k} has no channel data and was skipped" for k in missing]


@click.group("dll")
def dll_group():
    """Check a model DLL before PSS/E loads it."""


@dll_group.command("inspect")
@click.argument("dll", type=click.Path(exists=True, dir_okay=False), nargs=-1, required=True)
@click.option("--psse-root", default=None, help="PSS/E install folder, searched for the DLL's dependencies.")
@click.option("--model", "models", multiple=True, help="Model name the DLL should export (e.g. PERCBL). Repeatable.")
@pretty_option
def inspect_dlls(dll, psse_root, models, pretty):
    """Architecture, exported symbols, SHA-256 and missing dependencies of each DLL (exit 5 if any has a problem)."""
    from blackbox.dll_inspect import inspect_dll

    with cli_result("dll inspect", pretty) as result:
        reports = [inspect_dll(path, psse_root=psse_root, models=tuple(models)) for path in dll]
        data = {"dlls": [r.to_dict() for r in reports], "all_ok": all(r.ok for r in reports)}
        if not data["all_ok"]:
            bad = sum(1 for r in reports if not r.ok)
            raise ValidationMismatch(f"{bad} of {len(reports)} DLL(s) have problems", data)
        result["data"] = data
