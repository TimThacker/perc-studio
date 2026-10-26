"""The black-box validation report: one self-contained HTML file (plotly.js
embedded, so it opens offline), the JSON document behind it, and a
reproducibility bundle.

Every number in the report comes from the validation document that
`protocol.Validation.run` produced. Nothing is computed here except what is
needed to draw it.
"""

from __future__ import annotations

import csv
import html
import json
import math
import zipfile
from pathlib import Path

import plotly.graph_objects as go

from app.config import CURENT_GREEN, ENGINEERING_TOOL_NOTICE, TVA_CHARCOAL

from . import supervisor
from .runs import summary_warnings

GOOD, BAD, EDGE_C, GREY = "#2e7d32", "#c62828", "#ef6c00", "#78909c"
VERDICT_COLORS = {"meets": GOOD, "fails": BAD, "at the edge": EDGE_C, "beyond tested range": GREY,
                  "not solvable": GREY, "no requirement": GREY}
PRESET_COLORS = ["#1565c0", "#6a1b9a", "#00838f", "#ad1457", "#4e342e", "#283593", "#558b2f", "#f9a825"]


def _e(x) -> str:
    return html.escape(str(x))


def _fmt_s(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float) and math.isinf(x):
        return "always"
    return f"{x:.3g} s"


def _badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, GREY)
    return (f'<span style="background:{color};color:white;border-radius:10px;padding:1px 9px;'
            f'font-size:0.85em;white-space:nowrap">{_e(verdict)}</span>')


def _table(headers, rows) -> str:
    head = "<tr>" + "".join(f"<th>{_e(h)}</th>" for h in headers) + "</tr>" if headers else ""
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table>{head}{body}</table>"


class _Figures:
    """Embeds plotly.js with the first figure only."""

    def __init__(self):
        self.first = True
        self.n = 0

    def html(self, fig: go.Figure) -> str:
        self.n += 1
        out = fig.to_html(include_plotlyjs=self.first, full_html=False, div_id=f"bbv-fig-{self.n}",
                          config={"displaylogo": False})
        self.first = False
        return out


def load_trace(cache_root: Path, key: str) -> dict[str, list[float]] | None:
    path = Path(cache_root) / "cache" / key / "result.csv"
    if not path.exists():
        return None
    cols: dict[str, list[float]] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            for k, v in row.items():
                cols.setdefault(k, []).append(float(v) if v else float("nan"))
    return cols


# --- figures -------------------------------------------------------------------------------------------------------


def boundary_figure(doc: dict, fam_id: str) -> go.Figure | None:
    fam = doc["families"].get(fam_id)
    if not fam or "searches" not in fam:
        return None
    unit = fam["outer_unit"]
    fig = go.Figure()
    ok_x, ok_y, bad_x, bad_y, fail_x, fail_y = [], [], [], [], [], []
    for p in doc["points"]:
        if p["family"] != fam_id:
            continue
        cls = p["outcome"]["cls"]
        if cls in ("numerical_failure", "unstable"):
            fail_x.append(p["inner"])
            fail_y.append(p["outer"])
        elif p["outcome"]["cls"] in ("ride_through", "momentary_cessation"):
            ok_x.append(p["inner"])
            ok_y.append(p["outer"])
        else:
            bad_x.append(p["inner"])
            bad_y.append(p["outer"])
    fig.add_trace(go.Scatter(x=ok_x, y=ok_y, mode="markers", name="rode through",
                             marker={"color": GOOD, "size": 7, "symbol": "circle"}))
    fig.add_trace(go.Scatter(x=bad_x, y=bad_y, mode="markers", name="tripped",
                             marker={"color": BAD, "size": 8, "symbol": "x"}))
    if fail_x:
        fig.add_trace(go.Scatter(x=fail_x, y=fail_y, mode="markers", name="failed / unstable",
                                 marker={"color": "black", "size": 8, "symbol": "diamond-open"}))
    bx, by = [], []
    for s in sorted(fam["searches"], key=lambda s: s["tag"]):
        if s["transitions"]:
            below, above, _ = s["transitions"][0]
            bx.append(math.sqrt(below * above))
            by.append(s["tag"])
    if bx:
        fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", name="measured boundary",
                                 line={"color": "black", "width": 2, "dash": "dot"}))
    hi = fam["inner"]["hi"]
    for i, (pid, comp) in enumerate(doc["comparison"].items()):
        rows = comp["families"].get(fam_id, {}).get("points", [])
        xs, ys = [], []
        for r in sorted(rows, key=lambda r: r["value"]):
            req = hi * 1.5 if r["required_forever"] else r["required_s"]
            if req and req > 0:
                xs.append(min(req, hi * 1.5))
                ys.append(r["value"])
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=f"{comp['label']} requires",
                                     line={"color": PRESET_COLORS[i % len(PRESET_COLORS)], "width": 1.5,
                                           "shape": "hv"}, marker={"size": 4}))
    fig.update_layout(height=430, margin={"l": 60, "r": 20, "t": 30, "b": 50}, template="plotly_white",
                      legend={"orientation": "h", "y": -0.2},
                      xaxis={"type": "log", "title": f"{fam['inner']['name']} ({fam['inner']['unit']})"},
                      yaxis={"title": f"{fam['outer_name']} ({unit})" if unit else fam["outer_name"]})
    return fig


def trace_figure(cache_root: Path, cases: list[tuple[str, str]], title: str) -> go.Figure | None:
    """V, f and P against time for a few cases: (key, label) pairs."""
    from plotly.subplots import make_subplots

    traces = [(load_trace(cache_root, key), label) for key, label in cases]
    traces = [(t, label) for t, label in traces if t]
    if not traces:
        return None
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=("Bus voltage (pu) / frequency (Hz, right)", "Load P (pu of pre-event)"),
                        specs=[[{"secondary_y": True}], [{}]])
    for i, (t, label) in enumerate(traces):
        color = PRESET_COLORS[i % len(PRESET_COLORS)]
        p0 = t["P"][0] or 1.0
        fig.add_trace(go.Scatter(x=t["time"], y=t["V"], name=f"V: {label}", line={"color": color}), row=1, col=1)
        if max(t["F_HZ"]) - min(t["F_HZ"]) > 0.01:
            fig.add_trace(go.Scatter(x=t["time"], y=t["F_HZ"], name=f"f: {label}",
                                     line={"color": color, "dash": "dot"}), row=1, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(x=t["time"], y=[p / p0 for p in t["P"]], name=f"P: {label}",
                                 line={"color": color}), row=2, col=1)
    fig.update_layout(height=520, title=title, template="plotly_white", margin={"l": 60, "r": 60, "t": 60, "b": 40},
                      legend={"orientation": "h", "y": -0.12})
    fig.update_xaxes(title_text="time (s)", row=2, col=1)
    return fig


# --- sections ------------------------------------------------------------------------------------------------------


def _summary(doc) -> str:
    parts = []
    if doc.get("stopped"):
        parts.append(f'<div class="stop"><strong>The validation stopped:</strong> {_e(doc["stopped"])}</div>')
    rows = [[_e(c["label"]), _badge(c["overall"])] +
            [_badge(c["families"][k]["overall"]) if k in c["families"] else "-"
             for k in ("undervoltage", "overvoltage", "frequency")]
            for c in doc["comparison"].values()]
    if rows:
        parts.append(_table(["Preset", "Overall", "Undervoltage", "Overvoltage", "Frequency"], rows))
    elif not doc.get("stopped"):
        parts.append("<p>No presets were selected, so the report characterizes the model without comparing it.</p>")
    warnings = list(_warnings(doc))
    if warnings:
        parts.append("<ul class='warn'>" + "".join(f"<li>{_e(w)}</li>" for w in warnings) + "</ul>")
    return "\n".join(parts)


def _warnings(doc):
    yield from summary_warnings(doc)


def _environment(doc) -> str:
    env = doc["environment"]
    v = env.get("psse") or {}
    psse = f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}" if v else "-"
    sel = env["selection"]
    st = doc.get("stats", {})
    rows = [["PSS/E", _e(psse)], ["Install folder", _e(sel["install_dir"])],
            ["Python", _e(f"{env.get('python') or '-'} ({sel['python_exe']}, {sel['pspy_folder']})")],
            ["App version", _e(doc["app_version"])], ["Test level", _e(doc["setup"]["level_title"])],
            ["Time step used", _e(f"{st.get('delt', 0):.6g} s")],
            ["Cases", _e(f"{st.get('cases_run', 0)} run, {st.get('cases_cached', 0)} reused from cache")],
            ["Wall time", _e(f"{st.get('wall_seconds', 0):.0f} s")]]
    return _table(None, rows)


def _intake(doc) -> str:
    st = doc["stages"].get("intake", {})
    if not st:
        return ""
    out = [f"<p><strong>Load under test:</strong> {_e(st.get('target', '-'))}</p>"]
    if st.get("placed_records"):
        out.append("<p>Records as run on the rig (<code>{BUS}</code> is the rig bus; CON values unchanged):</p>")
        out.append("<pre>" + _e("\n".join(st["placed_records"])) + "</pre>")
    for n in st.get("notes", []):
        out.append(f"<p class='meta'>{_e(n)}</p>")
    for f in st.get("flags", []):
        out.append(f"<p class='flag'>{_e(f)}</p>")
    if st.get("dlls"):
        rows = [[_e(Path(d["path"]).name), _e(d["machine"] or "-"), f"<code>{_e(d['sha256'][:16])}...</code>",
                 _e(", ".join(d["exports"][:8]) + (" ..." if len(d["exports"]) > 8 else "")),
                 _e("; ".join(d["problems"] + d["notes"]) or "ok")] for d in st["dlls"]]
        out.append(_table(["DLL", "Machine", "SHA-256", "Exports", "Checks"], rows))
    return "\n".join(out)


def _initialization(doc) -> str:
    st = doc["stages"].get("initialization")
    if not st:
        return ""
    out = []
    if st.get("runs"):
        rows = [[_e(f"{r['v0']:g} pu"), _e(r.get("status")), _e(r.get("reason", "-")),
                 _e(f"{r['drift_p']:.2%}" if "drift_p" in r else "-")] for r in st["runs"]]
        out.append(_table(["Initial voltage", "Run", "Result", "P drift"], rows))
    fail = st.get("failure")
    if fail:
        out.append(f"<p class='flag'>First run: {_e(fail['status_text'])}"
                   f"{' - ' + _e(fail['error']) if fail.get('error') else ''}</p>")
        for f in fail.get("findings", []):
            out.append(f"<p><strong>{_e(f['code'])}</strong>: {_e(f['meaning'])}<br><code>{_e(f['line'])}</code></p>")
        if fail.get("suspect_states"):
            out.append("<pre>" + _e("\n".join(fail["suspect_states"])) + "</pre>")
        if fail.get("log_tail"):
            out.append("<details><summary>PSS/E log (end)</summary><pre>" + _e(fail["log_tail"]) + "</pre></details>")
    return "\n".join(out)


def _time_step(doc) -> str:
    st = doc["stages"].get("time_step")
    if not st:
        return ""
    out = [(f"<p>Chosen time step: <strong>{st['chosen']:.6g} s</strong>"
            f"{' (forced by the user)' if doc['setup'].get('forced_delt') else ''}. "
            f"The model settles {_fmt_s(st.get('settle_s'))} after a mild sag, so a load counts as having ridden "
            f"through when its power is back within {st['prompt_window_s']:.3g} s of the bus returning to normal.</p>")]
    for c in st["comparisons"]:
        rows = [[_e(r["reference"]), _e(r["coarse"]), _e(r["fine"]), _e("-" if r["rms"] is None else f"{r['rms']:.4f}"),
                 _badge("meets" if r["match"] else "fails")] for r in c["rows"]]
        out.append(f"<p>{c['coarse']:.6g} s against {c['fine']:.6g} s:</p>")
        out.append(_table(["Reference", f"{c['coarse']:.6g} s", f"{c['fine']:.6g} s", "RMS of P difference", "Match"],
                          rows))
    return "\n".join(out)


def _family_section(doc, fam_id, figs: _Figures, cache_root) -> str:
    fam = doc["families"].get(fam_id)
    if not fam:
        return ""
    out = [f"<h3>{_e(fam['title'])}</h3>"]
    if fam.get("description"):
        out.append(f"<p>{_e(fam['description'])}</p>")
    if fam.get("skipped"):
        out.append(f"<p class='meta'>Not run: {_e(fam['skipped'])}.</p>")
        return "\n".join(out)
    if fam["kind"] in ("undervoltage", "overvoltage", "frequency"):
        fig = boundary_figure(doc, fam_id)
        if fig:
            out.append(figs.html(fig))
    unit = fam["inner"]["unit"]
    rows = []
    for s in sorted(fam["searches"], key=lambda s: s["tag"]):
        if s["transitions"]:
            desc = "; ".join(f"{'rides through' if g else 'trips'} up to {b:.4g} {unit}, "
                             f"{'trips' if g else 'rides through'} from {a:.4g} {unit}" for b, a, g in s["transitions"])
        else:
            desc = ("rides through" if s["all_good"] else "trips") + \
                f" everywhere from {fam['inner']['lo']:.3g} to {fam['inner']['hi']:.3g} {unit}"
        if fam["kind"] == "recovery":
            desc = desc.replace("rides through", "reconnects").replace("trips", "stays off")
        rows.append([_e(f"{s['tag']:g} {fam['outer_unit']}" if fam["kind"] != "recovery" else "-"), _e(desc),
                     _e(len(s["points"])), _e("yes" if s["monotonic"] else "NO")])
    out.append(_table([fam["outer_name"].capitalize(), "Measured", "Runs", "Monotonic"], rows))
    if fam["kind"] == "recovery" and fam.get("reconnections"):
        t = fam["trip_event"]
        out.append(f"<p>The trip: {t['depth_pu']:g} pu for {t['duration_s']:.3g} s, then the voltage held at each "
                   f"level for {fam.get('observe_s', 0):.0f} s.</p>")
        rr = [[_e(f"{r['recovery_pu']:.3f} pu"), _e("yes" if r["reconnected"] else "no"),
               _e(_fmt_s(r.get("delay_s"))), _e(_fmt_s(r.get("ramp_s"))),
               _e(f"{r['final_ratio']:.0%}" if r.get("final_ratio") is not None else "-")]
              for r in fam["reconnections"]]
        out.append(_table(["Recovery voltage", "Reconnected", "Delay", "Ramp", "Final P"], rr))
        ok = [r for r in fam["reconnections"] if r["reconnected"]]
        if ok:
            pick = min(ok, key=lambda r: abs(r["recovery_pu"] - 1.0))
            fig = trace_figure(cache_root, [(pick["key"], f"recover to {pick['recovery_pu']:.3g} pu")],
                               "A trip and reconnection")
            if fig:
                out.append(figs.html(fig))
    if fam["kind"] == "undervoltage":
        pair = _boundary_pair(doc, fam_id)
        if pair:
            fig = trace_figure(cache_root, pair, "Either side of the boundary")
            if fig:
                out.append(figs.html(fig))
    return "\n".join(out)


def _boundary_pair(doc, fam_id):
    fam = doc["families"][fam_id]
    for s in sorted(fam["searches"], key=lambda s: s["tag"]):
        if s["transitions"]:
            below, above, _ = s["transitions"][0]
            keys = {(p["inner"]): p for p in doc["points"] if p["family"] == fam_id and p["outer"] == s["tag"]}
            if below in keys and above in keys:
                return [(keys[below]["key"], keys[below]["event"] + " - " + keys[below]["outcome"]["label"]),
                        (keys[above]["key"], keys[above]["event"] + " - " + keys[above]["outcome"]["label"])]
    return None


def _comparison(doc) -> str:
    out = []
    for comp in doc["comparison"].values():
        out.append(f"<h3>{_e(comp['label'])} {_badge(comp['overall'])}</h3>")
        for kind, fam in comp["families"].items():
            if fam.get("note"):
                out.append(f"<p class='meta'>{_e(kind.capitalize())}: {_e(fam['note'])}</p>")
                continue
            unit = {"undervoltage": "pu", "overvoltage": "pu", "frequency": "Hz"}[kind]
            rows = [[_e(f"{p['value']:g} {unit}"), _e("forever" if p["required_forever"] else _fmt_s(p["required_s"])),
                     _e(_fmt_s(p["longest_ok_s"])), _e(_fmt_s(p["shortest_trip_s"])), _badge(p["verdict"])]
                    for p in fam["points"] if p["verdict"] != "no requirement"]
            if rows:
                out.append(f"<p><strong>{_e(kind.capitalize())}</strong></p>")
                out.append(_table(["Level", "Must ride through", "Longest seen riding through", "Shortest seen tripping",
                                   "Verdict"], rows))
    return "\n".join(out)


def _robustness(doc) -> str:
    st = doc["stages"].get("robustness")
    if not st:
        return ""
    out = []
    for r in st.get("repeatability", []):
        out.append(f"<p>Same case twice, separate processes ({_e(r['case'])}): "
                   f"{_badge('meets' if r['match'] else 'fails')}</p>")
    if st.get("half_step"):
        rows = [[_e(r["family"]), _e(r["case"]), _e(r["outcome"]), _e(r["half_step_outcome"]),
                 _badge("meets" if r["match"] else "fails")] for r in st["half_step"]]
        out.append("<p>Boundary cases again at half the time step:</p>")
        out.append(_table(["Family", "Case", "Outcome", "At half step", "Same"], rows))
    cad = st.get("cadence", {})
    if cad.get("skipped"):
        out.append(f"<p class='meta'>run() cadence: not checked ({_e(cad['skipped'])}).</p>")
    elif cad:
        a, b = cad["event_to_event"], cad["every_step"]
        out.append(f"<p>run() called every time step against event to event ({_e(cad['case'])}): "
                   f"{_badge('meets' if cad['match'] else 'fails')} - reconnect delay {_fmt_s(a.get('delay_s'))} "
                   f"against {_fmt_s(b.get('delay_s'))}, ramp {_fmt_s(a.get('ramp_s'))} against "
                   f"{_fmt_s(b.get('ramp_s'))}.</p>")
    return "\n".join(out)


def _diagnosis(doc) -> str:
    if not doc["diagnosis"]:
        return "<p>No automatic actions were needed.</p>"
    return _table(["Action", "Reason"], [[_e(d["action"]), _e(d["reason"])] for d in doc["diagnosis"]])


METHOD = """
<p><strong>The model is a black box.</strong> Its records run on a one-bus PSS/E case exactly as written: only the
bus number (or the rig load's owner, zone or area) changes so the records attach to the rig's load. No CON is ever
changed. The rig's source is PSS/E's playback model PLBVF1, so the bus voltage and frequency follow each test's
profile exactly; the load cannot pull the voltage around.</p>
<p><strong>Rode through or tripped.</strong> Read from the load's own power: it rode through if P is back within
90% of its pre-event value within the prompt window after the bus returns to normal (the window is twice the
model's own settling time after a mild sag). Otherwise it tripped; the reconnect delay, ramp and final level are
read from when P climbs back. A fall below 10% while the voltage stays at or above 0.5 pu, followed by a prompt
recovery, is momentary cessation.</p>
<p><strong>Boundaries.</strong> For each level, the duration is searched by bisection on a log scale until the
bracket is within the level's tolerance. Each settled region is then sampled again at a few points (3 at Quick,
4 at Standard, 8 at Full); if the outcome flips more than once, the axis is scanned densely and every flip is
bracketed (marked "not monotonic"). A trip window narrower than that sampling can still be missed.</p>
<p><strong>Verdicts</strong> compare the load with each preset <em>as encoded in this app</em>: "meets" when it was
seen riding through at least the required duration, "fails" when it was seen tripping on a shorter one, "at the
edge" when the requirement falls inside the search bracket, "not solvable" when a case at that value failed to
solve in PSS/E (an exact 0 pu bus, for example) so there is no boundary, and "beyond tested range" when the requirement is longer
than the longest disturbance run. Tripping where a preset permits it is never a failure. This is not a compliance
determination.</p>
"""


def _tolerance(doc, figs: _Figures, overlay_preset_id: str | None) -> str:
    """The tolerance curve: the model's measured ride-through region, with a standard laid over it only when the
    user chose one."""
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    from .tolerance import (
        caption,
        frequency_note,
        measured_boundary,
        shortfalls,
        tolerance_figure,
    )

    preset = RIDE_THROUGH_PRESETS.get(overlay_preset_id) if overlay_preset_id else None
    out = [("<p>How long the model rides through each voltage and frequency, from the measured boundaries "
            "(stepped; each band uses the boundary measured at its end farther from nominal).</p>")]
    for quantity in ("voltage", "frequency"):
        fig = tolerance_figure(doc, quantity, preset)
        fig.update_layout(height=360)
        out.append(f"<h3>{quantity.capitalize()}</h3>" + figs.html(fig))
    if preset is not None:
        falls = [f for k in ("undervoltage", "overvoltage", "frequency")
                 for f in shortfalls(measured_boundary(doc, k), preset)]
        out.append(f"<p>{_e(caption(doc, preset, falls))}</p>")
        if (note := frequency_note(preset)) is not None:
            out.append(f"<p class='meta'>{_e(note)}</p>")
    return "\n".join(out)


def build_report_html(doc: dict, cache_root: Path, *, overlay_preset_id: str | None = None) -> str:
    figs = _Figures()
    fam_sections = "\n".join(_family_section(doc, f, figs, cache_root) for f in doc["families"])
    title = "Black-box validation"
    target = doc["stages"].get("intake", {}).get("target", "")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>{_e(title)} - {_e(target)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; color: #222; line-height: 1.5; }}
  .wrap {{ margin: 0 40px 40px 40px; }}
  .head {{ background: {CURENT_GREEN}; color: white; padding: 16px 40px; margin-bottom: 20px; }}
  .head h1 {{ margin: 0; font-size: 1.4em; }} .head div {{ color: #dff0df; font-size: 0.9em; }}
  h2 {{ margin-top: 32px; color: {CURENT_GREEN}; border-bottom: 2px solid {CURENT_GREEN}; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0 18px 0; font-size: 0.92em; }}
  th, td {{ border: 1px solid #ddd; padding: 5px 9px; text-align: left; vertical-align: top; }}
  th {{ background: {CURENT_GREEN}; color: white; }}
  pre {{ background: #f7f7f7; border: 1px solid #ddd; padding: 10px; border-radius: 6px; overflow-x: auto; }}
  .meta {{ color: {TVA_CHARCOAL}; }} .flag {{ color: #8a4b00; }}
  .stop {{ background: #fdecea; border: 1px solid #f5c2c0; border-radius: 6px; padding: 10px 14px; }}
  ul.warn li {{ color: #8a4b00; }}
  .notice {{ margin-top: 24px; background: #eef4fb; border: 1px solid #c9d9ea; border-radius: 8px; padding: 12px 16px;
             font-size: 0.85em; }}
</style></head><body>
<div class="head"><h1>{_e(title)}</h1><div>{_e(target)} &middot; {_e(doc['setup'].get('dyr_name') or '')}
 &middot; generated {_e(doc['generated'])}</div></div>
<div class="wrap">
<h2>Summary</h2>
{_summary(doc)}
<h2>Environment</h2>
{_environment(doc)}
<h2>The model</h2>
{_intake(doc)}
<h2>Initialization</h2>
{_initialization(doc)}
<h2>Time step</h2>
{_time_step(doc)}
<h2>Characterization</h2>
{fam_sections}
<h2>Comparison with presets</h2>
{_comparison(doc) or "<p>No presets selected.</p>"}
<h2>Tolerance curve</h2>
{_tolerance(doc, figs, overlay_preset_id)}
<h2>Robustness of the results</h2>
{_robustness(doc)}
<h2>Automatic actions</h2>
{_diagnosis(doc)}
<h2>Method</h2>
{METHOD}
<div class="notice"><strong>Engineering tool notice:</strong> {ENGINEERING_TOOL_NOTICE}</div>
</div></body></html>
"""


RERUN = r'''"""Re-run every PSS/E case in this bundle and compare with the stored results.

    <pssepython> rerun.py <PSS/E install folder> <PSSPYxx> [out folder]

Needs only the Python that your PSS/E install supports, and psse_worker.py and outx.py from this bundle.
"""
import csv, json, os, shutil, subprocess, sys

def load(path):
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    return [(float(r["time"]), float(r["P"] or "nan")) for r in rows]

def main():
    root, pspy = sys.argv[1], sys.argv[2]
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.abspath(sys.argv[3] if len(sys.argv) > 3 else os.path.join(here, "rerun"))
    worse = 0
    cases = sorted(os.listdir(os.path.join(here, "cases")))
    for key in cases:
        src = os.path.join(here, "cases", key)
        with open(os.path.join(src, "job.json")) as fh:
            job = json.load(fh)
        dst = os.path.join(out, key)
        os.makedirs(dst, exist_ok=True)
        job.update(psse_root=root, pspy_folder=pspy, out_dir=dst)
        job_path = os.path.join(dst, "job.json")
        with open(job_path, "w") as fh:
            json.dump(job, fh)
        subprocess.call([sys.executable, "-I", os.path.join(here, "psse_worker.py"), "run", job_path])
        old, new = os.path.join(src, "result.csv"), os.path.join(dst, "result.csv")
        if not (os.path.exists(old) and os.path.exists(new)):
            print(key, "no trace to compare"); continue
        a, b = load(old), load(new)
        diff = max(abs(pa - pb) for (_, pa), (_, pb) in zip(a, b)) if len(a) == len(b) else float("inf")
        worse += diff > 1e-4
        print(key, "same" if diff <= 1e-4 else "DIFFERENT (max |dP| = %g)" % diff)
    print("%d of %d cases differ" % (worse, len(cases)))

if __name__ == "__main__":
    main()
'''


def write_outputs(doc: dict, cache_root: Path, out_dir: Path, *, dyr_text: str = "", include_dlls: bool = False,
                  overlay_preset_id: str | None = None) -> dict[str, Path]:
    """report.html, validation.json and bundle.zip in `out_dir`. The report's tolerance curve carries a standard
    only when `overlay_preset_id` names one."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"html": out_dir / "report.html", "json": out_dir / "validation.json", "bundle": out_dir / "bundle.zip"}
    paths["html"].write_text(build_report_html(doc, cache_root, overlay_preset_id=overlay_preset_id), encoding="utf-8")
    paths["json"].write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    keys = {p["key"] for p in doc["points"]}
    for st in ("initialization",):
        keys.update(r["key"] for r in doc["stages"].get(st, {}).get("runs", []) if r.get("key"))
    with zipfile.ZipFile(paths["bundle"], "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("validation.json", json.dumps(doc, indent=1, default=str))
        z.write(paths["html"], "report.html")
        if dyr_text:
            z.writestr(doc["setup"].get("dyr_name") or "model.dyr", dyr_text)
        z.write(supervisor.worker_source(), "psse_worker.py")
        z.write(supervisor.reader_source(), supervisor.READER_NAME)  # the worker imports it
        z.writestr("rerun.py", RERUN)
        for key in sorted(keys):
            case = Path(cache_root) / "cache" / key
            for name in ("job.json", "result.csv", "meta.json", "psse.log", "case.outx"):  # case.outx: every channel, for the explorer
                if (case / name).exists():
                    z.write(case / name, f"cases/{key}/{name}")
        if include_dlls:
            for dll in doc["setup"].get("dlls", []):
                if Path(dll).exists():
                    z.write(dll, f"dlls/{Path(dll).name}")
    return paths
