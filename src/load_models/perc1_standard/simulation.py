"""Analytic response of the PERC1 standard model (PSS/E 36.7 PERCxx1U) to one
constant-depth voltage or frequency event.

A hand-coded time-stepped model of the data sheet's logic as measured in PSS/E
36.7.1, not PSS/E. What it reproduces, checked against PSS/E traces in
the PSS/E validation library, which is not published:

- the voltage filter (Tv), the cease timers (Tcease, Tdelay), FracOn = 1 - fcease,
  the reconnect timers (Trecon) and the linear ramp (Tramp) to
  (1 - fcease) + frecon * fcease, including a second dip during or after a ramp;
- steady-state P = P0 (V/V0)^nP and the Ipmax/Ipmin current limit, with the
  Tt converter lag;
- the frequency droop dP = Kdroop (df - deadband) (filtered by Tf), limited.

What it leaves out: the washouts (Kvp/Kvq), the lead-lags and the reactive path,
whose transients it does not model (steady state only); the model reports Q-less
active power in per unit of the block's initial power.

It also flags the two PSS/E 36.7.1 failures (`psse_nan_hazard`): a dip that ends
while Tdelay is running, and a voltage of 0 pu.
"""

from __future__ import annotations

import math

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
)

MIN_VOLTAGE = 1e-3  # PSS/E returns NaN at exactly 0 pu


class _CeaseLogic:
    """The data sheet's Figure 3, as PSS/E 36.7.1 behaves."""

    MONITOR, TCEASE, TDELAY, CEASED, TRECON, RAMP = range(6)

    def __init__(self, c):
        self.c = c
        self.state = self.MONITOR
        self.t0 = 0.0
        self.frac = 1.0
        self.ramp_from = 1.0
        self.cease_timer_t0 = None  # a Tcease timer running alongside a ramp
        self.hazard = False
        self.events = {}

    def _mark(self, name, t):
        self.events.setdefault(name, t)

    def step(self, t, vtf):
        c = self.c
        if c["fcease"] <= 0:
            return 1.0
        low, high = c["Vcease"], max(c["Vrecon"], c["Vcease"])
        final = (1 - c["fcease"]) + max(c["frecon"], 0.0) * c["fcease"]
        floor = 1 - min(max(c["fcease"], 0.0), 1.0)
        s = self.state
        if s == self.MONITOR:
            if vtf < low:
                self.state, self.t0 = self.TCEASE, t
        elif s == self.TCEASE:
            if vtf >= low:
                self.state = self.MONITOR
            elif t - self.t0 >= max(c["Tcease"], 0.0):
                self.state, self.t0 = self.TDELAY, t
        elif s == self.TDELAY:
            if vtf > high and c["Tdelay"] > 0:
                self.hazard = True  # PSS/E 36.7.1 starts Trecon here and returns NaN
            if t - self.t0 >= max(c["Tdelay"], 0.0):
                self.state = self.CEASED
                self.frac = floor
                self._mark("trip_time", t)
        elif s == self.CEASED:
            if vtf > high:
                self.state, self.t0 = self.TRECON, t
        elif s == self.TRECON:
            if vtf < low:
                self.state, self.t0 = self.TCEASE, t
            elif t - self.t0 >= max(c["Trecon"], 0.0):
                self.state, self.t0, self.ramp_from = self.RAMP, t, self.frac
                self._mark("reconnect_start", t)
        elif s == self.RAMP:
            ramp_s = max(c["Tramp"], 0.0)
            progress = 1.0 if ramp_s <= 0 else min((t - self.t0) / ramp_s, 1.0)
            self.frac = self.ramp_from + (final - self.ramp_from) * progress
            if vtf < low and self.cease_timer_t0 is None:
                self.cease_timer_t0 = t
            elif vtf >= low:
                self.cease_timer_t0 = None
            if self.cease_timer_t0 is not None and t - self.cease_timer_t0 >= max(c["Tcease"], 0.0):
                # a new cease interrupts the ramp: restart the cycle from the frozen level
                self.cease_timer_t0 = None
                self.state, self.t0 = self.TDELAY, t
            elif progress >= 1.0:
                self.state = self.MONITOR
                self.frac = final
                self._mark("reconnect_end", t)
        return self.frac


def _limit(i, lo, hi):
    return min(max(i, lo), hi)


def _run(c, v_of_t, f_of_t, t_end):
    """Step PSS/E's quarter-cycle grid; returns dense (t, v, p_norm, frac, f) rows."""
    ldfact = c["Ldfact"] if c["Ldfact"] > 0 else 0.8
    tv = max(c["Tv"], 0.0)
    tf = max(c["Tf"], 0.0)
    tt = max(c["Tt"], 2 * DT)
    logic = _CeaseLogic(c)
    vtf, ftf, i_state = v_of_t(0.0), 0.0, None
    rows = []
    n = round(t_end / DT)
    for k in range(n + 1):
        t = k * DT
        v = max(v_of_t(t), MIN_VOLTAGE)
        f_dev = f_of_t(t) / NOMINAL_FREQUENCY_HZ - 1.0
        vtf = v if tv == 0 else vtf + (v - vtf) * (1 - math.exp(-DT / tv))
        ftf = f_dev if tf == 0 else ftf + (f_dev - ftf) * (1 - math.exp(-DT / tf))
        frac = logic.step(t, vtf)
        edge = c["dbfl"] if ftf < c["dbfl"] else (min(ftf, c["dbfh"]))
        droop = c["Kdroop"] * (ftf - edge)
        i_cmd = _limit((ldfact + droop) * (vtf ** c["nP"]) / max(vtf, MIN_VOLTAGE), c["Ipmin"], c["Ipmax"])
        i_out = i_cmd * frac
        i_state = i_out if i_state is None else i_state + (i_out - i_state) * (1 - math.exp(-DT / tt))
        rows.append((t, v, v * i_state / ldfact, frac, NOMINAL_FREQUENCY_HZ * (1 + f_dev)))
    return rows, logic


def _response(rows, logic, c, *, event_kind, fault_duration_s, extra, fault_end):
    dense = decimate(rows)
    markers = {k: v for k, v in logic.events.items() if k in ("trip_time", "reconnect_start", "reconnect_end")}
    trips = "trip_time" in markers
    return {
        "event_kind": event_kind,
        "v_points": [(r[0], r[1]) for r in dense],
        "p_points": [(r[0], r[2]) for r in dense],
        "frac_on_points": [(r[0], r[3]) for r in dense],
        "trips": trips,
        "trip_type": "undervoltage" if trips else None,
        "fault_start": FAULT_START,
        "fault_end": fault_end,
        "fault_duration_s": fault_duration_s,
        "sim_end": rows[-1][0],
        "markers": markers,
        "psse_nan_hazard": logic.hazard or any(r[1] <= MIN_VOLTAGE * 1.0001 for r in rows),
        "armed_required_delay_s": None if trips else (c["Tcease"] if c["fcease"] > 0 else None),
        **extra,
    }


def simulate_perc1_standard_response(c, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT):
    fault_end = FAULT_START + fault_duration_s

    def v_of_t(t):
        return fault_voltage_pu if FAULT_START <= t < fault_end else 1.0

    # Long enough for the ramp to finish after the fault clears.
    tail = max(c["Trecon"], 0.0) + max(c["Tramp"], 0.0) + 1.0 if c["fcease"] > 0 else 1.0
    t_end = fault_end + min(tail, 3600.0)
    rows, logic = _run(c, v_of_t, lambda t: NOMINAL_FREQUENCY_HZ, t_end)
    return _response(rows, logic, c, event_kind="voltage", fault_duration_s=fault_duration_s,
                     extra={"fault_voltage_pu": fault_voltage_pu}, fault_end=fault_end)


def simulate_perc1_standard_frequency_response(c, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                               fault_frequency_hz=FREQUENCY_EVENT_HZ):
    fault_end = FAULT_START + fault_duration_s

    def f_of_t(t):
        return fault_frequency_hz if FAULT_START <= t < fault_end else NOMINAL_FREQUENCY_HZ

    t_end = fault_end + max(1.0, fault_duration_s * 0.1)
    rows, logic = _run(c, lambda t: 1.0, f_of_t, t_end)
    resp = _response(rows, logic, c, event_kind="frequency", fault_duration_s=fault_duration_s,
                     extra={"fault_frequency_hz": fault_frequency_hz}, fault_end=fault_end)
    resp["f_points"] = [(r[0], r[4]) for r in decimate(rows)]
    resp["trips"], resp["trip_type"], resp["markers"] = False, None, {}  # frequency never ceases this model
    return resp
