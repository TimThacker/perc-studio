"""PERC2 DLL v2.3 response to a single constant-depth voltage or frequency event.

v2.3 runs the PERC1 DLL's logic (in PSS/E, the PERC1 DLL behavior checks pass on both builds), so this module holds
its own copy of that simulator (its filters, power loop and response shape, up to `_frequency_response`)
with what v2.3 changed or adds, as PSS/E 35.6.4 and 36.7.1 measured it:

- **Ramps.** RAMPA and RAMPUA last their CON times LFM (LFM below 0.001 counts as 0.8); RUFRN1, ROFRN1, RAMPAMC and
  RAMPUAMC last their CON in seconds.
- **Momentary cessation** (ICON(M+1) = 1, FCEASE > 0). The filtered voltage strictly below VLBLK or above VUBLK ceases
  the load at once (no CMTDELAY): FracOn steps to 1 - FCEASE. It comes back after the filtered voltage has been
  strictly inside (VLRCMC, VURCMC) for TBLK + TDELY without a break, ramping over RAMPAMC (after a low-voltage
  cessation) or RAMPUAMC (high) to (1 - FCEASE) + FRECON x FCEASE - the same partial return as a trip. The stage
  timers keep running during a cessation: a stage that trips turns it into an ordinary trip, which reconnects on the
  stage path (VRPA < V < VRUPA, TDRA/TRUPA + CMTDELAYC, RAMPA/RAMPUA). A new cessation during the ramp ceases again.
"""

from __future__ import annotations

import itertools
import math

from ..base import (
    FAULT_DURATION,
    FAULT_START,
    FREQUENCY_EVENT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from .cons import FIXED_DEFAULTS, RAMP_CONS, effective_lfm, flag_on, ramp_seconds

# The frequency trip/reconnect CONs the model uses: stage 1 only; the "2"/"3"/"4" sets are marked "NOT USED" by the vendor.
UNDERFREQUENCY_TRIP_CONS = ("FUFTP1", "TUFTP1")
OVERFREQUENCY_TRIP_CONS = ("FOFTP1", "TOFTP1")
UNDERFREQUENCY_RECONNECT_CONS = ("FUFRN1", "TUFRN1", "RUFRN1")
OVERFREQUENCY_RECONNECT_CONS = ("FOFRN1", "TOFRN1", "ROFRN1")

# The 4 Option-3 stage CON pairs per direction, stage 1 first - VDPA/DMA and
# VDUA/TDUA are stage 1, the same point Option 1 has always been.
UNDERVOLTAGE_STAGE_CONS = [("VDPA", "DMA"), ("VDPA1", "DMA1"), ("VDPA2", "DMA2"), ("VDPA3", "DMA3")]
OVERVOLTAGE_STAGE_CONS = [("VDUA", "TDUA"), ("VDUA1", "TDUA1"), ("VDUA2", "TDUA2"), ("VDUA3", "TDUA3")]

# Floor for a zero time constant, so a bypassed filter is an instant one.
_MIN_TAU = 1e-6
# Cycling (VRPA below a stage voltage) never ends on its own; stop after this
# many trips.
_MAX_TRIPS = 6
_TIME_EPS = 1e-9


def _con(p, name):
    """A CON from `p`, falling back to the vendor default for the secondary
    CONs older saved cases may not carry."""
    return p[name] if name in p else FIXED_DEFAULTS[name]


class _Filtered:
    """A piecewise-constant input through a first-order lag, in closed form.
    `segments` is [(start_time, value)], starting at t = 0 from steady state."""

    def __init__(self, segments, tau):
        self.segments = segments
        self.tau = max(tau, _MIN_TAU)
        self.starts = []
        x = segments[0][1]
        for i, (t0, u) in enumerate(segments):
            self.starts.append(x)
            if i + 1 < len(segments):
                x = u + (x - u) * math.exp(-(segments[i + 1][0] - t0) / self.tau)

    def index(self, t):
        i = 0
        while i + 1 < len(self.segments) and self.segments[i + 1][0] <= t:
            i += 1
        return i

    def raw(self, t):
        return self.segments[self.index(t)][1]

    def at(self, t):
        i = self.index(t)
        t0, u = self.segments[i]
        return u + (self.starts[i] - u) * math.exp(-(t - t0) / self.tau)

    def next_change(self, t, levels):
        """The first time after `t` at which the filtered value crosses one of
        `levels`, or the input steps - whichever is sooner."""
        i = self.index(t)
        t0, u = self.segments[i]
        x0 = self.starts[i]
        x = self.at(t)
        best = self.segments[i + 1][0] if i + 1 < len(self.segments) else math.inf
        for level in levels:
            if min(x, u) < level < max(x, u):
                crossing = t0 + self.tau * math.log((x0 - u) / (level - u))
                # At a crossing, rounding can put x a hair on the old side of
                # the level it has just reached; that crossing is not "next".
                if crossing > t + _TIME_EPS:
                    best = min(best, crossing)
        return best


def _run_logic(sig, under_stages, over_stages, window, reconnect, fcease, frecon,
               trip_delay, reconnect_delay, horizon, first_trip_only=False):
    """Run the cease/reconnect state machine on the filtered signal `sig`.

    under_stages/over_stages: [(threshold, delay)]; armed while the filtered
    value is strictly below/above the threshold. window: (low, high), the
    open interval the reconnect timer needs. reconnect: {"under"|"over":
    (delay, ramp)}. Returns the FRACON breakpoints and every trip/reconnect."""
    stages = [("under", v, d) for v, d in under_stages] + [("over", v, d) for v, d in over_stages]
    levels = sorted({v for _k, v, _d in stages} | set(window))
    low, high = window
    final_on = 1.0 - fcease * (1.0 - frecon)

    t = 0.0
    mode = "on"  # on | tripped | ramping
    fracon = 1.0
    stage_started = [None] * len(stages)
    reconnect_started = None
    trip_kind = None
    ramp = None  # (start, end, from, to)
    fracon_points = [(0.0, 1.0)]
    trips, reconnects = [], []

    while t < horizon:
        t_change = sig.next_change(t, levels)
        # Nothing crosses a level inside (t, t_change), so the predicates there
        # are those at any interior point.
        probe = sig.at(t + min(t_change - t, sig.tau) / 2.0)
        if fcease > 0 and mode != "tripped":
            for i, (kind, v, _d) in enumerate(stages):
                armed = probe < v if kind == "under" else probe > v
                if not armed:
                    stage_started[i] = None
                elif stage_started[i] is None:
                    stage_started[i] = t
        if mode == "tripped":
            if low < probe < high:
                if reconnect_started is None:
                    reconnect_started = t
            else:
                reconnect_started = None

        candidates = [t_change, horizon]
        trip_at = [
            (start + d + trip_delay, i) for i, ((_k, _v, d), start) in enumerate(zip(stages, stage_started))
            if start is not None
        ]
        if trip_at:
            candidates.append(min(trip_at)[0])
        if reconnect_started is not None:
            candidates.append(reconnect_started + reconnect[trip_kind][0] + reconnect_delay)
        if ramp is not None:
            candidates.append(ramp[1])
        t_next = max(min(candidates), t)

        if trip_at and min(trip_at)[0] <= t_next + _TIME_EPS:
            when, i = min(trip_at)
            if ramp is not None:  # tripped mid-ramp: FRACON is where the ramp had got to
                fracon = ramp[2] + (ramp[3] - ramp[2]) * (when - ramp[0]) / max(ramp[1] - ramp[0], _TIME_EPS)
                ramp = None
            fracon_points += [(when, fracon), (when, 1.0 - fcease)]
            fracon = 1.0 - fcease
            mode, trip_kind = "tripped", stages[i][0]
            trips.append({"time": when, "kind": trip_kind, "stage": i})
            stage_started = [None] * len(stages)
            reconnect_started = None
            t = when
            if first_trip_only or len(trips) >= _MAX_TRIPS:
                break
            continue
        if reconnect_started is not None and \
                reconnect_started + reconnect[trip_kind][0] + reconnect_delay <= t_next + _TIME_EPS:
            start = reconnect_started + reconnect[trip_kind][0] + reconnect_delay
            end = start + max(reconnect[trip_kind][1], 0.0)
            ramp = (start, end, fracon, final_on)
            reconnects.append({"start": start, "end": end})
            fracon_points.append((start, fracon))
            mode, reconnect_started = "ramping", None
            t = start
            continue
        if ramp is not None and ramp[1] <= t_next + _TIME_EPS:
            fracon = ramp[3]
            fracon_points.append((ramp[1], fracon))
            t, ramp, mode = ramp[1], None, "on"
            continue

        if t_change == math.inf and not any(s is not None for s in stage_started) \
                and reconnect_started is None and ramp is None:
            break  # settled for good: online, or tripped outside the window
        t = t_next

    return {"fracon_points": fracon_points, "trips": trips, "reconnects": reconnects,
            "tripped_at_end": mode == "tripped", "cycling": len(trips) >= _MAX_TRIPS}


def _fracon_at(points, t):
    """FRACON at `t` from its breakpoints (linear between, right-continuous at
    a step)."""
    value = points[0][1]
    for (t0, v0), (t1, v1) in itertools.pairwise(points):
        if t < t0:
            break
        if t1 > t0 and t < t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        value = v1
    return value


def _deadband(x, d):
    return math.copysign(max(abs(x) - d, 0.0), x)


def _power_trace(p, volt, freq, fracon_points, key_times, sim_end):
    """P(t) from the current-order loop, sampled finely for a few time
    constants after each event and sparsely where nothing moves."""
    lfm = _con(p, "LFM")
    ipmax, ipmin = _con(p, "IPMAXA"), _con(p, "IPMINA")
    npa, droopa, dba = p["NPA"], _con(p, "DROOPA"), _con(p, "DBA")
    tra = max(p.get("TRA", 0.02), _MIN_TAU)
    pref = min(1.0, ipmax / lfm)

    def target(t):
        vf = max(volt.at(t), 1e-3)
        droop = droopa * _deadband(freq.at(t) - NOMINAL_FREQUENCY_HZ, dba) / NOMINAL_FREQUENCY_HZ
        order = pref * vf ** npa * (1.0 + droop) * lfm / vf
        return _fracon_at(fracon_points, t) * min(max(order, ipmin), ipmax)

    settle = 10.0 * max(tra, volt.tau, freq.tau)
    step = max(min(tra, volt.tau, freq.tau) / 4.0, settle / 400.0)
    grid = {0.0, sim_end}
    for k in key_times:
        if 0.0 <= k <= sim_end:
            n = int(settle / step)
            grid.update(min(k + j * step, sim_end) for j in range(n + 1))
    for (t0, _v0), (t1, _v1) in itertools.pairwise(fracon_points):
        if t1 - t0 > step:  # a ramp: enough points to draw the line and the lag
            grid.update(t0 + (t1 - t0) * j / 40.0 for j in range(41))
    grid = sorted(g for g in grid if 0.0 <= g <= sim_end)
    steps_at = {t0 for t0, _u in volt.segments[1:]}

    ip = target(0.0)
    points = [(0.0, volt.raw(0.0) * ip / lfm)]
    for a, b in itertools.pairwise(grid):
        n = max(1, min(200, math.ceil((b - a) / step)))
        h = (b - a) / n
        for j in range(n):
            ip += (target(a + j * h) - ip) * (1.0 - math.exp(-h / tra))
        if b in steps_at:  # the voltage steps here and P with it; Ip cannot
            points.append((b, volt.raw(a) * ip / lfm))
        points.append((b, volt.raw(b) * ip / lfm))
    return points, pref


def _first_trip_hold(build_logic, hold_cap):
    """The shortest event duration that trips, by bisection, or None."""
    if not build_logic(hold_cap)["trips"]:
        return None
    lo, hi = 0.0, hold_cap
    for _ in range(40):
        mid = (lo + hi) / 2.0
        lo, hi = (lo, mid) if build_logic(mid)["trips"] else (mid, hi)
    return hi


def _response(p, kind, fault_duration_s, level, recovery_level):
    fcease, frecon = p["FCEASE"], p["FRECON"]
    fault_end = FAULT_START + fault_duration_s
    trip_delay, reconnect_delay = _con(p, "CMTDELAY"), _con(p, "CMTDELAYC")

    if kind == "voltage":
        nominal = 1.0
        under = [(p[v], p[d]) for v, d in UNDERVOLTAGE_STAGE_CONS]
        over = [(p[v], p[d]) for v, d in OVERVOLTAGE_STAGE_CONS]
        window = (p["VRPA"], _con(p, "VRUPA"))
        reconnect = {"under": (p["TDRA"], p["RAMPA"]), "over": (_con(p, "TRUPA"), _con(p, "RAMPUA"))}
        tau = _con(p, "TVM")
    else:
        nominal = NOMINAL_FREQUENCY_HZ
        under = [(_con(p, UNDERFREQUENCY_TRIP_CONS[0]), _con(p, UNDERFREQUENCY_TRIP_CONS[1]))]
        over = [(_con(p, OVERFREQUENCY_TRIP_CONS[0]), _con(p, OVERFREQUENCY_TRIP_CONS[1]))]
        window = (_con(p, UNDERFREQUENCY_RECONNECT_CONS[0]), _con(p, OVERFREQUENCY_RECONNECT_CONS[0]))
        reconnect = {"under": tuple(_con(p, n) for n in UNDERFREQUENCY_RECONNECT_CONS[1:]),
                     "over": tuple(_con(p, n) for n in OVERFREQUENCY_RECONNECT_CONS[1:])}
        tau = _con(p, "TFRQ")

    longest_trip = max(d for _v, d in under + over) + trip_delay
    longest_reconnect = max(d + r for d, r in reconnect.values()) + reconnect_delay
    settle = 20.0 * max(tau, _MIN_TAU)

    def logic(duration, first_trip_only=False):
        end = FAULT_START + duration
        sig = _Filtered([(0.0, nominal), (FAULT_START, level), (end, recovery_level)], tau)
        horizon = end + settle + (_MAX_TRIPS + 1) * (longest_trip + longest_reconnect) + 1.0
        return _run_logic(sig, under, over, window, reconnect, fcease, frecon,
                          trip_delay, reconnect_delay, horizon, first_trip_only), sig

    result, _sig = logic(fault_duration_s)
    trips, reconnects = result["trips"], result["reconnects"]

    # For a ride-through: the shortest hold of this level that WOULD trip
    # (None if the level never arms a stage).
    armed_requirement = None
    if not trips and fcease > 0:
        armed_requirement = _first_trip_hold(
            lambda d: logic(d, first_trip_only=True)[0], longest_trip + settle + 1.0)

    if trips:
        last = max([trips[-1]["time"]] + [r["end"] for r in reconnects])
        if result["tripped_at_end"] and not result["cycling"]:
            # Show the time a reconnect would have needed, so "stays tripped"
            # is visibly past it.
            delay, ramp = reconnect[trips[-1]["kind"]]
            last = max(last, fault_end + delay + reconnect_delay + ramp)
        sim_end = last + max(0.5, last * 0.1)
    else:
        sim_end = fault_end + (1.0 if kind == "voltage" else max(1.0, fault_duration_s * 0.1))
    sim_end = max(sim_end, fault_end + settle)

    volt_segments = [(0.0, 1.0), (FAULT_START, level), (fault_end, recovery_level)] if kind == "voltage" \
        else [(0.0, 1.0)]
    freq_segments = [(0.0, nominal), (FAULT_START, level), (fault_end, recovery_level)] if kind == "frequency" \
        else [(0.0, NOMINAL_FREQUENCY_HZ)]
    volt = _Filtered(volt_segments, _con(p, "TVM"))
    freq = _Filtered(freq_segments, _con(p, "TFRQ"))
    key_times = [FAULT_START, fault_end] + [tr["time"] for tr in trips] + \
        [x for r in reconnects for x in (r["start"], r["end"])]
    p_points, pref = _power_trace(p, volt, freq, result["fracon_points"], key_times, sim_end)

    trip_type = None
    if trips:
        names = {"voltage": {"under": "undervoltage", "over": "overvoltage"},
                 "frequency": {"under": "underfrequency", "over": "overfrequency"}}[kind]
        trip_type = names[trips[0]["kind"]]
    markers = {}
    if trips:
        markers["trip_time"] = trips[0]["time"]
        if reconnects:
            markers["reconnect_start"] = reconnects[0]["start"]
            markers["reconnect_end"] = reconnects[0]["end"]

    stays_tripped = result["tripped_at_end"] and not result["cycling"]
    stays_tripped_reason = None
    if stays_tripped:
        low, high = window
        unit = "pu" if kind == "voltage" else "Hz"
        names = ("VRPA", "VRUPA") if kind == "voltage" else (UNDERFREQUENCY_RECONNECT_CONS[0],
                                                            OVERFREQUENCY_RECONNECT_CONS[0])
        fmt = "{:.2f}"
        stays_tripped_reason = (
            f"recovers to {fmt.format(recovery_level)} {unit}, not strictly inside the reconnect window "
            f"{names[0]} {fmt.format(low)} - {names[1]} {fmt.format(high)} {unit}"
        )

    nominal_points = [(0.0, nominal), (FAULT_START, nominal), (FAULT_START, level),
                      (fault_end, level), (fault_end, recovery_level), (sim_end, recovery_level)]
    response = {
        "event_kind": kind,
        "p_points": p_points,
        "trips": bool(trips),
        "trip_type": trip_type,
        "fault_start": FAULT_START,
        "fault_end": fault_end,
        "fault_duration_s": fault_duration_s,
        "sim_end": sim_end,
        "markers": markers,
        # Only meaningful when trips is False: None if this level doesn't arm
        # any stage at all; otherwise the shortest hold that WOULD trip it,
        # including the measurement-filter lag.
        "armed_required_delay_s": armed_requirement,
        # Every trip and reconnect, in order: more than one when the block
        # cycles (VRPA below a stage voltage).
        "trip_events": trips,
        "reconnect_events": reconnects,
        "reconnects": bool(reconnects) and not stays_tripped,
        "stays_tripped_reason": stays_tripped_reason,
        # Trips again after reconnecting, for as long as the level holds:
        # the reconnect window overlaps a trip stage (VRPA below VDPA).
        "cycles": len(trips) > 1,
        # The power the block holds before the event: below 1.0 when
        # IPMAXA < LFM, because it cannot draw its own power-flow load.
        "initial_power_pu": pref,
    }
    if kind == "voltage":
        response.update(v_points=nominal_points, fault_voltage_pu=level)
    else:
        response.update(v_points=[(0.0, 1.0), (sim_end, 1.0)], f_points=nominal_points,
                        fault_frequency_hz=level)
    return response


def _voltage_response(p, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                            recovery_voltage_pu=1.0):
    """Voltage steps to `fault_voltage_pu` (a sag or a swell) at FAULT_START,
    holds for `fault_duration_s`, then returns to `recovery_voltage_pu`."""
    return _response(p, "voltage", fault_duration_s, fault_voltage_pu, recovery_voltage_pu)


def _frequency_response(p, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                      fault_frequency_hz=FREQUENCY_EVENT_HZ,
                                      recovery_frequency_hz=NOMINAL_FREQUENCY_HZ):
    """The frequency-side counterpart of _voltage_response(): frequency
    steps to `fault_frequency_hz`, holds for `fault_duration_s`, then returns
    to `recovery_frequency_hz`. The DLL has ONE frequency trip point per
    direction (FUFTP1/TUFTP1, FOFTP1/TOFTP1); stages 2-4 are ignored even when
    set. Power follows the droop while the block is online."""
    return _response(p, "frequency", fault_duration_s, fault_frequency_hz, recovery_frequency_hz)


MC_KINDS = {"mc_under": "low-voltage momentary cessation", "mc_over": "high-voltage momentary cessation"}


def perc1_equivalent(cons) -> dict:
    """The PERC1 DLL CONs that behave like `cons` on v2.3 with momentary cessation off: RAMPA and RAMPUA in seconds,
    LFM as the DLL uses it (0.8 below 0.001), negative delays as 0."""
    p = dict(cons)
    p["LFM"] = effective_lfm(cons)
    for n in ("TDRA", "TRUPA", "TUFRN1", "TOFRN1", "CMTDELAY", "CMTDELAYC", "TBLK", "TDELY"):
        p[n] = max(float(cons[n]), 0.0)  # the DLL treats a negative delay as 0 (validation finding 8)
    for n in RAMP_CONS:
        p[n] = ramp_seconds(cons, n)
    return p


def mc_active(cons) -> bool:
    return flag_on(cons, "MCFLAG") and float(cons["FCEASE"]) > 0


def _run_mc_logic(sig, stages, windows, reconnect, fcease, frecon, trip_delay, reconnect_delay, horizon,
               first_trip_only=False):
    """The cease/reconnect state machine on the filtered voltage `sig`.

    stages: [(kind, threshold, delay)], kind "under"/"over" (stage trips, delayed by trip_delay) or "mc_under"/
    "mc_over" (momentary cessation, delay 0, not delayed). windows/reconnect: per kind, the open interval the reconnect
    timer needs and (delay, ramp). reconnect_delay (CMTDELAYC) applies to the stage kinds only."""
    levels = sorted({v for _k, v, _d in stages} | {x for w in windows.values() for x in w})
    final_on = 1.0 - fcease * (1.0 - frecon)

    t = 0.0
    mode = "on"  # on | ceased | ramping
    fracon = 1.0
    stage_started = [None] * len(stages)
    reconnect_started = None
    kind = None
    ramp = None  # (start, end, from, to)
    fracon_points = [(0.0, 1.0)]
    trips, reconnects = [], []

    def extra(k):
        return 0.0 if k.startswith("mc") else reconnect_delay

    while t < horizon:
        t_change = sig.next_change(t, levels)
        probe = sig.at(t + min(t_change - t, sig.tau) / 2.0)
        for i, (k, v, _d) in enumerate(stages):
            # A trip stops every timer. During a cessation the stage timers run on (and the MC checks are moot).
            live = mode != "ceased" or (kind.startswith("mc") and not k.startswith("mc"))
            armed = live and (probe < v if k.endswith("under") else probe > v)
            if not armed:
                stage_started[i] = None
            elif stage_started[i] is None:
                stage_started[i] = t
        if mode == "ceased":
            low, high = windows[kind]
            if low < probe < high:
                if reconnect_started is None:
                    reconnect_started = t
            else:
                reconnect_started = None

        candidates = [t_change, horizon]
        trip_at = [(start + d + (0.0 if k.startswith("mc") else trip_delay), i)
                   for i, ((k, _v, d), start) in enumerate(zip(stages, stage_started)) if start is not None]
        if trip_at:
            candidates.append(min(trip_at)[0])
        if reconnect_started is not None:
            candidates.append(reconnect_started + reconnect[kind][0] + extra(kind))
        if ramp is not None:
            candidates.append(ramp[1])
        t_next = max(min(candidates), t)

        if trip_at and min(trip_at)[0] <= t_next + _TIME_EPS:
            when, i = min(trip_at)
            if ramp is not None:  # ceased mid-ramp: FracOn is where the ramp had got to
                fracon = ramp[2] + (ramp[3] - ramp[2]) * (when - ramp[0]) / max(ramp[1] - ramp[0], _TIME_EPS)
                ramp = None
            new_kind = stages[i][0]
            if mode != "ceased":
                fracon_points += [(when, fracon), (when, 1.0 - fcease)]
                fracon = 1.0 - fcease
            trips.append({"time": when, "kind": new_kind, "stage": i, "escalated": mode == "ceased"})
            mode, kind = "ceased", new_kind
            stage_started = [None] * len(stages)
            reconnect_started = None
            t = when
            if first_trip_only or len(trips) >= _MAX_TRIPS:
                break
            continue
        if reconnect_started is not None and reconnect_started + reconnect[kind][0] + extra(kind) <= t_next + _TIME_EPS:
            start = reconnect_started + reconnect[kind][0] + extra(kind)
            end = start + max(reconnect[kind][1], 0.0)
            ramp = (start, end, fracon, final_on)
            reconnects.append({"start": start, "end": end, "kind": kind})
            fracon_points.append((start, fracon))
            mode, reconnect_started = "ramping", None
            t = start
            continue
        if ramp is not None and ramp[1] <= t_next + _TIME_EPS:
            fracon = ramp[3]
            fracon_points.append((ramp[1], fracon))
            t, ramp, mode = ramp[1], None, "on"
            continue

        if t_change == math.inf and not any(s is not None for s in stage_started) \
                and reconnect_started is None and ramp is None:
            break
        t = t_next

    return {"fracon_points": fracon_points, "trips": trips, "reconnects": reconnects,
            "tripped_at_end": mode == "ceased", "cycling": len(trips) >= _MAX_TRIPS, "final_kind": kind}


def _mc_voltage_response(c, fault_duration_s, level, recovery_level):
    """A voltage event with momentary cessation on (`_response` with the v2.3 logic)."""
    fcease, frecon = float(c["FCEASE"]), float(c["FRECON"])
    fault_end = FAULT_START + fault_duration_s
    trip_delay, reconnect_delay = float(c["CMTDELAY"]), float(c["CMTDELAYC"])
    stages = ([("under", c[v], c[d]) for v, d in UNDERVOLTAGE_STAGE_CONS]
              + [("over", c[v], c[d]) for v, d in OVERVOLTAGE_STAGE_CONS]
              + [("mc_under", c["VLBLK"], 0.0), ("mc_over", c["VUBLK"], 0.0)])
    stage_window = (c["VRPA"], c["VRUPA"])
    mc_window = (c["VLRCMC"], c["VURCMC"])
    windows = {"under": stage_window, "over": stage_window, "mc_under": mc_window, "mc_over": mc_window}
    mc_delay = max(c["TBLK"], 0.0) + max(c["TDELY"], 0.0)
    reconnect = {"under": (c["TDRA"], c["RAMPA"]), "over": (c["TRUPA"], c["RAMPUA"]),
                 "mc_under": (mc_delay, c["RAMPAMC"]), "mc_over": (mc_delay, c["RAMPUAMC"])}
    tau = c["TVM"]
    longest_trip = max(d for _k, _v, d in stages) + trip_delay
    longest_reconnect = max(d + r for d, r in reconnect.values()) + reconnect_delay
    settle = 20.0 * max(tau, _MIN_TAU)

    def logic(duration, first_trip_only=False):
        end = FAULT_START + duration
        sig = _Filtered([(0.0, 1.0), (FAULT_START, level), (end, recovery_level)], tau)
        horizon = end + settle + (_MAX_TRIPS + 1) * (longest_trip + longest_reconnect) + 1.0
        return _run_mc_logic(sig, stages, windows, reconnect, fcease, frecon, trip_delay, reconnect_delay, horizon,
                          first_trip_only), sig

    result, _sig = logic(fault_duration_s)
    trips, reconnects = result["trips"], result["reconnects"]
    armed_requirement = None
    if not trips and fcease > 0:
        armed_requirement = _first_trip_hold(lambda d: logic(d, first_trip_only=True)[0], longest_trip + settle + 1.0)

    stays = result["tripped_at_end"] and not result["cycling"]
    if trips:
        last = max([trips[-1]["time"]] + [r["end"] for r in reconnects])
        if stays:
            delay, ramp = reconnect[result["final_kind"]]
            last = max(last, fault_end + delay + ramp + (0.0 if result["final_kind"].startswith("mc") else
                                                          reconnect_delay))
        sim_end = last + max(0.5, last * 0.1)
    else:
        sim_end = fault_end + 1.0
    sim_end = max(sim_end, fault_end + settle)

    volt = _Filtered([(0.0, 1.0), (FAULT_START, level), (fault_end, recovery_level)], tau)
    freq = _Filtered([(0.0, NOMINAL_FREQUENCY_HZ)], c["TFRQ"])
    key_times = [FAULT_START, fault_end] + [tr["time"] for tr in trips] + \
        [x for r in reconnects for x in (r["start"], r["end"])]
    p_points, pref = _power_trace(c, volt, freq, result["fracon_points"], key_times, sim_end)

    names = {"under": "undervoltage", "over": "overvoltage", **MC_KINDS}
    markers = {}
    if trips:
        markers["trip_time"] = trips[0]["time"]
        if reconnects:
            markers["reconnect_start"] = reconnects[0]["start"]
            markers["reconnect_end"] = reconnects[0]["end"]
    reason = None
    if stays:
        k = result["final_kind"]
        low, high = windows[k]
        pair = ("VLRCMC", "VURCMC") if k.startswith("mc") else ("VRPA", "VRUPA")
        reason = (f"recovers to {recovery_level:.2f} pu, not strictly inside the reconnect window "
                  f"{pair[0]} {low:.2f} - {pair[1]} {high:.2f} pu")
    nominal_points = [(0.0, 1.0), (FAULT_START, 1.0), (FAULT_START, level), (fault_end, level),
                      (fault_end, recovery_level), (sim_end, recovery_level)]
    return {
        "event_kind": "voltage",
        "p_points": p_points,
        "v_points": nominal_points,
        "fault_voltage_pu": level,
        "trips": bool(trips),
        "trip_type": names[trips[0]["kind"]] if trips else None,
        "fault_start": FAULT_START,
        "fault_end": fault_end,
        "fault_duration_s": fault_duration_s,
        "sim_end": sim_end,
        "markers": markers,
        "armed_required_delay_s": armed_requirement,
        "trip_events": trips,
        "reconnect_events": reconnects,
        "reconnects": bool(reconnects) and not stays,
        "stays_tripped_reason": reason,
        "cycles": sum(1 for tr in trips if not tr["escalated"]) > 1,
        "initial_power_pu": pref,
        # A cessation that a stage trip took over: it reconnects on the stage path, not TBLK/RAMPAMC.
        "escalated": any(tr["escalated"] for tr in trips),
    }


def simulate_perc2_dll_response(cons, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                                recovery_voltage_pu=1.0):
    """Voltage steps to `fault_voltage_pu` at FAULT_START, holds for `fault_duration_s`, returns to
    `recovery_voltage_pu`."""
    p = perc1_equivalent(cons)
    if not mc_active(cons):
        return _voltage_response(p, fault_duration_s, fault_voltage_pu, recovery_voltage_pu)
    return _mc_voltage_response({k: (float(v) if not isinstance(v, str) else v) for k, v in p.items()},
                             fault_duration_s, fault_voltage_pu, recovery_voltage_pu)


def simulate_perc2_dll_frequency_response(cons, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                          fault_frequency_hz=FREQUENCY_EVENT_HZ,
                                          recovery_frequency_hz=NOMINAL_FREQUENCY_HZ):
    """A held frequency (the voltage stays at 1.0 pu, so momentary cessation never acts). The DLL measures frequency
    against 60 Hz whatever ICON(M) says."""
    return _frequency_response(perc1_equivalent(cons), fault_duration_s, fault_frequency_hz,
                                             recovery_frequency_hz)


__all__ = [
    "MC_KINDS",
    "OVERFREQUENCY_RECONNECT_CONS",
    "OVERFREQUENCY_TRIP_CONS",
    "OVERVOLTAGE_STAGE_CONS",
    "UNDERFREQUENCY_RECONNECT_CONS",
    "UNDERFREQUENCY_TRIP_CONS",
    "UNDERVOLTAGE_STAGE_CONS",
    "mc_active",
    "perc1_equivalent",
    "simulate_perc2_dll_frequency_response",
    "simulate_perc2_dll_response",
]
