"""The runs in a run folder: a short summary of each, read from its `validation.json` only.

No Qt and no channel data, so listing a folder of past runs is quick. A run folder is
`<run root>/<YYYYmmdd-HHMMSS>/` holding `report.html`, `validation.json`, `bundle.zip`
and `work/cache/<case key>/` (each case's `job.json`, `meta.json`, `result.csv`,
`psse.log` and `case.outx`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VERDICT_ORDER = ("fails", "at the edge", "not solvable", "beyond tested range", "meets", "no requirement")
KINDS = ("undervoltage", "overvoltage", "frequency")


@dataclass(frozen=True)
class RunSummary:
    folder: Path
    generated: str  # "2026-10-12 14:03:11"
    level: str
    level_title: str
    cases: int
    dyr_name: str
    model: str  # the model under test, e.g. "PERC1" (from the load target), or the .dyr name
    dlls: tuple[str, ...]
    psse_version: str  # "35.6" (the selection) or "35.6.4" when PSS/E reported it
    python: str
    compared: tuple[tuple[str, str, dict], ...]  # (preset label, overall verdict, {kind: verdict})
    wall_seconds: float
    workers: int
    delt: float | None
    stopped: str | None
    warnings: tuple[str, ...] = field(default=())

    @property
    def doc_path(self) -> Path:
        return self.folder / "validation.json"

    @property
    def when(self) -> datetime | None:
        try:
            return datetime.strptime(self.generated, "%Y-%m-%d %H:%M:%S")  # local time, as written
        except ValueError:
            return None

    @property
    def short_version(self) -> str:
        return ".".join(self.psse_version.split(".")[:2])

    @property
    def title(self) -> str:
        """"PERC1 DLL · 35.6 · Standard"."""
        return f"{self.model} · {self.short_version} · {self.level_title}"

    @property
    def tab_title(self) -> str:
        return f"Run · {self.model} · {self.short_version}"

    @property
    def heading(self) -> str:
        """"PERC1 DLL on PSS/E 35.6 · Standard level"."""
        return f"{self.model} on PSS/E {self.short_version} · {self.level_title} level"

    def date_text(self, *, year: bool = True) -> str:
        when = self.when
        if when is None:
            return self.generated
        return f"{when.day} {when:%b}" + (f" {when.year}" if year else "")

    @property
    def subtitle(self) -> str:
        """"12 Oct 2026 · 396 cases, all completed · 32 min on 4 workers · time step 0.00417 s"."""
        parts = [self.date_text(), f"{self.cases} cases" + (", all completed" if not self.stopped else
                                                              f", stopped: {self.stopped}")]
        minutes = self.wall_seconds / 60.0
        parts.append((f"{minutes:.0f} min" if minutes >= 1 else f"{self.wall_seconds:.0f} s")
                     + f" on {self.workers} worker{'s' if self.workers != 1 else ''}")
        if self.delt:
            parts.append(f"time step {self.delt:.3g} s")
        return " · ".join(parts)

    @property
    def overall(self) -> str | None:
        """The worst verdict across the compared presets (None when nothing was compared)."""
        found = [verdict for _label, verdict, _per in self.compared]
        return next((v for v in VERDICT_ORDER if v in found), None)


def _model_name(doc: dict) -> str:
    """The model under test as people call it: "PERC1 DLL", "PERC1 standard", else the record's own model name(s)."""
    target = doc.get("stages", {}).get("intake", {}).get("target") or ""
    names = [n.strip() for n in target.split(" - ")[0].split("+") if n.strip()]
    if any(re.fullmatch(r"PERC(BL|OW|ZN|AR|AL)1U", n) for n in names):
        return "PERC1 standard"
    names = ["PERC1 DLL" if n == "PERC1" else n for n in names if not re.fullmatch(r"MAIN(BL|OW|ZN|AR|AL)10", n)]
    return " + ".join(names) or Path(doc.get("setup", {}).get("dyr_name") or "model").stem


def _psse_version(doc: dict) -> str:
    env = doc.get("environment", {})
    v = env.get("psse") or {}
    if v.get("major") is not None:
        return ".".join(str(v[k]) for k in ("major", "minor", "patch") if v.get(k) is not None)
    return env.get("selection", {}).get("version", "")


def summary_warnings(doc: dict) -> list[str]:
    """Everything a reader should know before trusting the result: initialization and time-step warnings, intake
    flags, robustness differences, failed runs and non-monotonic searches. Plain text (the report escapes it)."""
    out: list[str] = []
    st = doc.get("stages", {})
    for key in ("initialization", "time_step"):
        if st.get(key, {}).get("warning"):
            out.append(st[key]["warning"])
    out.extend(st.get("intake", {}).get("flags", []))
    robustness = st.get("robustness", {})
    if robustness.get("cadence", {}).get("warning"):
        out.append(robustness["cadence"]["warning"])
    for r in robustness.get("half_step", []):
        if not r["match"]:
            out.append(f"{r['case']}: the outcome changes at half the time step ({r['outcome']} vs "
                       f"{r['half_step_outcome']})")
    for fam in doc.get("families", {}).values():
        if fam.get("failures"):
            out.append(f"{fam['title']}: {fam['failures']} run(s) failed or were unstable")
        for s in fam.get("searches", []):
            if not s.get("monotonic", True):
                out.append(f"{fam['title']} at {s['tag']:g} {fam.get('outer_unit', '')}: the outcome flips more "
                           "than once along the axis (not monotonic)")
    return out


def summarize(doc: dict, folder: Path) -> RunSummary:
    setup = doc.get("setup", {})
    stats = doc.get("stats", {})
    compared = tuple(
        (comp.get("label", pid), comp.get("overall", "no requirement"),
         {kind: fam.get("overall") for kind, fam in comp.get("families", {}).items()})
        for pid, comp in doc.get("comparison", {}).items())
    return RunSummary(
        folder=Path(folder), generated=doc.get("generated", ""), level=setup.get("level", ""),
        level_title=setup.get("level_title", setup.get("level", "")).strip() or "?",
        cases=int(stats.get("cases_run", 0)) + int(stats.get("cases_cached", 0)) or len(doc.get("points", [])),
        dyr_name=setup.get("dyr_name") or "", model=_model_name(doc), dlls=tuple(setup.get("dlls", [])),
        psse_version=_psse_version(doc), python=str(doc.get("environment", {}).get("python") or ""),
        compared=compared, wall_seconds=float(stats.get("wall_seconds", 0.0)), workers=int(stats.get("workers", 0)),
        delt=stats.get("delt"), stopped=doc.get("stopped"), warnings=tuple(summary_warnings(doc)))


def read_run(folder: str | Path) -> tuple[dict, RunSummary]:
    folder = Path(folder).resolve()  # the report page cannot load a relative file URL
    doc = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
    return doc, summarize(doc, folder)


def list_runs(run_root: str | Path) -> list[RunSummary]:
    """Every run under `run_root`, newest first. Folders without a readable validation.json are skipped."""
    root = Path(run_root)
    if not root.is_dir():
        return []
    runs = []
    for folder in root.iterdir():
        if not (folder / "validation.json").is_file():
            continue
        try:
            runs.append(read_run(folder)[1])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(runs, key=lambda r: (r.generated, r.folder.name), reverse=True)


def case_files(folder: str | Path) -> list[Path]:
    """Every case's channel file in a run folder."""
    return sorted(Path(folder).glob("work/cache/*/case.outx"))


def measured_rows(doc: dict) -> list[tuple[str, str, str]]:
    """(Test, Result, Boundary) rows for the summary's "Measured behaviour" table, grouping neighbouring values
    with the same outcome: ("Undervoltage 0.3–0.4 pu", "trips after", "0.273–0.289 s")."""
    rows: list[tuple[str, str, str]] = []
    for kind in KINDS:
        fam = doc.get("families", {}).get(kind)
        if not fam or "searches" not in fam:
            continue
        unit, name = fam.get("outer_unit", ""), kind.capitalize()
        groups: list[list] = []
        for s in sorted(fam["searches"], key=lambda s: s["tag"]):
            ok = [d for d, rode in s["points"] if rode]
            trip = [d for d, rode in s["points"] if not rode]
            if not trip:
                key = ("rides through", "whole tested range")
            else:
                lo = max((d for d in ok if d < min(trip)), default=None)
                key = ("trips after", f"{lo:.3f}–{min(trip):.3f} s" if lo is not None else f"under {min(trip):.3f} s")
            if groups and groups[-1][1] == key:
                groups[-1][0].append(s["tag"])
            else:
                groups.append([[s["tag"]], key])
        for tags, (result, boundary) in groups:
            span = f"{tags[0]:g}" if len(tags) == 1 else f"{tags[0]:g}–{tags[-1]:g}"
            rows.append((f"{name} {span} {unit}".strip(), result, boundary))
    rec = doc.get("families", {}).get("recovery")
    if rec and rec.get("reconnections"):
        ok = [r for r in rec["reconnections"] if r.get("reconnected")]
        if ok:
            lo, hi = min(r["recovery_pu"] for r in ok), max(r["recovery_pu"] for r in ok)
            pick = min(ok, key=lambda r: abs(r["recovery_pu"] - 1.0))
            timing = " · ".join(t for t in (
                f"delay {pick['delay_s']:.1f} s" if pick.get("delay_s") is not None else "",
                f"ramp {pick['ramp_s']:.1f} s" if pick.get("ramp_s") is not None else "") if t)
            rows.append(("Reconnection", f"between {lo:.2f} and {hi:.2f} pu", timing or "-"))
    return rows
