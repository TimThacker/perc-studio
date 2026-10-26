"""Black-box validation, end to end: the stages of
docs/black_box/BLACK_BOX_VALIDATION.md §4.1, run against one load target.

Stage 0  intake: scan the .dyr, place the target on the rig, inspect the DLLs.
Stage 1  initialization: flat runs with no disturbance (at 1.0, 0.95, 1.05 pu).
Stage 2  time step: reference disturbances at DELT, DELT/2, DELT/4; keep the
         largest step whose results match the next finer one. Also measures the
         model's own settling time, which sets the classifier's prompt window.
Stage 3  characterization: the probe families' boundary searches.
Stage 4  robustness: the same case twice, boundary points at half the step,
         and run() every step against event to event.

Every automatic action (a retry, a smaller step) comes from a fixed list, is
recorded under "diagnosis", and never changes a CON. The result is one
JSON-serializable document; `report.py` renders it.
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.build_info import __version__
from presets.ridethrough import RIDE_THROUGH_PRESETS

from . import classify as cl
from .dll_inspect import inspect_dll
from .families import EVENT_START, LEVELS, NOMINAL_HZ, Event, Family, build_families
from .intake import load_targets, other_records_note, place_on_rig, scan_dyr
from .logparse import STATUS_TEXT, parse_log, suspect_states
from .psse_install import PsseSelection
from .scoring import compare_family, overall
from .search import BoundarySearch, run_searches
from .supervisor import DEFAULT_DELT, DEFAULT_FREQ_FILTER, CaseResult, CaseSpec, Session

FLAT_RUN_S = 10.0
RECOVERY_PROBE_PU = (1.0, 1.02, 0.97, 1.04)
DRIFT_WARN = 0.01
DRIFT_STOP = 0.10


@dataclass
class ValidationSetup:
    selection: PsseSelection
    dyr_text: str
    target_index: int = 0
    dlls: tuple[str, ...] = ()
    preset_ids: tuple[str, ...] = ()
    level: str = "standard"
    delt: float | None = None  # forced time step; None lets Stage 2 choose
    freq_filter: float = DEFAULT_FREQ_FILTER
    workers: int = 4
    p_mw: float = 100.0
    q_mvar: float = 20.0
    map_own_bus_icons: bool = True
    dyr_name: str = ""


class Stop(Exception):
    """The validation cannot continue; the document says why."""


@dataclass
class _Point:
    family: str
    outer: float
    inner: float
    event: Event
    result: CaseResult
    outcome: cl.Outcome

    def to_dict(self) -> dict:
        return {"family": self.family, "outer": self.outer, "inner": self.inner, "key": self.result.key,
                "status": self.result.status, "event": self.event.label, "event_start": self.event.start,
                "event_end": self.event.end, "outcome": self.outcome.to_dict()}


@dataclass
class Validation:
    setup: ValidationSetup
    work_root: Path
    on_event: Callable[[dict], None] | None = None
    env: dict | None = None
    doc: dict = field(default_factory=dict)

    def __post_init__(self):
        self.work_root = Path(self.work_root)
        self.session = Session(self.setup.selection, self.work_root, workers=self.setup.workers, env=self.env,
                               on_event=self._relay)
        self.delt = self.setup.delt or DEFAULT_DELT
        self.prompt_window = cl.MIN_PROMPT_WINDOW_S
        self.observe_s = 2.0
        self.points: list[_Point] = []

    # --- plumbing -----------------------------------------------------------------------------------------------

    def _relay(self, event: dict):
        if self.on_event:
            self.on_event(event)

    def _stage(self, stage: str, message: str):
        self._relay({"kind": "stage", "stage": stage, "message": message})

    def cancel(self):
        self.session.cancel()

    def _action(self, what: str, why: str):
        self.doc["diagnosis"].append({"action": what, "reason": why})
        self._relay({"kind": "diagnosis", "action": what, "reason": why})

    def _spec(self, event: Event, *, delt: float | None = None, every_step: bool = False, repeat: int = 0,
              v0: float = 1.0, label: str = "") -> CaseSpec:
        rig = dict(self.placement.rig, p_mw=self.setup.p_mw, q_mvar=self.setup.q_mvar, v0=v0)
        return CaseSpec(records=self.placement.records, segments=event.segments, t_end=event.t_end,
                        dlls=tuple(self.setup.dlls), rig=tuple(sorted(rig.items())), delt=delt or self.delt,
                        freq_filter=self.setup.freq_filter, run_every_step=every_step,
                        expect_ncon=self.placement.expect_ncon, repeat=repeat, label=label or event.label)

    def _classify(self, result: CaseResult, event: Event) -> cl.Outcome:
        return cl.classify(result, event.start, event.end, prompt_window_s=self.prompt_window)

    # --- run ----------------------------------------------------------------------------------------------------

    def run(self) -> dict:
        started = time.time()
        presets = [RIDE_THROUGH_PRESETS[p] for p in self.setup.preset_ids]
        self.doc = {
            "schema": 1, "app_version": __version__, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "setup": {"level": self.setup.level, "level_title": LEVELS[self.setup.level].title,
                      "presets": [{"id": p.id, "label": p.label} for p in presets], "dyr_name": self.setup.dyr_name,
                      "dlls": list(self.setup.dlls), "p_mw": self.setup.p_mw, "q_mvar": self.setup.q_mvar,
                      "forced_delt": self.setup.delt},
            "environment": {"selection": self.setup.selection.to_dict()},
            "stages": {}, "families": {}, "comparison": {}, "diagnosis": [], "points": [], "stopped": None,
        }
        try:
            self._intake()
            self._initialization()
            self._time_step()
            self._characterize(presets)
            self._robustness()
            self._compare(presets)
        except Stop as stop:
            self.doc["stopped"] = str(stop)
        if self.session.cancelled and not self.doc["stopped"]:
            self.doc["stopped"] = "cancelled by the user"
        self.doc["points"] = [p.to_dict() for p in self.points]
        self.doc["stats"] = {"cases_run": self.session.cases_run, "cases_cached": self.session.cases_cached,
                             "wall_seconds": round(time.time() - started, 1), "delt": self.delt,
                             "prompt_window_s": self.prompt_window, "workers": self.session.workers}
        self._stage("done", self.doc["stopped"] or "finished")
        return self.doc

    # --- Stage 0 ------------------------------------------------------------------------------------------------

    def _intake(self):
        self._stage("intake", "reading the .dyr file and the DLLs")
        records = scan_dyr(self.setup.dyr_text)
        targets = load_targets(records)
        stage = {"records": [r.label for r in records], "targets": [t.label for t in targets]}
        self.doc["stages"]["intake"] = stage
        if not targets:
            raise Stop("the .dyr file has no load-model record to test")
        if not 0 <= self.setup.target_index < len(targets):
            raise Stop(f"there is no load #{self.setup.target_index + 1} in the file (it has {len(targets)})")
        target = targets[self.setup.target_index]
        self.placement = place_on_rig(records, target, map_own_bus_icons=self.setup.map_own_bus_icons)
        models = tuple(m for m in target.models)
        dll_reports = [inspect_dll(d, psse_root=self.setup.selection.install_dir, models=models)
                       for d in self.setup.dlls]
        stage.update(target=target.label, placed_records=list(self.placement.records),
                     notes=list(self.placement.notes) + other_records_note(records, target),
                     flags=list(self.placement.flags), dlls=[r.to_dict() for r in dll_reports])
        fatal = [p for r in dll_reports for p in r.problems if "built for" in p or "not a Windows DLL" in p
                 or "cannot read" in p]
        if fatal:
            raise Stop("; ".join(fatal))

    # --- Stage 1 ------------------------------------------------------------------------------------------------

    def _flat_event(self, v0: float) -> Event:
        return Event(((0.0, v0, NOMINAL_HZ),), FLAT_RUN_S, FLAT_RUN_S, FLAT_RUN_S, f"no disturbance at {v0:g} pu")

    def _initialization(self):
        self._stage("initialization", "flat runs with no disturbance")
        stage = self.doc["stages"]["initialization"] = {"runs": []}
        base = self._run_with_playbook(self._flat_event(1.0), stage, v0=1.0)
        self.doc["environment"]["psse"] = base.meta.get("version")
        self.doc["environment"]["python"] = base.meta.get("python")
        others = self.session.run_many([self._spec(self._flat_event(v), v0=v) for v in (0.95, 1.05)])
        for v0, res in ((1.0, base), (0.95, others[0]), (1.05, others[1])):
            found = cl.flat_run_findings(res)
            stage["runs"].append({"v0": v0, "key": res.key, "status": res.status, **found})
        first = stage["runs"][0]
        if not first.get("ok") and not first.get("tripped") and first.get("reason", "").startswith("the load draws no power"):
            raise Stop("the load draws no power with no disturbance, so there is nothing to characterize. Check that "
                       "every DLL the model needs was added and matches this PSS/E version.")
        if first.get("tripped"):
            raise Stop("the load trips with no disturbance at 1.0 pu, so there is nothing to characterize")
        drift = max(first.get("drift_p", 0.0), first.get("drift_q", 0.0))
        if drift > DRIFT_STOP:
            raise Stop(f"the load drifts {drift:.0%} with no disturbance; it does not initialize to the power flow")
        if drift > DRIFT_WARN:
            stage["warning"] = f"the load drifts {drift:.1%} with no disturbance; results carry that drift"

    def _run_with_playbook(self, event: Event, stage: dict, *, v0: float = 1.0) -> CaseResult:
        """Run a case; on failure, try the fixed remedies once each, then stop with the findings."""
        res = self.session.run_one(self._spec(event, v0=v0))
        if res.ok:
            return res
        findings = parse_log(res.log)
        stage["failure"] = {"status": res.status, "status_text": STATUS_TEXT.get(res.status, res.status),
                            "error": res.meta.get("error"), "findings": [f.__dict__ for f in findings],
                            "suspect_states": suspect_states(res.log), "dyre_ierr": res.meta.get("dyre_ierr"),
                            "log_tail": res.log[-2500:]}
        if res.status in ("crashed", "timeout", "exception"):
            self._action("ran the case again in a new process", f"first attempt: {STATUS_TEXT[res.status]}")
            res = self.session.run_one(self._spec(event, v0=v0, repeat=1))
            if res.ok:
                return res
        if res.status == "run_error" and not self.setup.delt:
            self._action(f"halved the time step to {self.delt / 2:.6g} s", "PSS/E stopped during the simulation")
            self.delt /= 2
            res = self.session.run_one(self._spec(event, v0=v0))
            if res.ok:
                return res
        codes = {f["code"] for f in stage["failure"]["findings"]}
        if res.status == "dll_error" or "dll_not_loaded" in codes:
            names = ", ".join(Path(d).name for d in self.setup.dlls) or "the model DLL"
            reason = next((f["meaning"] for f in stage["failure"]["findings"] if f["code"] == "dll_not_loaded"), "")
            raise Stop(f"PSS/E could not load {names}. {reason or 'See the initialization findings.'} "
                       "This is an input problem, not a model behavior.")
        if res.status == "dyre_error" or codes & {"model_not_found", "record_ignored", "model_not_accessible"}:
            raise Stop("PSS/E could not read the model (see the initialization findings): an input problem, "
                       "not a model behavior")
        if res.status == "init_error" or "init_suspect" in codes:
            raise Stop("the model does not initialize in PSS/E (see the initialization findings)")
        raise Stop(f"the first run failed: {STATUS_TEXT.get(res.status, res.status)}")

    # --- Stage 2 ------------------------------------------------------------------------------------------------

    def _ref_events(self) -> dict[str, Event]:
        obs = 2.0

        def hold(v=1.0, f=NOMINAL_HZ, dur=0.1, label=""):
            t0, t1 = EVENT_START, EVENT_START + dur
            return Event(((0.0, 1.0, NOMINAL_HZ), (t0, v, f), (t1, 1.0, NOMINAL_HZ)), t1 + obs, t0, t1, label)

        return {"mild": hold(0.9, dur=0.05, label="0.9 pu for 0.05 s"),
                "sag": hold(0.5, dur=0.1, label="0.5 pu for 0.1 s"),
                "swell": hold(1.15, dur=0.5, label="1.15 pu for 0.5 s"),
                "frequency": hold(f=58.5, dur=5.0, label="58.5 Hz for 5 s")}

    def _time_step(self):
        self._stage("time_step", "checking that the results do not depend on the time step")
        refs = self._ref_events()
        d0 = self.delt
        steps = [d0, d0 / 2, d0 / 4] if not self.setup.delt else [d0, d0 / 2]
        specs = [(name, d, self._spec(ev, delt=d)) for d in steps for name, ev in refs.items()]
        results = self.session.run_many([s for _, _, s in specs])
        by = {(name, d): r for (name, d, _), r in zip(specs, results, strict=True)}
        mild_d0 = by[("mild", d0)]
        settle = cl.settle_time(mild_d0, refs["mild"].end)
        self.prompt_window = max(cl.MIN_PROMPT_WINDOW_S, 2 * settle + 0.05) if settle is not None else 0.5
        self.observe_s = max(2.0, self.prompt_window + 1.0)

        def pair(a, b):
            rows, ok = [], True
            for name, ev in refs.items():
                ra, rb = by[(name, a)], by[(name, b)]
                oa, ob = self._classify(ra, ev), self._classify(rb, ev)
                same, rms = cl.traces_match(ra, rb)
                match = same and oa.cls == ob.cls
                ok &= match
                rows.append({"reference": ev.label, "coarse": oa.label, "fine": ob.label,
                             "rms": None if math.isinf(rms) else round(rms, 5), "match": match})
            return ok, rows

        stage = self.doc["stages"]["time_step"] = {"candidates": steps, "settle_s": settle,
                                                   "prompt_window_s": self.prompt_window, "comparisons": []}
        chosen, sensitive = None, False
        for a, b in itertools.pairwise(steps):
            ok, rows = pair(a, b)
            stage["comparisons"].append({"coarse": a, "fine": b, "match": ok, "rows": rows})
            if ok and chosen is None:
                chosen = a
        if self.setup.delt:
            chosen = self.setup.delt
            sensitive = not stage["comparisons"][0]["match"]
        elif chosen is None:
            chosen, sensitive = steps[-1], True
        self.delt = chosen
        stage.update(chosen=chosen, sensitive=sensitive)
        if sensitive:
            stage["warning"] = (f"results still change when the time step is halved from {chosen:.6g} s; every "
                                "result below carries that uncertainty")
        if chosen != d0:
            self._action(f"used a time step of {chosen:.6g} s", f"results at {d0:.6g} s did not match half that step")
            # The prompt window is measured again at the chosen step.
            settle = cl.settle_time(by[("mild", chosen)], refs["mild"].end)
            if settle is not None:
                self.prompt_window = max(cl.MIN_PROMPT_WINDOW_S, 2 * settle + 0.05)
                self.observe_s = max(2.0, self.prompt_window + 1.0)
                stage.update(settle_s=settle, prompt_window_s=self.prompt_window)

    # --- Stage 3 ------------------------------------------------------------------------------------------------

    def _evaluator(self, fam_by_search: dict, context: dict, good: Callable[[cl.Outcome, CaseResult, Event], bool]):
        def evaluate(batch):
            items = []
            for search, x in batch:
                fam: Family = fam_by_search[id(search)]
                ev = fam.event(search.tag, x, context)
                items.append((fam, search.tag, x, ev, self._spec(ev, label=f"{fam.title}: {ev.label}")))
            results = self.session.run_many([it[4] for it in items])
            out = []
            for (fam, outer, x, ev, _spec), res in zip(items, results, strict=True):
                oc = self._classify(res, ev)
                self.points.append(_Point(fam.id, outer, x, ev, res, oc))
                out.append(good(oc, res, ev))
            return out

        return evaluate

    def _search(self, families: list[Family], context: dict, good, outer_values: dict | None = None):
        searches, fam_by_search = [], {}
        for fam in families:
            values = (outer_values or {}).get(fam.id, fam.outer_values)
            for value in values:
                s = BoundarySearch(fam.inner, tag=value, interior_checks=LEVELS[self.setup.level].interior_checks)
                searches.append(s)
                fam_by_search[id(s)] = fam
        run_searches(searches, self._evaluator(fam_by_search, {**context, "observe_s": self.observe_s}, good),
                     should_stop=lambda: self.session.cancelled)
        for fam in families:
            mine = [s for s in searches if fam_by_search[id(s)] is fam]
            self.doc["families"][fam.id] = {
                "title": fam.title, "kind": fam.kind, "description": fam.description, "outer_name": fam.outer_name,
                "outer_unit": fam.outer_unit, "inner": {"name": fam.inner.name, "unit": fam.inner.unit,
                                                        "lo": fam.inner.lo, "hi": fam.inner.hi},
                "searches": [s.summary() for s in mine],
                "failures": sum(1 for p in self.points if p.family == fam.id
                                and p.outcome.cls in (cl.FAILURE, cl.UNSTABLE)),
            }
        return searches

    def _characterize(self, presets):
        families = {f.id: f for f in build_families(self.setup.level, presets, observe_s=self.observe_s)}
        self.families = families
        primary = [f for f in families.values() if not f.needs and f.kind != "rocof"]
        self._stage("characterization", "searching the ride-through boundaries")
        self._search(primary, {}, lambda oc, _r, _e: oc.rode_through)
        if self.session.cancelled:
            return
        if "recovery" in families:
            self._recovery(families["recovery"])
        if "repeat" in families:
            self._repeat(families["repeat"])
        if "rocof" in families:
            self._rocof(families["rocof"])

    def _unsolvable(self, family: str) -> set[float]:
        """Outer values of `family` where any case failed to solve (PSS/E not converged, NaN): the search read those
        failures as trips, so the row is not a measurement."""
        return {p.outer for p in self.points if p.family == family and p.outcome.cls == cl.FAILURE}

    def _uv_points(self):
        return [p for p in self.points if p.family == "undervoltage"]

    def _recovery(self, fam: Family):
        trips = [p for p in self._uv_points() if p.outcome.tripped]
        if not trips:
            self.doc["families"][fam.id] = {"title": fam.title, "skipped": "the load never tripped on a sag, so "
                                            "there is no reconnection to characterize"}
            return
        # The shallowest sag that tripped, at the shortest duration seen tripping there.
        depth = max(p.outer for p in trips)
        trip = min((p for p in trips if p.outer == depth), key=lambda p: p.inner)
        self._stage("characterization", "mapping the reconnection window")
        self.trip_event = (depth, max(trip.inner, 0.05))
        # A few long runs size the observation window for the rest of the search. Not only 1.0 pu: a model whose
        # reconnect window is strictly above 1.0 pu (VRPA = 1.00 in several presets) never reconnects at 1.0.
        ctx = {"trip_event": self.trip_event}
        levels = RECOVERY_PROBE_PU
        probe_evs = [fam.event(0.0, v, ctx) for v in levels]
        probes = self.session.run_many([self._spec(ev, label=f"{fam.title}: {ev.label}") for ev in probe_evs])
        backs = [_reconnection(res, ev.end) for res, ev in zip(probes, probe_evs, strict=True)]
        came_back = [b for b in backs if b["reconnected"]]
        if not came_back:
            self.doc["families"][fam.id] = {
                "title": fam.title, "trip_event": {"depth_pu": depth, "duration_s": self.trip_event[1]},
                "skipped": (f"after tripping, the load did not reconnect within {fam.observe_s:.0f} s at any of "
                            + ", ".join(f"{v:g}" for v in levels) + " pu")}
            return
        done_by = max((b.get("delay_s") or 0.0) + (b.get("ramp_s") or 0.0) for b in came_back)
        ctx["recovery_observe_s"] = min(fam.observe_s, max(10.0, 1.5 * done_by + 5.0))

        def reconnected(oc, res, ev):
            return _reconnection(res, ev.end)["reconnected"]

        self._search([fam], ctx, reconnected)
        info = self.doc["families"][fam.id]
        info["trip_event"] = {"depth_pu": depth, "duration_s": self.trip_event[1]}
        info["observe_s"] = ctx["recovery_observe_s"]
        info["reconnections"] = [
            {"recovery_pu": p.inner, **_reconnection(p.result, p.event.end), "key": p.result.key}
            for p in sorted((p for p in self.points if p.family == fam.id), key=lambda p: p.inner)]

    def _repeat(self, fam: Family):
        level = LEVELS[self.setup.level]
        single_ok = {}
        for s in self.doc["families"].get("undervoltage", {}).get("searches", []):
            oks = [x for x, ok in s["points"] if ok]
            if (s["monotonic"] and s["transitions"] and oks and max(oks) >= 0.05
                    and s["tag"] not in self._unsolvable("undervoltage")):
                single_ok[s["tag"]] = round(0.6 * max(oks), 4)
        if not single_ok:
            self.doc["families"][fam.id] = {"title": fam.title, "skipped": "no sag depth has both a ride-through "
                                            "and a trip region to build repeated sags from"}
            return
        depths = sorted(single_ok)
        pick = depths if len(depths) <= level.repeat_depths else [
            depths[round(i * (len(depths) - 1) / (level.repeat_depths - 1))] for i in range(level.repeat_depths)]
        self._stage("characterization", "repeated sags")
        self._search([fam], {"single_ok": single_ok}, lambda oc, _r, _e: oc.rode_through,
                     outer_values={fam.id: tuple(pick)})
        self.doc["families"][fam.id]["single_sag_s"] = {str(k): single_ok[k] for k in pick}

    def _rocof(self, fam: Family):
        held_ok = {}
        for s in self.doc["families"].get("frequency", {}).get("searches", []):
            held_ok[s["tag"]] = max((x for x, ok in s["points"] if ok), default=0.0)
        usable = []
        for f in fam.outer_values:
            near = [v for v in held_ok if (v - NOMINAL_HZ) * (f - NOMINAL_HZ) > 0 and abs(v - NOMINAL_HZ) >= abs(
                f - NOMINAL_HZ)]
            # Only frequencies the load is seen riding through when held: a ramp is then the only new stress.
            if near and held_ok[min(near, key=lambda v: abs(v - f))] >= 2.0:
                usable.append(f)
        if not usable:
            self.doc["families"][fam.id] = {"title": fam.title, "skipped": "the load does not ride through the "
                                            "ramp's target frequencies when they are held"}
            return
        self._stage("characterization", "frequency ramps")
        self._search([fam], {}, lambda oc, _r, _e: oc.rode_through, outer_values={fam.id: tuple(usable)})

    # --- Stage 4 ------------------------------------------------------------------------------------------------

    def _robustness(self):
        if self.session.cancelled:
            return
        self._stage("robustness", "repeatability, half time step and run() cadence")
        stage = self.doc["stages"]["robustness"] = {}
        boundary = []
        for fid in ("undervoltage", "overvoltage", "frequency"):
            for s in self.doc["families"].get(fid, {}).get("searches", []):
                if s["tag"] in self._unsolvable(fid):
                    continue  # a boundary that includes unsolved cases is not a boundary (the first check is a repeat)
                for below, above, _ in s["transitions"][:1]:
                    boundary.append((fid, s["tag"], below, above))
        boundary = boundary[:6]
        by_key = {(p.family, p.outer, p.inner): p for p in self.points}

        checks = []
        if boundary:
            fid, outer, _below, above = boundary[0]
            p = by_key.get((fid, outer, above))
            if p:
                again = self.session.run_one(self._spec(p.event, repeat=1))
                same, rms = cl.traces_match(p.result, again, p_tol=1e-4)
                checks.append(("repeat", p, again, same, rms))
        stage["repeatability"] = [{"case": c[1].event.label, "match": c[3], "rms": _num(c[4])} for c in checks]

        halves = []
        specs = []
        for fid, outer, below, above in boundary:
            for x in (below, above):
                p = by_key.get((fid, outer, x))
                if p:
                    specs.append((p, self._spec(p.event, delt=self.delt / 2)))
        for (p, _), res in zip(specs, self.session.run_many([s for _, s in specs]), strict=True):
            oc = self._classify(res, p.event)
            halves.append({"family": p.family, "case": p.event.label, "outcome": p.outcome.label,
                           "half_step_outcome": oc.label, "match": oc.cls == p.outcome.cls})
        stage["half_step"] = halves

        reconnect = [p for p in self.points if p.family == "recovery" and p.outcome.tripped
                     and _reconnection(p.result, p.event.end)["reconnected"]]
        if reconnect:
            p = min(reconnect, key=lambda q: abs(q.inner - 1.0))
            every = self.session.run_one(self._spec(p.event, every_step=True))
            same, rms = cl.traces_match(p.result, every)
            a, b = _reconnection(p.result, p.event.end), _reconnection(every, p.event.end)
            stage["cadence"] = {"case": p.event.label, "match": same, "rms": _num(rms),
                                "event_to_event": a, "every_step": b}
            if not same:
                stage["cadence"]["warning"] = ("the result changes when psspy.run is called every time step "
                                               "instead of from event to event: the model depends on how the "
                                               "study script calls PSS/E")
        else:
            stage["cadence"] = {"skipped": "no trip-and-reconnect case to compare"}

    # --- comparison ---------------------------------------------------------------------------------------------

    def _compare(self, presets):
        maxima = {"undervoltage": LEVELS[self.setup.level].max_voltage_duration,
                  "overvoltage": LEVELS[self.setup.level].max_voltage_duration,
                  "frequency": LEVELS[self.setup.level].max_frequency_duration}
        for preset in presets:
            per = {}
            for kind in ("undervoltage", "overvoltage", "frequency"):
                fam = self.doc["families"].get(kind)
                if not fam or "searches" not in fam:
                    continue
                if kind == "frequency" and preset.frequency_ride_through is None:
                    per[kind] = {"overall": "no requirement", "points": [],
                                 "note": "this preset publishes no frequency ride-through table"}
                    continue
                verdicts = compare_family(preset, kind, fam["searches"], maxima[kind],
                                          frozenset(self._unsolvable(kind)))
                per[kind] = {"overall": overall(verdicts), "points": [v.to_dict() for v in verdicts]}
            worst = overall_from(per)
            self.doc["comparison"][preset.id] = {"label": preset.label, "families": per, "overall": worst}


def overall_from(per: dict) -> str:
    order = ["fails", "at the edge", "not solvable", "beyond tested range", "meets", "no requirement"]
    found = [v["overall"] for v in per.values()]
    for o in order:
        if o in found:
            return o
    return "no requirement"


def _num(x):
    return None if x is None or math.isinf(x) or math.isnan(x) else round(x, 6)


def _reconnection(res: CaseResult, event_end: float) -> dict:
    """Whether, when and how far the load came back after the bus returned (to any level)."""
    if not res.ok or not res.time:
        return {"reconnected": False, "status": res.status}
    p0 = res.p[0] or 1.0
    return cl.reconnection([(t, p / p0) for t, p in zip(res.time, res.p, strict=True) if t >= event_end], event_end)
