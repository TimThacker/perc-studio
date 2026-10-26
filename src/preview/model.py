"""What the live preview shows for one block and one test event, as plain data.

Qt-free. `build_preview` runs the block's simulator (the PERC1 DLL model, the PERC2 DLL v2.3, the
PERC1 standard model or the PERC2 standard model) once and derives everything the screen needs from that one run, so
the verdict strip, the charts and the facility tiles never disagree:

* the verdict ("TRIPS" / "RIDES THROUGH"), its title and detail line;
* the three figures under the verdict (load tripped, reconnects, ramp);
* the state timeline (online / ceased / reconnecting, with the ceased fraction);
* the comparison with the chosen ride-through preset: whether each trip stage sits
  where the preset permits a trip, and where the event itself falls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from editor.model_ui import (
    DLL_MODEL_ID,
    PERC2_DLL_MODEL_ID,
    PERC2_MODEL_ID,
    STANDARD_MODEL_ID,
    uses_standard_names,
)
from load_models.base import (
    FAULT_DURATION,
    FREQUENCY_EVENT_HZ,
    NOMINAL_FREQUENCY_HZ,
    V_FAULT,
)
from load_models.perc1_dll.cons import OVERFREQUENCY_TRIP_CONS, UNDERFREQUENCY_TRIP_CONS
from load_models.perc1_dll.simulation import (
    OVERVOLTAGE_STAGE_CONS,
    UNDERVOLTAGE_STAGE_CONS,
    simulate_perc1_event,
)
from presets.envelope import (
    envelope_bound,
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
)
from preview.style import format_seconds

ONLINE, CEASED, RECONNECTING = "online", "ceased", "reconnecting"
TRIPS, RIDES_THROUGH = "TRIPS", "RIDES THROUGH"
RIDE_THROUGH_REGION, TRIP_PERMITTED_REGION = "ride_through", "trip_permitted"


@dataclass(frozen=True)
class StateSegment:
    t0: float
    t1: float
    state: str  # ONLINE | CEASED | RECONNECTING
    fraction: float  # the fraction of the block that is off (CEASED) or coming back (RECONNECTING)


@dataclass(frozen=True)
class Event:
    kind: str = "voltage"  # "voltage" | "frequency"
    duration_s: float = FAULT_DURATION
    voltage_pu: float = V_FAULT
    frequency_hz: float = FREQUENCY_EVENT_HZ

    @property
    def level(self) -> float:
        return self.frequency_hz if self.kind == "frequency" else self.voltage_pu


@dataclass
class StandardCheck:
    """The block against the chosen preset for this event's quantity."""

    available: bool  # a preset (and, for frequency, a table) to compare against
    stage_rows: list[tuple[str, bool | None]] = field(default_factory=list)  # (direction, ok); None = not modelled
    pill: str = ""
    pill_ok: bool | None = None
    region: str | None = None  # RIDE_THROUGH_REGION | TRIP_PERMITTED_REGION, where the event falls
    sentence: str = ""


@dataclass
class PreviewResult:
    model_id: str
    params: dict
    event: Event
    sim: dict
    verdict: str
    title: str
    detail: str
    load_tripped: str
    reconnects: str
    ramp: str
    timeline: list[StateSegment]
    fcease: float
    standard: StandardCheck
    block_mw: float | None = None

    @property
    def trips(self) -> bool:
        return self.verdict == TRIPS

    def back_by_s(self) -> float | None:
        """When the block is fully back online (the end of its last ramp); None if it never comes back."""
        if not self.trips:
            return None
        if self.sim.get("stays_tripped_reason") or self.sim.get("cycles"):
            return None
        end = self.sim.get("markers", {}).get("reconnect_end")
        return float(end) if end is not None else None

    def tile_text(self) -> str:
        """The facility-response tile line: "Trips · back by 91 s", "Rides through", "Trips · stays off"."""
        if not self.trips:
            return "Rides through"
        back = self.back_by_s()
        return f"Trips · back by {fmt_seconds(back)}" if back is not None else "Trips · stays off"


# --- formatting ---------------------------------------------------------------------------------------


def fmt_seconds(seconds: float) -> str:
    if seconds is None or math.isinf(seconds):
        return "never"
    return format_seconds(seconds)


def _fmt_plain(seconds: float) -> str:
    return f"{seconds:.2f}" if seconds < 10 else f"{seconds:.0f}"


def _mw(fraction: float, block_mw: float | None) -> str:
    if block_mw is None:
        return f"{fraction * 100:.0f} %"
    return f"{fraction * block_mw:.2f} MW"


def event_title(event: Event, block_label: str | None = None) -> str:
    if event.kind == "frequency":
        f = event.frequency_hz
        kind = "Under-frequency" if f < NOMINAL_FREQUENCY_HZ else "Over-frequency" if f > NOMINAL_FREQUENCY_HZ \
            else "Nominal-frequency"
        text = f"{kind} event: {f:.2f} Hz for {fmt_seconds(event.duration_s)}"
    else:
        cycles = event.duration_s * 60.0
        word = "swell" if event.voltage_pu > 1.0 else "sag"
        text = f"{cycles:g}-cycle {word} to {event.voltage_pu:.2f} pu"
    return f"{block_label} · {text}" if block_label else text


# --- simulation ---------------------------------------------------------------------------------------


def perc2_voltage_points(params: dict) -> list[tuple[float, float, str, str, str]]:
    """PERC2's active voltage cease points as (voltage, delay, "under"|"over", voltage CON, delay CON): the momentary
    checks and the long-table points whose flags are on. Point 3 is timed by point 1's time (TVLC1/TVHC1), as PSS/E
    36.7.1 does. Repeated points (presets pad the tables) appear once."""
    from load_models.perc2_standard.cons import flag_on, long_time_point

    points = []
    if flag_on(params, "VLMflag"):
        points.append((params["VLcease"], max(params["Tcease"], 0.0), "under", "VLcease", "Tcease"))
    if flag_on(params, "VHMflag"):
        points.append((params["VHcease"], max(params["Tcease"], 0.0), "over", "VHcease", "Tcease"))
    for flag, prefix, direction, live in (("VLLflag", "L", "under", lambda v: v > 0),
                                          ("VLHflag", "H", "over", lambda v: v < 90)):
        if flag_on(params, flag):
            for i in (1, 2, 3, 4):
                timer = f"TV{prefix}C{long_time_point(i)}"
                v, d = params[f"V{prefix}C{i}"], max(params[timer], 0.0)
                if live(v):
                    points.append((v, d, direction, f"V{prefix}C{i}", timer))
    seen, unique = set(), []
    for point in points:
        if (point[0], point[1], point[2]) not in seen:
            seen.add((point[0], point[1], point[2]))
            unique.append(point)
    return unique


def perc2_frequency_points(params: dict) -> list[tuple[float, float, str, str, str]]:
    """PERC2's active frequency cease points as (Hz, delay, "under"|"over", frequency CON, delay CON)."""
    from load_models.perc2_standard.cons import flag_on

    points = []
    if flag_on(params, "FLflag"):
        points.append((params["FLC1"], max(params["TFLC1"], 0.0), "under", "FLC1", "TFLC1"))
    if flag_on(params, "FHflag"):
        points.append((params["FHC1"], max(params["TFHC1"], 0.0), "over", "FHC1", "TFHC1"))
    return points


def simulate(model_id: str, params: dict, event: Event) -> dict:
    # The PERC2 DLL v2.3 shares the PERC1 DLL's CON names, so everything below the simulation is the DLL's; its own
    # simulator applies the ramp x LFM rule and momentary cessation.
    if model_id in (PERC2_MODEL_ID, PERC2_DLL_MODEL_ID):
        from load_models import get_load_model

        model = get_load_model(model_id)
        if event.kind == "frequency":
            return model.simulate_frequency(params, event.duration_s, event.frequency_hz)
        return model.simulate(params, event.duration_s, event.voltage_pu)
    if model_id == STANDARD_MODEL_ID:
        from preview.standard import simulate_standard

        return simulate_standard(params, event.duration_s, event.voltage_pu, event.kind, event.frequency_hz)
    return simulate_perc1_event(params, event.kind, event.duration_s, event.voltage_pu, event.frequency_hz)


def cease_fraction(model_id: str, params: dict) -> float:
    return float(params["fcease"] if uses_standard_names(model_id) else params["FCEASE"])


def reconnect_fraction(model_id: str, params: dict) -> float:
    return float(params["frecon"] if uses_standard_names(model_id) else params["FRECON"])


def state_timeline(sim: dict, fcease: float) -> list[StateSegment]:
    """Online until the first trip; ceased from each trip to its reconnect (or to the end when it stays
    off); reconnecting through each ramp; online again after. A cycling block gives several rounds."""
    end = float(sim["sim_end"])
    if not sim.get("trips"):
        return [StateSegment(0.0, end, ONLINE, 0.0)]
    trips = sim.get("trip_events")
    reconnects = sim.get("reconnect_events")
    if trips is None:  # the standard model reports its single cycle as markers
        m = sim["markers"]
        trips = [{"time": m["trip_time"]}]
        reconnects = [{"start": m["reconnect_start"], "end": m["reconnect_end"]}] if "reconnect_start" in m else []
    segments: list[StateSegment] = []
    t = 0.0
    for i, trip in enumerate(trips):
        t_trip = min(float(trip["time"]), end)
        if t_trip > t:
            segments.append(StateSegment(t, t_trip, ONLINE, 0.0))
        if i < len(reconnects):
            start, stop = min(float(reconnects[i]["start"]), end), min(float(reconnects[i]["end"]), end)
            segments.append(StateSegment(t_trip, start, CEASED, fcease))
            if stop > start:
                segments.append(StateSegment(start, stop, RECONNECTING, fcease))
            t = stop
        else:
            segments.append(StateSegment(t_trip, end, CEASED, fcease))
            t = end
    if t < end:
        segments.append(StateSegment(t, end, ONLINE, 0.0))
    return [s for s in segments if s.t1 > s.t0]


def _verdict_detail(model_id: str, sim: dict, params: dict) -> str:
    m = sim.get("markers", {})
    if sim["trips"]:
        trip_type = (sim.get("trip_type") or "").capitalize()
        word = "cease" if uses_standard_names(model_id) else "trip"
        detail = f"{trip_type} {word} at {fmt_seconds(m['trip_time'])}"
        if sim.get("stays_tripped_reason"):
            detail += f" · stays off: {sim['stays_tripped_reason']}"
        elif sim.get("cycles"):
            detail += (f" · cycles: trips {len(sim.get('trip_events', []))} times, because the reconnect window "
                       "overlaps a trip stage")
        elif "reconnect_start" in m:
            detail += f" · reconnects {_fmt_plain(m['reconnect_start'])}–{fmt_seconds(m['reconnect_end'])}"
    elif model_id == PERC2_MODEL_ID and sim["event_kind"] == "frequency" and not perc2_frequency_points(params):
        detail = "Both frequency cease checks are off; only droop responds"
    elif model_id == PERC2_MODEL_ID:
        detail = "This event does not reach any active cease point"
    elif model_id == STANDARD_MODEL_ID and sim["event_kind"] == "frequency":
        detail = "This model has no frequency trip; only droop responds"
    elif model_id == STANDARD_MODEL_ID and sim.get("fault_voltage_pu", 1.0) > 1.0:
        detail = "This model has no overvoltage trip"
    elif sim.get("armed_required_delay_s") is not None and (
            model_id != STANDARD_MODEL_ID or sim.get("fault_voltage_pu", 1.0) < params["Vcease"]):
        detail = f"Would trip only if held {fmt_seconds(sim['armed_required_delay_s'])}"
    else:
        detail = "This level does not reach any trip stage"
    if sim.get("initial_power_pu", 1.0) < 1.0 - 1e-9:
        detail += f" · holds only {sim['initial_power_pu']:.2f} pu before the event (IPMAXA < LFM)"
    if sim.get("psse_nan_hazard"):
        detail += " · PSS/E 36.7.1 would return NaN for this event"
    return detail


# --- the comparison with the preset ------------------------------------------------------------------


def _stage_pill(rows: list[tuple[str, bool | None]]) -> tuple[str, bool | None]:
    judged = [(label, ok) for label, ok in rows if ok is not None]
    if not judged:
        return "Not modelled", None
    if all(ok for _label, ok in judged):
        if len(judged) == 2:
            return "Both stages OK", True
        return f"{judged[0][0]} OK", True
    bad = [label for label, ok in judged if not ok]
    return " and ".join(bad) + " NOT OK", False


def voltage_stage_rows(model_id: str, params: dict, preset) -> list[tuple[str, bool | None]]:
    """Whether each direction's trip stages sit where the preset permits a trip."""
    under = envelope_segments_from_steps(preset.envelope)
    over = overvoltage_segments_from_steps(preset.overvoltage_envelope or [])
    if model_id == STANDARD_MODEL_ID:
        ok = params["Vcease"] <= envelope_bound(under, max(params["Tcease"], 0.0))
        return [("Cease point", ok), ("Overvoltage", None)]
    if model_id == PERC2_MODEL_ID:
        points = perc2_voltage_points(params)
        rows = []
        for label, direction, segments in (("Undervoltage", "under", under), ("Overvoltage", "over", over)):
            mine = [(v, d) for v, d, side, *_names in points if side == direction]
            if not mine:
                rows.append((label, None))
                continue
            rows.append((label, all(v <= envelope_bound(segments, d) if direction == "under"
                                    else v >= envelope_bound(segments, d) for v, d in mine)))
        return rows
    under_ok = all(params[v] <= envelope_bound(under, params[d]) for v, d in UNDERVOLTAGE_STAGE_CONS)
    over_ok = all(params[v] >= envelope_bound(over, params[d]) for v, d in OVERVOLTAGE_STAGE_CONS)
    return [("Undervoltage", under_ok), ("Overvoltage", over_ok)]


def voltage_region(preset, voltage_pu: float, duration_s: float) -> str:
    """Where a voltage event falls on the preset's two-sided envelope."""
    if voltage_pu < 1.0:
        floor = envelope_bound(envelope_segments_from_steps(preset.envelope), duration_s)
        return RIDE_THROUGH_REGION if voltage_pu >= floor - 1e-9 else TRIP_PERMITTED_REGION
    if voltage_pu > 1.0:
        ceiling = envelope_bound(overvoltage_segments_from_steps(preset.overvoltage_envelope or []), duration_s)
        return RIDE_THROUGH_REGION if voltage_pu <= ceiling + 1e-9 else TRIP_PERMITTED_REGION
    return RIDE_THROUGH_REGION


def frequency_stage_rows(model_id: str, params: dict, table) -> list[tuple[str, bool | None]]:
    if model_id == STANDARD_MODEL_ID:
        return [("Frequency trip", None)]
    if model_id == PERC2_MODEL_ID:
        points = {direction: (f, d) for f, d, direction, *_names in perc2_frequency_points(params)}
        rows = []
        for label, direction in (("Under-frequency", "under"), ("Over-frequency", "over")):
            if direction not in points:
                rows.append((label, None))
                continue
            f, d = points[direction]
            bound = table.bound(direction, d)
            rows.append((label, f <= bound if direction == "under" else f >= bound))
        return rows
    rows = []
    for label, direction, (f_name, d_name) in (("Under-frequency", "under", UNDERFREQUENCY_TRIP_CONS),
                                               ("Over-frequency", "over", OVERFREQUENCY_TRIP_CONS)):
        f, d = params[f_name], params[d_name]
        bound = table.bound(direction, d)
        rows.append((label, f <= bound if direction == "under" else f >= bound))
    return rows


def check_against_preset(model_id: str, params: dict, preset, event: Event, trips: bool) -> StandardCheck:
    if preset is None:
        return StandardCheck(False, sentence="Choose a ride-through preset to compare this block against.")
    if event.kind == "frequency":
        table = preset.frequency_ride_through
        if table is None:
            return StandardCheck(False, pill="No frequency table", sentence=(
                f"{preset.label} has no published frequency table, so there is nothing to compare this event "
                "against."))
        rows = frequency_stage_rows(model_id, params, table)
        region = TRIP_PERMITTED_REGION if table.trip_permitted(event.frequency_hz, event.duration_s) \
            else RIDE_THROUGH_REGION
        where = f"Event at {event.frequency_hz:.2f} Hz for {fmt_seconds(event.duration_s)}"
    else:
        rows = voltage_stage_rows(model_id, params, preset)
        region = voltage_region(preset, event.voltage_pu, event.duration_s)
        where = f"Event at {event.voltage_pu:.2f} pu for {event.duration_s:.3f} s"
    pill, pill_ok = _stage_pill(rows)
    if region == TRIP_PERMITTED_REGION:
        sentence = f"{where} falls in the region where tripping is permitted."
    elif trips:
        sentence = (f"{where} falls in the region where {preset.label} requires ride-through, "
                    "and this block trips: it falls short here.")
    else:
        sentence = f"{where} falls in the region where {preset.label} requires ride-through, and this block rides through."
    return StandardCheck(True, rows, pill, pill_ok, region, sentence)


# --- the whole preview -------------------------------------------------------------------------------


def build_preview(model_id: str, params: dict, event: Event, *, preset=None, block_mw: float | None = None,
                  block_label: str | None = None) -> PreviewResult:
    sim = simulate(model_id, params, event)
    fcease = cease_fraction(model_id, params)
    frecon = reconnect_fraction(model_id, params)
    trips = bool(sim["trips"])
    m = sim.get("markers", {})
    if trips:
        load_tripped = _mw(fcease, block_mw)
        if sim.get("stays_tripped_reason") or "reconnect_start" not in m:
            reconnects, ramp = "none", "–"
        else:
            reconnects = _mw(fcease * frecon, block_mw)
            ramp = fmt_seconds(m["reconnect_end"] - m["reconnect_start"])
    else:
        load_tripped, reconnects, ramp = _mw(0.0, block_mw), "–", "–"
    return PreviewResult(
        model_id=model_id, params=params, event=event, sim=sim,
        verdict=TRIPS if trips else RIDES_THROUGH,
        title=event_title(event, block_label),
        detail=_verdict_detail(model_id, sim, params),
        load_tripped=load_tripped, reconnects=reconnects, ramp=ramp,
        timeline=state_timeline(sim, fcease), fcease=fcease,
        standard=check_against_preset(model_id, params, preset, event, trips),
        block_mw=block_mw,
    )


def ceased_label(segment: StateSegment, model_id: str = DLL_MODEL_ID) -> str:
    """The state strip's text for a ceased segment: "Ceased · 100 % (FCEASE 1.00)"."""
    name = "fcease" if uses_standard_names(model_id) else "FCEASE"
    return f"Ceased · {segment.fraction * 100:.0f} % ({name} {segment.fraction:.2f})"
