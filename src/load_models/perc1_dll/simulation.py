"""PERC1 (DLL) response to a single constant-depth voltage or frequency event.

This is the hand-coded model behind the app's live chart and the mock runner,
not the compiled DLL. It follows the rules the PSS/E behavior probes measured
against `PERC2_V35.dll` (in the PSS/E validation library, which is not published:
744 of 744 checks; summarised in docs/developer/PERC1_MODEL.md, "Measured runtime
behavior"):

- **Measurement.** The trip and reconnect logic sees the voltage through a
  first-order lag `TVM` (VFILT), and the frequency through `TFRQ`.
- **Trip.** Each of the 4 stages per direction runs its own timer while the
  filtered value is strictly beyond its threshold, and resets the moment it
  is not. A stage trips when its timer reaches its delay plus `CMTDELAY`;
  FRACON then steps to 1 - `FCEASE`. Stage timers also run during a
  reconnect ramp.
- **Reconnect.** After a trip the reconnect timer (`TDRA`, `TRUPA`, `TUFRN1`
  or `TOFRN1`, plus `CMTDELAYC`) runs only while the filtered value is
  strictly inside the window (`VRPA`, `VRUPA`) for voltage trips or
  (`FUFRN1`, `FOFRN1`) for frequency trips, and restarts whenever it leaves.
  Once the ramp starts, it runs to the end. `VRPA` below a stage voltage
  therefore makes the block cycle.
- **Power.** A current order Ip lags its target on `TRA`. The target is
  FRACON * clip(Pref * VFILT^NPA * (1 + droop) * LFM / VFILT, IPMINA, IPMAXA),
  with droop = `DROOPA` * db(f - 60, `DBA`) / 60 and Pref = min(1,
  `IPMAXA`/`LFM`). The block draws P = V * Ip / `LFM`. So a constant-power
  block is current-limited in a deep sag, P dips and recovers at sag onset,
  overshoots towards 1/V on recovery, and decays over `TRA` after a trip.

Not modelled: PSS/E's own bus-frequency filter (a study setting, ~0.03 s, in
front of `TFRQ`), the lead-lag/washout blocks (bypassed in every exported
record), the one-time-step discretisation of each event, and Q.
"""

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
from .cons import (
    OVERFREQUENCY_RECONNECT_CONS,
    OVERFREQUENCY_TRIP_CONS,
    PERC1_FIXED_DEFAULTS,
    UNDERFREQUENCY_RECONNECT_CONS,
    UNDERFREQUENCY_TRIP_CONS,
)

# The 4 Option-3 stage CON pairs per direction, stage 1 first - VDPA/DMA and
# VDUA/TDUA are stage 1, the same point Option 1 has always been. Module
# level (not a local literal) so preview/perc1_dll.py and the docs scripts reuse the
# exact same stage ordering the simulator evaluates.
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
    return p[name] if name in p else PERC1_FIXED_DEFAULTS[name]


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


def simulate_perc1_response(p, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT,
                            recovery_voltage_pu=1.0):
    """Voltage steps to `fault_voltage_pu` (a sag or a swell) at FAULT_START,
    holds for `fault_duration_s`, then returns to `recovery_voltage_pu`."""
    return _response(p, "voltage", fault_duration_s, fault_voltage_pu, recovery_voltage_pu)


def simulate_perc1_frequency_response(p, fault_duration_s=FREQUENCY_EVENT_DURATION,
                                      fault_frequency_hz=FREQUENCY_EVENT_HZ,
                                      recovery_frequency_hz=NOMINAL_FREQUENCY_HZ):
    """The frequency-side counterpart of simulate_perc1_response(): frequency
    steps to `fault_frequency_hz`, holds for `fault_duration_s`, then returns
    to `recovery_frequency_hz`. The DLL has ONE frequency trip point per
    direction (FUFTP1/TUFTP1, FOFTP1/TOFTP1); stages 2-4 are ignored even when
    set. Power follows the droop while the block is online."""
    return _response(p, "frequency", fault_duration_s, fault_frequency_hz, recovery_frequency_hz)


def simulate_perc1_event(p, event_kind, fault_duration_s, fault_voltage_pu=V_FAULT,
                         fault_frequency_hz=FREQUENCY_EVENT_HZ):
    """Dispatch to the voltage or frequency simulator by `event_kind`."""
    if event_kind == "frequency":
        return simulate_perc1_frequency_response(p, fault_duration_s, fault_frequency_hz)
    return simulate_perc1_response(p, fault_duration_s, fault_voltage_pu)
