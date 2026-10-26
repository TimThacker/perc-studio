"""Analytic response of the PERC2 standard model (PSS/E 36.7 PERCxx2U) to one constant-depth voltage or frequency
event, or to any piecewise-constant voltage/frequency profile.

A hand-coded time-stepped model of the logic as measured in PSS/E 36.7.1, not PSS/E. What it reproduces,
checked against PSS/E traces in the PSS/E validation library, which is not published:

- the voltage filter (Tv) and the frequency filter (Tf), whose input is held at nominal while the bus voltage is below
  0.7 pu;
- the six cease checks, each with its own timer that resets when its condition clears: momentary low/high (Tcease),
  long low/high (4 points each; point 3 waits point 1's time, TVLC1/TVHC1, as PSS/E 36.7.1 does) and frequency;
  Tdelay after any of them;
  FracOn = 1 - fcease on a cease;
- the cease level (0 momentary, 1 long, 2 frequency) choosing the reconnect delay and ramp (Trecon/Tramp x Ldfact,
  TLreconL/TLrampL x Ldfact, TLreconH/TLrampH x Ldfact, or never); escalation to a higher level while ceased;
- the reconnect window VLrecon < Vtf < VHrecon (VLrecon raised to VLcease, VHrecon lowered to VHcease whatever the
  flags), the linear ramp to (1 - fcease) + frecon x fcease, every check timer restarting when the ramp starts, and a
  new cease interrupting the ramp (so a sustained sag inside the reconnect window cycles);
- steady-state P = P0 (Vtf/Vinit)^nP limited by min(Ipmax, Imax) / max(Ipmin, -Imax), the Tt converter lag, and the
  droop dP = Kdroop (df - deadband) on the MVA base.

What it leaves out: the washouts, lead-lags and the reactive path's transients (steady state only); power is reported
in per unit of the block's initial power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..base import (
    FAULT_DURATION,
    FAULT_START,
    FREQUENCY_EVENT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from ..common import (  # noqa: F401 - DT/OUTPUT_DT/MAX_POINTS are part of the module's API
    DT,
    MAX_POINTS,
    OUTPUT_DT,
    decimate,
    flag_on,
)
from .cons import effective_ldfact, effective_limits, long_time_point

MIN_VOLTAGE = 1e-3
FREQUENCY_GATE_PU = 0.7  # below this bus voltage the frequency filter's input is held at nominal (sheet note 5)
NEVER = math.inf


@dataclass
class _Check:
    name: str
    level: int  # 0 momentary, 1 long, 2 frequency
    side: str  # "low" | "high"
    kind: str  # "voltage" | "frequency"
    threshold: float
    delay: float

    def active(self, vtf, f_hz):
        x = vtf if self.kind == "voltage" else f_hz
        return x < self.threshold if self.side == "low" else x > self.threshold


def build_checks(c) -> list[_Check]:
    checks = []
    if flag_on(c, "VLMflag"):
        checks.append(_Check("VLM", 0, "low", "voltage", c["VLcease"], c["Tcease"]))
    if flag_on(c, "VHMflag"):
        checks.append(_Check("VHM", 0, "high", "voltage", c["VHcease"], c["Tcease"]))
    # PSS/E 36.7.1 evaluates long point 3 with point 1's time (TVLC1/TVHC1), not its own: reproduced as measured.
    if flag_on(c, "VLLflag"):
        checks += [_Check(f"VLC{i}", 1, "low", "voltage", c[f"VLC{i}"], c[f"TVLC{long_time_point(i)}"]) for i in (1, 2, 3, 4)]
    if flag_on(c, "VLHflag"):
        checks += [_Check(f"VHC{i}", 1, "high", "voltage", c[f"VHC{i}"], c[f"TVHC{long_time_point(i)}"]) for i in (1, 2, 3, 4)]
    if flag_on(c, "FLflag"):
        checks.append(_Check("FLC1", 2, "low", "frequency", c["FLC1"], c["TFLC1"]))
    if flag_on(c, "FHflag"):
        checks.append(_Check("FHC1", 2, "high", "frequency", c["FHC1"], c["TFHC1"]))
    return checks


class CeaseLogic:
    """The cease/reconnect machine (sheet Figures 2-4) as PSS/E 36.7.1 runs it."""

    MONITOR, CEASED, RAMP = 0, 1, 2

    def __init__(self, c):
        self.c = c
        self.fcease = min(max(c["fcease"], 0.0), 1.0)
        self.floor = 1.0 - self.fcease
        self.final = self.floor + max(c["frecon"], 0.0) * self.fcease
        self.ldfact = effective_ldfact(c)
        self.vlrecon = max(c["VLrecon"], c["VLcease"])
        self.vhrecon = min(c["VHrecon"], c["VHcease"])
        self.checks = build_checks(c) if self.fcease > 0 else []
        self.timers: dict[str, float | None] = {k.name: None for k in self.checks}
        self.mode = self.MONITOR
        self.level = -1
        self.frac = 1.0
        self.pending: tuple[_Check, float] | None = None  # a triggered check waiting out Tdelay
        self.recon_t0 = None
        self.ramp_t0 = None
        self.ramp_from = 1.0
        self.trecon_used = max(c["Trecon"], 0.0)
        self.tramp_used = max(c["Tramp"], 0.0) * self.ldfact
        self.cause: _Check | None = None
        self.events: dict[str, float] = {}
        self.history: list[tuple[str, float, object]] = []

    def _mark(self, name, t, detail=None):
        self.events.setdefault(name, t)
        self.history.append((name, t, detail))

    def _used(self, check: _Check):
        c = self.c
        if check.level == 0:
            return max(c["Trecon"], 0.0), max(c["Tramp"], 0.0) * self.ldfact
        if check.level == 1 and check.side == "low":
            return max(c["TLreconL"], 0.0), max(c["TLrampL"], 0.0) * self.ldfact
        if check.level == 1:
            return max(c["TLreconH"], 0.0), max(c["TLrampH"], 0.0) * self.ldfact
        return NEVER, NEVER

    def _eligible(self, check):
        return self.mode != self.CEASED or check.level > self.level

    def _cease(self, check, t):
        if self.mode == self.CEASED:  # escalation: the load is already off, only the reconnect settings change
            self.level = check.level
        else:
            self.mode, self.level, self.frac = self.CEASED, check.level, self.floor
            self._mark("trip_time", t, check.name)
        self.cause = check
        self.trecon_used, self.tramp_used = self._used(check)
        self.recon_t0 = None
        self.pending = None
        self.history.append(("cease", t, check.name))

    def step(self, t, vtf, f_hz):
        eps = 1e-9
        for check in self.checks:
            if not self._eligible(check):
                self.timers[check.name] = None
                continue
            if check.active(vtf, f_hz):
                if self.timers[check.name] is None:
                    self.timers[check.name] = t
                if t - self.timers[check.name] >= max(check.delay, 0.0) - eps and (
                        self.pending is None or check.level > self.pending[0].level):
                    self.pending = (check, t)
            else:
                self.timers[check.name] = None
        if self.pending is not None and t - self.pending[1] >= max(self.c["Tdelay"], 0.0) - eps:
            check = self.pending[0]
            if self.mode != self.CEASED or check.level > self.level:
                self._cease(check, t)
            self.pending = None
        if self.mode == self.CEASED and self.level in (0, 1):
            if self.vlrecon < vtf < self.vhrecon:
                if self.recon_t0 is None:
                    self.recon_t0 = t
                if t - self.recon_t0 >= self.trecon_used - eps:
                    self.mode, self.ramp_t0, self.ramp_from = self.RAMP, t, self.frac
                    self.timers = dict.fromkeys(self.timers)  # every check restarts with the ramp
                    self._mark("reconnect_start", t)
            else:
                self.recon_t0 = None
        if self.mode == self.RAMP:
            progress = 1.0 if self.tramp_used <= 0 else min((t - self.ramp_t0) / self.tramp_used, 1.0)
            self.frac = self.ramp_from + (self.final - self.ramp_from) * progress
            if progress >= 1.0:
                self.mode, self.level, self.frac = self.MONITOR, -1, self.final
                self._mark("reconnect_end", t)
        return self.frac


def _limit(i, lo, hi):
    return min(max(i, lo), hi)


def run_profile(c, v_of_t, f_of_t, t_end, dt=DT):
    """Step the model on PSS/E's quarter-cycle grid. Returns (rows, logic): rows are (t, V, P pu of initial power,
    FracOn, f Hz, Vtf)."""
    ldfact = effective_ldfact(c)
    tv, tf, tt = max(c["Tv"], 0.0), max(c["Tf"], 0.0), max(c["Tt"], 2 * dt)
    ipmax_u, ipmin_u, _iq_hi, _iq_lo = effective_limits(c)
    logic = CeaseLogic(c)
    v0 = max(v_of_t(0.0), MIN_VOLTAGE)
    vtf, ftf, i_state = v0, 0.0, None
    rows = []
    for k in range(round(t_end / dt) + 1):
        t = k * dt
        v = max(v_of_t(t), MIN_VOLTAGE)
        f_hz = f_of_t(t)
        f_dev = (f_hz / NOMINAL_FREQUENCY_HZ - 1.0) if v >= FREQUENCY_GATE_PU else 0.0
        vtf = v if tv == 0 else vtf + (v - vtf) * (1 - math.exp(-dt / tv))
        ftf = f_dev if tf == 0 else ftf + (f_dev - ftf) * (1 - math.exp(-dt / tf))
        frac = logic.step(t, vtf, NOMINAL_FREQUENCY_HZ * (1 + ftf))
        edge = c["dbfl"] if ftf < c["dbfl"] else min(ftf, c["dbfh"])
        droop = c["Kdroop"] * (ftf - edge)
        i_cmd = _limit((ldfact + droop) * ((vtf / v0) ** c["nP"]) / max(vtf, MIN_VOLTAGE), ipmin_u, ipmax_u)
        i_out = i_cmd * frac
        i_state = i_out if i_state is None else i_state + (i_out - i_state) * (1 - math.exp(-dt / tt))
        rows.append((t, v, v * i_state / ldfact, frac, f_hz, vtf))
    return rows, logic


_TRIP_TYPES = {("voltage", "low"): "undervoltage", ("voltage", "high"): "overvoltage",
               ("frequency", "low"): "underfrequency", ("frequency", "high"): "overfrequency"}


def _response(rows, logic, c, *, event_kind, fault_duration_s, extra, fault_end):
    dense = decimate(rows)
    markers = {k: v for k, v in logic.events.items() if k in ("trip_time", "reconnect_start", "reconnect_end")}
    first = next((h for h in logic.history if h[0] == "cease"), None)
    first_check = next((k for k in logic.checks if first and k.name == first[2]), None)
    trips = "trip_time" in markers
    # every cease and every ramp, in order (PERC2 can cease again mid-ramp, and cycles in a sag inside the window)
    trip_events, reconnect_events, ramp_start = [], [], None
    off = False  # the load is ceased (an escalation while off is not a new trip)
    for name, t, detail in logic.history:
        if name == "cease" and not off:
            if ramp_start is not None:  # the cease interrupts a running ramp
                reconnect_events.append({"start": ramp_start, "end": t})
                ramp_start = None
            trip_events.append({"time": t, "check": detail})
            off = True
        elif name == "reconnect_start":
            ramp_start, off = t, False
        elif name == "reconnect_end" and ramp_start is not None:
            reconnect_events.append({"start": ramp_start, "end": t})
            ramp_start = None
    if ramp_start is not None:  # still ramping when the run ends
        reconnect_events.append({"start": ramp_start, "end": rows[-1][0]})
    stays = None
    if trips and logic.mode == CeaseLogic.CEASED:
        if logic.level == 2:
            stays = "a frequency cease never reconnects"
        elif not logic.vlrecon < 1.0 < logic.vhrecon:
            stays = (f"the reconnect window {logic.vlrecon:.3g} < V < {logic.vhrecon:.3g} pu excludes the post-event "
                     "voltage")
    return {
        "trip_events": trip_events,
        "reconnect_events": reconnect_events,
        "cycles": len(trip_events) > 1,
        "stays_tripped_reason": stays,
        "event_kind": event_kind,
        "v_points": [(r[0], r[1]) for r in dense],
        "p_points": [(r[0], r[2]) for r in dense],
        "frac_on_points": [(r[0], r[3]) for r in dense],
        "trips": trips,
        "trip_type": _TRIP_TYPES[(first_check.kind, first_check.side)] if first_check else None,
        "cease_check": first_check.name if first_check else None,
        "cease_level": logic.level if logic.mode == CeaseLogic.CEASED else (first_check.level if first_check else None),
        "never_reconnects": logic.mode == CeaseLogic.CEASED and logic.level == 2,
        "fault_start": FAULT_START,
        "fault_end": fault_end,
        "fault_duration_s": fault_duration_s,
        "sim_end": rows[-1][0],
        "markers": markers,
        "history": [(name, t, detail) for name, t, detail in logic.history],
        **extra,
    }


def _tail(c):
    """Long enough after the event for the slowest reconnect to finish (capped)."""
    ld = effective_ldfact(c)
    pairs = [(c["Trecon"], c["Tramp"]), (c["TLreconL"], c["TLrampL"]), (c["TLreconH"], c["TLrampH"])]
    longest = max(max(a, 0.0) + max(b, 0.0) * ld for a, b in pairs)
    return min(longest + 1.0, 600.0) if c["fcease"] > 0 else 1.0


def simulate_perc2_standard_response(c, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT):
    fault_end = FAULT_START + fault_duration_s

    def v_of_t(t):
        return fault_voltage_pu if FAULT_START <= t < fault_end else 1.0

    rows, logic = run_profile(c, v_of_t, lambda t: NOMINAL_FREQUENCY_HZ, fault_end + _tail(c))
    return _response(rows, logic, c, event_kind="voltage", fault_duration_s=fault_duration_s,
                     extra={"fault_voltage_pu": fault_voltage_pu}, fault_end=fault_end)


def simulate_perc2_standard_frequency_response(c, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                               fault_frequency_hz=FREQUENCY_EVENT_HZ):
    fault_end = FAULT_START + fault_duration_s

    def f_of_t(t):
        return fault_frequency_hz if FAULT_START <= t < fault_end else NOMINAL_FREQUENCY_HZ

    rows, logic = run_profile(c, lambda t: 1.0, f_of_t, fault_end + max(1.0, fault_duration_s * 0.1))
    resp = _response(rows, logic, c, event_kind="frequency", fault_duration_s=fault_duration_s,
                     extra={"fault_frequency_hz": fault_frequency_hz}, fault_end=fault_end)
    resp["f_points"] = [(r[0], r[4]) for r in decimate(rows)]
    if resp["trip_type"] not in (None, "underfrequency", "overfrequency"):
        resp["trip_type"] = None
    return resp


def simulate_perc2_standard_profile(c, breakpoints, t_end):
    """Any piecewise-constant profile: `breakpoints` [(t, v_pu, f_hz), ...] in time order, each holding until the
    next. Used to compare with the PSS/E library's own profiles."""
    pts = sorted(breakpoints)

    def at(t, i):
        val = pts[0][i]
        for p in pts:
            if p[0] <= t + 1e-12:
                val = p[i]
            else:
                break
        return val

    rows, logic = run_profile(c, lambda t: at(t, 1), lambda t: at(t, 2), t_end)
    return rows, logic
