"""Browsing the cases of a black-box validation: which tests were run, what each
recorded, and a figure of the channels you pick.

No Qt here (the tab in `ui/blackbox/explorer.py` is only widgets), so everything
can be tested without a display. A "results set" is a validation's `validation.json`
plus the folder that holds its cases. It is opened from either place a run leaves
its results:

* a run folder (`validation.json` next to `work/cache/<key>/`), or
* a `bundle.zip` (`validation.json` and `cases/<key>/`), unpacked to a temp folder.

Each case folder holds `case.outx` (every recorded channel, read by `blackbox.outx`)
and `result.csv` (the V, F_HZ, P, Q trace the verdicts were judged on). The channel
file wins when it is there and readable; otherwise the CSV is used, so an older
run or a bundle without channel files still plots.
"""

from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import tokens as t

from .outx import ChannelFile, OutxFormatError, read_outx

# The first two follow the app's voltage and power colours; past six cases the dash style changes too.
PLOT_COLORS = (t.PARTNER_BLUE, t.POWER, t.BRAND, "#6B4FA0", "#0E7C86", "#8A5A00")
DASHES = ("solid", "dash", "dot", "dashdot")
CSV_COLUMNS = {"V": "V", "F_HZ": "F (Hz)", "P": "P", "Q": "Q"}  # result.csv column -> channel label
OTHER_GROUP = "Other runs"


class ResultsError(ValueError):
    """The chosen folder or zip is not a black-box validation result."""


@dataclass
class CaseEntry:
    """One simulated case: where it is, what it was, and what the validation concluded."""

    key: str
    group: str  # the benchmark test it belongs to (a family title, or OTHER_GROUP)
    label: str  # the event, e.g. "0 pu for 0.01667 s"
    verdict: str  # "rode through", "tripped", ... or the case status when it was not judged
    folder: Path
    event: tuple[float, float] | None = None  # event start and end, for shading the plot


@dataclass
class ResultsSet:
    doc: dict
    case_root: Path  # the folder whose children are the case folders
    cases: list[CaseEntry]
    temp: tempfile.TemporaryDirectory | None = None  # keeps an unpacked bundle alive

    def close(self):
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None


# --- opening -------------------------------------------------------------------------------------------------------


def _case_root(base: Path) -> Path | None:
    for candidate in (base / "work" / "cache", base / "cases", base / "cache"):
        if candidate.is_dir():
            return candidate
    return None


def open_results(path: str | Path) -> ResultsSet:
    """Open a run folder, its `validation.json`, or a `bundle.zip`."""
    path = Path(path)
    temp = None
    if path.is_file() and path.suffix.lower() == ".zip":
        temp = tempfile.TemporaryDirectory(prefix="bbv_results_", ignore_cleanup_errors=True)
        try:
            with zipfile.ZipFile(path) as z:
                z.extractall(temp.name)
        except zipfile.BadZipFile as exc:
            temp.cleanup()
            raise ResultsError(f"{path.name} is not a zip file: {exc}") from exc
        base = Path(temp.name)
    elif path.is_file() and path.name == "validation.json":
        base = path.parent
    elif path.is_dir():
        base = path
    else:
        raise ResultsError(f"{path} is not a results folder, validation.json or bundle.zip")
    doc_path = base / "validation.json"
    root = _case_root(base)
    if not doc_path.exists() or root is None:
        if temp:
            temp.cleanup()
        raise ResultsError(f"{path} has no validation.json with its cases next to it")
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    return ResultsSet(doc, root, list_cases(doc, root), temp)


def list_cases(doc: dict, case_root: Path) -> list[CaseEntry]:
    """Every case folder under `case_root`, named after the test and event it came from."""
    titles = {fam_id: fam.get("title", fam_id) for fam_id, fam in doc.get("families", {}).items()}
    known: dict[str, CaseEntry] = {}
    for p in doc.get("points", []):
        folder = case_root / p["key"]
        if folder.is_dir():
            known[p["key"]] = CaseEntry(p["key"], titles.get(p["family"], p["family"]), p.get("event", p["key"]),
                                        p.get("outcome", {}).get("label", p.get("status", "")), folder,
                                        (p["event_start"], p["event_end"]) if "event_start" in p else None)
    entries = list(known.values())
    for folder in sorted(case_root.iterdir()):
        if folder.is_dir() and folder.name not in known and (folder / "meta.json").exists():
            entries.append(_unlabelled_case(folder))
    entries.sort(key=lambda e: (e.group == OTHER_GROUP, e.group, e.label))
    return entries


def _unlabelled_case(folder: Path) -> CaseEntry:
    """A case that is not one of the test points (initialization, robustness, a search probe)."""
    status, label = "", folder.name
    try:
        status = json.loads((folder / "meta.json").read_text(encoding="utf-8")).get("status", "")
        segments = json.loads((folder / "job.json").read_text(encoding="utf-8")).get("segments", [])
        label = " -> ".join(f"{v:.3g} pu @ {t:.3g} s" for t, v, _ in segments) or folder.name
    except (OSError, ValueError):
        pass
    return CaseEntry(folder.name, OTHER_GROUP, label, status, folder)


# --- reading one case ----------------------------------------------------------------------------------------------


def _read_csv(path: Path) -> ChannelFile:
    columns: dict[str, list[float]] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            for name, value in row.items():
                columns.setdefault(name, []).append(float(value) if value else float("nan"))
    time = columns.pop("time", [])
    return ChannelFile(str(path), "", time, {CSV_COLUMNS.get(k, k): v for k, v in columns.items()})


def load_case(entry: CaseEntry) -> ChannelFile | None:
    """The case's channels: from `case.outx` when it reads, else from `result.csv`, else None."""
    outx = entry.folder / "case.outx"
    if outx.exists():
        try:
            return read_outx(outx)
        except OutxFormatError:
            pass
    csv_path = entry.folder / "result.csv"
    return _read_csv(csv_path) if csv_path.exists() else None


def channel_names(files: list[ChannelFile]) -> list[str]:
    """The union of channel names across the chosen cases, in first-seen order."""
    seen: dict[str, None] = {}
    for f in files:
        for name in f.names:
            seen.setdefault(name)
    return list(seen)


# --- the figure ----------------------------------------------------------------------------------------------------


def build_figure(selected: list[tuple[CaseEntry, ChannelFile]], channels: list[str]) -> go.Figure:
    """One plot row per channel (shared time axis), one colour per case, overlaid.

    Zoom, pan, hover read-outs and hiding a case by clicking its legend entry come
    from plotly. The event window of each case is shaded in its colour.
    """
    rows = max(1, len(channels))
    titles = [f"{c} (pu)" if c in ("V", "P", "Q", "F") else c for c in channels]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=min(0.08, 0.4 / rows),
                        subplot_titles=titles or None)
    fig.update_annotations(font={"size": 12, "color": t.TEXT}, xanchor="left", x=0)
    for i, (entry, data) in enumerate(selected):
        color = PLOT_COLORS[i % len(PLOT_COLORS)]
        dash = DASHES[(i // len(PLOT_COLORS)) % len(DASHES)] if len(selected) > 2 else ("solid", "dash")[i % 2]
        name = f"{entry.label} · {entry.verdict}" if entry.verdict else entry.label
        for r, channel in enumerate(channels, start=1):
            if channel not in data.channels:
                continue
            fig.add_trace(go.Scattergl(x=data.time, y=data.channels[channel], mode="lines", name=name,
                                       legendgroup=entry.key, showlegend=(r == 1),
                                       line={"color": color, "width": 1.8, "dash": dash},
                                       hovertemplate="%{y:.5g}<br>t = %{x:.4f} s<extra>" + entry.label + "</extra>"),
                          row=r, col=1)
        if entry.event and i == 0:
            fig.add_vrect(x0=entry.event[0], x1=entry.event[1], fillcolor=t.HAIRLINE, opacity=0.9, line_width=0,
                          layer="below", row="all", col=1)
    if selected and selected[0][0].event:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name="Disturbance",
                                 marker={"symbol": "square", "size": 12, "color": t.HAIRLINE}), row=1, col=1)
    fig.update_xaxes(title_text="time (s)", row=rows, col=1)
    fig.update_xaxes(gridcolor=t.HAIRLINE, linecolor=t.CARD_BORDER, zeroline=False)
    fig.update_yaxes(gridcolor=t.HAIRLINE, linecolor=t.CARD_BORDER, zeroline=False)
    fig.update_layout(height=max(380, 230 * rows), template="plotly_white", hovermode="x unified",
                      font={"family": t.CSS_FONT_SANS, "size": 11, "color": t.TEXT},
                      margin={"l": 56, "r": 16, "t": 64 if channels else 20, "b": 44},
                      legend={"orientation": "h", "x": 0, "xanchor": "left", "y": 1.0, "yanchor": "bottom",
                              "font": {"size": 11}})
    if channels:
        fig.update_layout(legend={"y": 1.0 + 40 / max(380, 230 * rows)})
    if not channels:
        fig.add_annotation(text="Choose at least one channel", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
    return fig
