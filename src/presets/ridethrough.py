"""Ride-through parameterization preset library.

This is a **library**, not a derivation function: every preset below is a literal,
self-contained record, independent of any other preset's numbers. A preset entry should be readable
and auditable on its own, with nothing implicit borrowed from elsewhere. Each preset's page,
``docs/user/presets/<id>.md``, cites the source of every number; ``docs/developer/ADDING_A_PRESET.md``
describes the design.

Three generic tiers (Extended / Standard / Minimal) are transcribed from
``docs/user/parameter_tiers.md`` §1-2. Grid-operator/reliability-standard ride-through
envelopes - ERCOT (NOGRR282, PUCT-approved), PJM (proposed), MISO (draft), SPP (published
HILL ride-through curve), NERC LLWG SAR (pre-standard proposal), and NERC PRC-029-1
(FERC-approved, generation/IBR-side) - are transcribed from the sources cited on their
preset pages. None of these envelopes are derived from or mapped onto
ITIC/CBEMA; each is its own independently-sourced set of voltage/duration breakpoints.
ITIC is a 1970s-era equipment power-quality tolerance curve, not a bulk-power-system
reliability standard, and this app's live plot no longer draws or compares against it at
all (see §9.1) - every preset here is now a fully self-contained, two-sided ride-through
envelope (`envelope` for the undervoltage floor, `overvoltage_envelope` for the
overvoltage ceiling), and panel 3 of the live chart draws only the selected preset's own
tolerance region, auto-scaled to it. PRC-029-1 in particular governs generator/IBR
ride-through, not load ride-through - it is included as the actual industry comparison
benchmark (this is exactly how PJM's own proposal deck uses it, benchmarking ERCOT/
MISO's LOAD curves against it), not because a data center's load model is itself bound
by it.

Frequency ride-through is a separate, optional table per preset
(`frequency_ride_through`). Only presets whose source publishes a complete
frequency table carry one (PJM's proposal and NERC PRC-029-1); every other
preset leaves it None and exports the vendor-typical frequency CONs unchanged.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from load_models.perc1_dll.cons import (
    PERC1_FIXED_DEFAULTS,
    frequency_stage_cons,
    voltage_stage_cons,
)


@dataclass(frozen=True)
class RideThroughStep:
    """One row of a standard's ride-through table: below `voltage_pu`, the facility
    is only required to hold on for `min_duration_s` before tripping is permitted.
    `min_duration_s=None` means "continuous" - must never trip on voltage alone.

    The same class is reused for a preset's `overvoltage_envelope` (ascending
    voltage_pu there too), just read as the mirror-image statement: up to
    `voltage_pu`, the facility must tolerate the swell for at least
    `min_duration_s` before tripping is permitted; `None` again means the
    continuous-operation ceiling - see `presets.envelope.overvoltage_segments_from_steps`."""

    voltage_pu: float
    min_duration_s: float | None


@dataclass(frozen=True)
class FrequencyBand:
    """One mandatory row of a frequency ride-through table: between the band's
    inner edge (the continuous band, or the previous row's `limit_hz`) and
    `limit_hz`, the facility must ride through for at least `min_duration_s`.
    Beyond the outermost row's `limit_hz`, tripping is permitted immediately."""

    limit_hz: float
    min_duration_s: float


@dataclass(frozen=True)
class FrequencyRideThrough:
    """A standard's frequency ride-through table. `continuous_low_hz` to
    `continuous_high_hz` must be ridden through indefinitely; `underfrequency`
    and `overfrequency` list the mandatory rows from the continuous band
    outward (e.g. PRC-029-1: 58.8-61.2 Hz continuous, then 57.0 Hz / 61.8 Hz
    for 299 s, then may trip). `source` cites where the numbers came from."""

    continuous_low_hz: float
    continuous_high_hz: float
    underfrequency: tuple[FrequencyBand, ...]
    overfrequency: tuple[FrequencyBand, ...]
    source: str

    def bound(self, direction: str, duration_s: float) -> float:
        """The frequency the facility must ride through down to
        (`direction="under"`) or up to (`"over"`) for an event lasting
        `duration_s`: the outermost row still in force at that duration, else
        the continuous band's edge."""
        if direction == "under":
            in_force = [band.limit_hz for band in self.underfrequency if band.min_duration_s > duration_s]
            return min(in_force, default=self.continuous_low_hz)
        in_force = [band.limit_hz for band in self.overfrequency if band.min_duration_s > duration_s]
        return max(in_force, default=self.continuous_high_hz)

    def trip_permitted(self, frequency_hz: float, duration_s: float) -> bool:
        """Whether a constant `frequency_hz` held `duration_s` may trip."""
        if frequency_hz < self.continuous_low_hz:
            return frequency_hz < self.bound("under", duration_s)
        if frequency_hz > self.continuous_high_hz:
            return frequency_hz > self.bound("over", duration_s)
        return False

    def segments(self, direction: str, t_max: float) -> list[tuple[float, float, float]]:
        """(t0, t1, frequency) segments of the boundary, for plotting."""
        bands = self.underfrequency if direction == "under" else self.overfrequency
        breakpoints = sorted({0.0, *(band.min_duration_s for band in bands if band.min_duration_s < t_max)})
        edges = [*breakpoints, t_max]
        return [(t0, t1, self.bound(direction, t0)) for t0, t1 in itertools.pairwise(edges)]


def frequency_trip_points(table: FrequencyRideThrough) -> tuple[tuple, tuple]:
    """The single (frequency_hz, delay_s) trip point per direction PERC1 can
    hold (FUFTP1/TUFTP1 and FOFTP1/TOFTP1 - the vendor model has one frequency
    stage, not four). Each arms at the continuous band's edge with the
    innermost row's duration: e.g. PRC-029-1 -> trip below 58.8 Hz or above
    61.2 Hz once held 299 s. That never trips inside a zone the table requires
    riding through (every row has expired by then, so the whole band beyond
    the edge is trip-permitted), and it does not trip earlier than required
    further out - riding through longer than required is always compliant.
    It is the frequency counterpart of `collapsed_point()` for voltage's
    single Option-1 point."""

    def point(bands, continuous_edge):
        if not bands:
            raise ValueError("a frequency table needs at least one mandatory row per direction")
        return continuous_edge, max(band.min_duration_s for band in bands)

    return (point(table.underfrequency, table.continuous_low_hz),
            point(table.overfrequency, table.continuous_high_hz))


@dataclass(frozen=True)
class RideThroughPreset:
    id: str
    label: str
    category: str  # "Generic" | "Grid operator standard"
    status: str  # "Adopted (internal)" | "Adopted (PUCT-approved)" | "Adopted (published)" | "Proposed" | "Draft"
    citation: str
    # One line naming the source, for UI subtitles; `citation` is the full record.
    short_source: str
    envelope: list[RideThroughStep]  # undervoltage floor, sorted low -> high voltage_pu
    overvoltage_envelope: list[RideThroughStep]  # overvoltage ceiling, sorted low -> high voltage_pu
    overcurrent_pu: float | None
    recovery: str
    it_bundle: dict[str, float | int]
    vfd_bundle: dict[str, float | int]
    # None when the source publishes no frequency ride-through table; the
    # bundles then keep PERC1_FIXED_DEFAULTS' vendor-typical frequency CONs.
    frequency_ride_through: FrequencyRideThrough | None = None


def collapsed_point(envelope: list[RideThroughStep]) -> RideThroughStep:
    """Collapse a multi-step envelope into the single (voltage_pu, min_duration_s)
    point PERC1's Option-1 cease/reconnect logic needs: the shallowest (highest-
    voltage) mandatory row - the step immediately below the continuous-operation
    floor. This is deliberately conservative.

    Takes the envelope list directly (not a `RideThroughPreset`) so it can be
    called while a preset is still being *built* - see `_shared_bundle()` /
    `_generic_bundles()` below, which derive `VDPA`/`DMA` from a preset's own
    `envelope` this way instead of a second, separately hand-typed number that
    could silently drift from it.

    This is stage 1 of `multi_stage_undervoltage()`'s own 4-stage result -
    kept as its own function because `_bundle()`'s `VDPA`/`DMA` (Option 1's
    own point, which every preset exposes regardless of how many real
    envelope tiers it has) is still meaningfully "the" single point for
    anything that only cares about one number (e.g. the live-preview chart's
    pass/fail banner)."""
    mandatory = [step for step in envelope if step.min_duration_s is not None]
    if not mandatory:
        return envelope[0]
    return max(mandatory, key=lambda step: step.voltage_pu)


def collapsed_overvoltage_point(overvoltage_envelope: list[RideThroughStep]) -> RideThroughStep:
    """The overvoltage-side mirror of collapsed_point() - with one necessary
    twist undervoltage doesn't need. Read literally, a row like ERCOT's
    "up to 1.20 pu: must tolerate for at least 2.0 s" states a requirement for
    the whole BAND between the continuous ceiling (1.10 pu) and that row's own
    voltage (1.20 pu) - not a threshold that itself only starts mattering at
    1.20 pu. PERC1's own VDUA/TDUA mechanism is a simple "trip if V exceeds
    VDUA for TDUA seconds" timer, so reproducing that band correctly means
    arming AT the band's own lower edge (the continuous ceiling, 1.10 pu) with
    the row's own duration (2.0 s) - not at the row's own upper voltage
    (1.20 pu), which would leave the entire 1.10-1.20 pu band permanently
    unable to trip no matter how long it's held. (On the undervoltage side
    this twist isn't needed only because ERCOT's own table happens to state
    the continuous floor and the shallowest mandatory row as the exact same
    number, 0.90 pu - overvoltage's continuous ceiling and shallowest
    mandatory row are two different published numbers, 1.10 and 1.20.)

    If a preset has no finite overvoltage tier (the three generic tiers,
    plus NERC LLWG SAR - no published temporal figure exists for them), falls
    back to the flat continuous ceiling itself (`min_duration_s=None`), same
    fallback shape as collapsed_point() - callers must supply an explicit
    override for `TDUA` in that case; there is no meaningful duration to
    derive.

    Stage 1 of `multi_stage_overvoltage()`'s own 4-stage result - see
    `collapsed_point()`'s docstring for why it stays a separate function."""
    mandatory = [step for step in overvoltage_envelope if step.min_duration_s is not None]
    if not mandatory:
        return overvoltage_envelope[0]
    ordered_all = sorted(overvoltage_envelope, key=lambda step: step.voltage_pu)
    shallowest = min(mandatory, key=lambda step: step.voltage_pu)
    idx = ordered_all.index(shallowest)
    arming_voltage = ordered_all[idx - 1].voltage_pu if idx > 0 else shallowest.voltage_pu
    return RideThroughStep(arming_voltage, shallowest.min_duration_s)


def multi_stage_undervoltage(envelope: list[RideThroughStep]) -> list[tuple[float, float]]:
    """Map a preset's own undervoltage envelope onto up to 4 Option-3 stage
    breakpoints - (VDPA, DMA), (VDPA1, DMA1), (VDPA2, DMA2), (VDPA3, DMA3), in
    that order - for `load_models.perc1_dll.cons.voltage_stage_cons()`.

    Why this exists: testing confirmed, via direct PSS/E
    simulation against the real compiled PERC2_V35.dll, that the DLL always
    evaluates all 4 undervoltage stages - there is no way to drive "Option 1
    only." Every preset's own `envelope` here already IS a multi-tier
    ride-through curve (up to 5 `RideThroughStep`s, the last one the
    continuous-operation floor) - this function is what actually puts that
    real data into the CONs the DLL evaluates, instead of leaving stages 2-4
    at PERC1_FIXED_DEFAULTS' vendor-sample values (which do not represent any
    of this preset's own published numbers).

    Takes every *mandatory* (finite-duration) row, sorted shallowest-first
    (matching `collapsed_point()` - stage 1 here is always identical to
    `collapsed_point(envelope)`), and pads to exactly 4 stages by repeating
    the deepest defined tier's own (voltage, duration) - this was directly
    validated in PSS/E (in the PSS/E validation library, which is not
    published): a repeated stage fires at the exact same time
    as the tier it copies, so it cannot introduce a different, earlier trip
    condition. Raises ValueError if the envelope has more than 4 mandatory
    tiers - the model has exactly 4 undervoltage stages and there is no
    correct way to silently drop one; re-tier the envelope instead."""
    mandatory = [step for step in envelope if step.min_duration_s is not None]
    if not mandatory:
        step = envelope[0]
        duration = step.min_duration_s if step.min_duration_s is not None else 0.0
        return [(step.voltage_pu, duration)] * 4
    ordered = sorted(mandatory, key=lambda step: step.voltage_pu, reverse=True)
    if len(ordered) > 4:
        raise ValueError(
            f"envelope has {len(ordered)} mandatory tiers; PERC1's Option-3 table only "
            "has 4 undervoltage stages - collapse or re-tier this envelope"
        )
    stages = [(step.voltage_pu, step.min_duration_s) for step in ordered]
    while len(stages) < 4:
        stages.append(stages[-1])
    return stages


def _pad_overvoltage_stages(stages: list[tuple[float, float]], anchor_voltage: float) -> list[tuple[float, float]]:
    """Pad to exactly 4 stages by appending `(anchor_voltage, 0.0)` entries -
    `anchor_voltage` is always the highest published tier's own voltage
    (e.g. ERCOT's 1.20 pu), never a higher, invented one. Every standard in
    this library is explicit that anything above its own highest published
    tier is an immediate trip condition, not a slower/graduated one (ERCOT
    NOGRR282 says it plainly: "above 1.20 pu: may ride through or trip").
    No other voltage/duration is assumed."""
    extended = list(stages)
    while len(extended) < 4:
        extended.append((anchor_voltage, 0.0))
    return extended


def multi_stage_overvoltage(
    overvoltage_envelope: list[RideThroughStep], tdua_override: float | None = None
) -> list[tuple[float, float]]:
    """The overvoltage-side mirror of `multi_stage_undervoltage()`: maps a
    preset's own `overvoltage_envelope` onto up to 4 Option-3 stage
    breakpoints - (VDUA, TDUA), (VDUA1, TDUA1), (VDUA2, TDUA2), (VDUA3, TDUA3).

    Stage 1 is always identical to
    `collapsed_overvoltage_point(overvoltage_envelope)` - see that function's
    own docstring for why its arming VOLTAGE is the continuous ceiling (e.g.
    1.10 pu), not the published tier's own upper voltage (1.20 pu): a row
    like "up to 1.20 pu: tolerate for at least 2.0 s" describes the whole
    band above the continuous ceiling, and PERC1's simple "trip if V exceeds
    VDUA for TDUA seconds" mechanism can only reproduce that band by arming
    at its lower edge. Stages 2-4 pad with `(tier's own voltage, 0.0)` via
    `_pad_overvoltage_stages()` - every preset in this library publishes at
    most one real overvoltage tier and is explicit that anything above it is
    an immediate trip condition. If there is no finite mandatory tier at all
    (a flat continuous ceiling - the three generic tiers, plus NERC LLWG
    SAR), stage 1 itself uses the `tdua_override`-derived point (exactly
    mirroring `collapsed_overvoltage_point()`'s own fallback) and stages 2-4
    still pad the same way, anchored to that same ceiling voltage (there is
    no separate published tier to anchor to instead)."""
    mandatory = [step for step in overvoltage_envelope if step.min_duration_s is not None]
    if not mandatory:
        step = overvoltage_envelope[0]
        if step.min_duration_s is not None:
            duration = step.min_duration_s
        elif tdua_override is not None:
            duration = tdua_override
        else:
            raise ValueError("overvoltage_envelope has no finite mandatory tier - tdua_override is required")
        return _pad_overvoltage_stages([(step.voltage_pu, duration)], step.voltage_pu)
    ordered_all = sorted(overvoltage_envelope, key=lambda step: step.voltage_pu)
    mandatory_ordered = sorted(mandatory, key=lambda step: step.voltage_pu)
    if len(mandatory_ordered) > 4:
        raise ValueError(
            f"overvoltage_envelope has {len(mandatory_ordered)} mandatory tiers; PERC1's Option-3 table "
            "only has 4 overvoltage stages - collapse or re-tier this envelope"
        )
    stages = []
    for tier in mandatory_ordered:
        idx = ordered_all.index(tier)
        arming_voltage = ordered_all[idx - 1].voltage_pu if idx > 0 else tier.voltage_pu
        stages.append((arming_voltage, tier.min_duration_s))
    return _pad_overvoltage_stages(stages, mandatory_ordered[-1].voltage_pu)


# Reconnect delay (TDRA/Trecon) and ramp rate (RAMPA/Tramp) are two distinct
# CONs: TDRA is a dwell/confirmation delay before any reconnection is
# committed to (guards against re-triggering on a bouncing/noisy voltage
# signal); RAMPA is how long the actual power ramp takes once it starts. No
# standard in this library splits its published "restore >=X% within N
# seconds of voltage recovery" window into those two components - it's one
# combined figure. Treating the entire window as RAMPA (as an earlier
# revision of this module did) mislabels that combined window as pure ramp
# duration, and produces an implausibly slow, seconds-long linear power ramp
# for equipment that is, by construction, power-electronics-interfaced and
# capable of a much faster response once cleared to reconnect.
#
# SPP is the one standard in this library that actually publishes a number in
# that "fast, power-electronics-plausible" range on its own terms (5 cycles,
# ~0.083 s - see docs/user/presets/spp_hill.md). This app reuses that
# figure as its own realistic ramp-rate benchmark for every other
# grid-operator preset too: RAMPA is fixed at this value, and the remainder
# of each standard's own published recovery window is assigned to TDRA as the
# confirmation/dwell delay. This is an app-chosen split, not a per-standard
# citation, for every preset except SPP itself - see each preset's own
# "Reconnection behavior" doc section.
REALISTIC_POWER_ELECTRONICS_RAMP_S = 0.083


def _bundle(undervoltage_stages, fcease, vrpa, tdra, rampa, frecon, npa, nqa, ipmaxa=1.0, overvoltage_stages=None,
            frequency_ride_through=None):
    """Build a complete PERC1_DISPLAY_FIELDS-shaped CON dict for a preset, starting
    from PERC1_FIXED_DEFAULTS (the same base as the model's PERC1_DEFAULT_CONS) and
    overriding the core cease/reconnect and ZIP fields explicitly, one preset at a time.

    `undervoltage_stages`/`overvoltage_stages` are each a list of exactly 4
    (voltage_pu, duration_s) tuples - see `multi_stage_undervoltage()`/
    `multi_stage_overvoltage()` above and `load_models.perc1_dll.cons.voltage_stage_cons()`, which
    actually writes them into VDPA/DMA + VDPA1-3/DMA1-3 and VDUA/TDUA +
    VDUA1-3/TDUA1-3. Every call site below passes its own preset's real
    multi-tier envelope this way instead of a single hand-typed point, so a
    preset's exported trip behavior actually reflects its own `envelope`/
    `overvoltage_envelope` on every stage the compiled DLL evaluates - not
    just the one stage (VDPA/DMA or VDUA/TDUA) this app used to drive before
    PSS/E testing confirmed the DLL always evaluates all 4.
    `overvoltage_stages` defaults to PERC1_FIXED_DEFAULTS' own shared point
    (1.10 pu / 0.5 s) repeated 4 times if not given."""
    if overvoltage_stages is None:
        overvoltage_stages = [(1.10, 0.50)] * 4
    params = dict(PERC1_FIXED_DEFAULTS)
    params.update(voltage_stage_cons(undervoltage_stages, overvoltage_stages))
    if frequency_ride_through is not None:
        underfrequency_stage, overfrequency_stage = frequency_trip_points(frequency_ride_through)
        params.update(frequency_stage_cons(
            underfrequency_stage, overfrequency_stage,
            reconnect_low_hz=frequency_ride_through.continuous_low_hz,
            reconnect_high_hz=frequency_ride_through.continuous_high_hz,
        ))
    params.update(
        {
            "FCEASE": fcease,
            "VRPA": vrpa,
            "TDRA": tdra,
            "RAMPA": rampa,
            "FRECON": frecon,
            "NPA": npa,
            "NQA": nqa,
            "TRA": 0.02,
            "IPMAXA": ipmaxa,
        }
    )
    return params


def _collapse_envelopes(envelope, overvoltage_envelope, tdua_override=None):
    """Shared derivation step for `_shared_bundle()`/`_generic_bundles()`: map a
    preset's own `envelope`/`overvoltage_envelope` onto the full 4-stage
    Option-3 breakpoint lists `_bundle()` needs, via
    `multi_stage_undervoltage()`/`multi_stage_overvoltage()`, instead of a
    single hand-typed `(vdpa, dma, vdua, tdua)` point - a second, independent
    representation of "this preset's trip point" that could silently drift
    from the envelope table it's supposedly summarizing (this happened for
    real, repeatedly, to the envelope tables themselves - see e.g.
    ercot_nogrr282.md and miso_draft.md's "Known caveats" - so the same risk
    on the CON side is not hypothetical). Both callers pass the exact same
    `envelope`/`overvoltage_envelope` list objects they also assign to the
    preset's own dataclass fields, so the exported CONs and the documented/
    plotted envelope are now structurally guaranteed to agree, not just
    conventionally kept in sync by hand.

    Returns `(vdpa, dma, vdua, tdua, undervoltage_stages, overvoltage_stages)`
    - the first four are stage 1 alone (identical to
    `collapsed_point()`/`collapsed_overvoltage_point()`, kept for callers that
    still just need one number, e.g. per-block DMA overrides), the last two
    are the full 4-stage lists for `_bundle()`.

    `tdua_override` is required whenever `overvoltage_envelope` has no finite
    mandatory tier (a flat continuous ceiling, `min_duration_s=None` - the three
    generic tiers, plus NERC LLWG SAR): PERC1 needs an actual finite `TDUA`, and
    there is no meaningful duration to derive in that case - see
    `multi_stage_overvoltage()`'s own docstring."""
    undervoltage_stages = multi_stage_undervoltage(envelope)
    overvoltage_stages = multi_stage_overvoltage(overvoltage_envelope, tdua_override)
    vdpa, dma = undervoltage_stages[0]
    vdua, tdua = overvoltage_stages[0]
    return vdpa, dma, vdua, tdua, undervoltage_stages, overvoltage_stages


def _shared_bundle(envelope, overvoltage_envelope, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                    ipmaxa=1.0, tdua_override=None, frequency_ride_through=None):
    """Build one CON bundle - with the full 4-stage undervoltage/overvoltage
    tables derived from the preset's own envelope, via `_collapse_envelopes()`
    - and use it for both `it_bundle` and `vfd_bundle`.

    Every grid-operator standard in this library regulates the facility's
    overall large-load ride-through, not IT vs. cooling-VFD separately - so
    for those presets `it_bundle` and `vfd_bundle` are always identical, and
    Screening (which only ever reads `it_bundle` - it models a single
    computational-load PERC1 block, not a facility composition with separate
    cooling blocks) only ever needs the one value anyway. This helper derives
    the bundle exactly once and returns both dataclass kwargs pointing at the
    same dict, so there is structurally nothing to drift - spread with
    `**_shared_bundle(...)` at each grid-operator preset's call site.

    The three generic tiers (Extended/Standard/Minimal) are the only presets
    that genuinely need different IT/VFD numbers (a different `DMA` trip
    delay per block, from docs/user/parameter_tiers.md §1) - they use
    `_generic_bundles()` instead."""
    _vdpa, _dma, _vdua, _tdua, undervoltage_stages, overvoltage_stages = _collapse_envelopes(
        envelope, overvoltage_envelope, tdua_override
    )
    bundle = _bundle(undervoltage_stages, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                      ipmaxa=ipmaxa, overvoltage_stages=overvoltage_stages,
                      frequency_ride_through=frequency_ride_through)
    return {"it_bundle": bundle, "vfd_bundle": bundle}


def _generic_bundles(envelope, overvoltage_envelope, vfd_dma, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                      ipmaxa=1.0, tdua_override=None):
    """Like `_shared_bundle()`, but for the three generic tiers, where the
    cooling-VFD block is deliberately given a longer trip delay (`vfd_dma`) than
    the IT block - a genuine, intentional per-block difference (see
    docs/user/parameter_tiers.md §1), not a hand-typed duplicate of the envelope's own
    collapsed point.

    `VDUA`/`TDUA` (and every overvoltage stage) are still derived once, via
    `_collapse_envelopes()`, and shared by both blocks. `VDPA`/`DMA` genuinely
    differ between IT and VFD - and so, correspondingly, do their Option-3
    stages 2-4: the generic tiers only ever have exactly one real published
    undervoltage breakpoint (a qualitative tier, not a cited multi-row
    standard), so `multi_stage_undervoltage()` would return that single point
    repeated 4 times at whichever DMA `_collapse_envelopes()` happened to
    compute (the IT block's own) - correct for IT, but wrong for VFD, which
    needs `vfd_dma` repeated instead, not IT's `it_dma`. There is no separate
    published VFD-specific multi-tier table to encode here, so VFD's own
    stages 2-4 simply repeat its own (vdpa, vfd_dma) point, the same
    validated-safe "repeat, don't invent a new number" pattern used
    everywhere else in this module."""
    vdpa, _it_dma, _vdua, _tdua, undervoltage_stages, overvoltage_stages = _collapse_envelopes(
        envelope, overvoltage_envelope, tdua_override
    )
    it_bundle = _bundle(undervoltage_stages, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                         ipmaxa=ipmaxa, overvoltage_stages=overvoltage_stages)
    vfd_bundle = _bundle([(vdpa, vfd_dma)] * 4, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                         ipmaxa=ipmaxa, overvoltage_stages=overvoltage_stages)
    return {"it_bundle": it_bundle, "vfd_bundle": vfd_bundle}


def _standard_preset(*, id, label, short_source, status, citation, envelope, overvoltage_envelope, overcurrent_pu, recovery,
                      fcease, vrpa, tdra, rampa, frecon, npa, nqa, ipmaxa=1.0, tdua_override=None,
                      frequency_ride_through=None) -> RideThroughPreset:
    """Construct a "Grid operator standard" preset. `envelope`/`overvoltage_envelope`
    are each passed exactly once here and reused for both the dataclass's own
    fields and the CON derivation (`_shared_bundle()`) - the whole point of this
    factory: there is no second, independently-typed copy of the envelope for
    the exported VDPA/DMA/VDUA/TDUA to silently drift from."""
    return RideThroughPreset(
        id=id,
        label=label,
        category="Grid operator standard",
        status=status,
        citation=citation,
        short_source=short_source,
        envelope=envelope,
        overvoltage_envelope=overvoltage_envelope,
        overcurrent_pu=overcurrent_pu,
        recovery=recovery,
        frequency_ride_through=frequency_ride_through,
        **_shared_bundle(envelope, overvoltage_envelope, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                          ipmaxa=ipmaxa, tdua_override=tdua_override,
                          frequency_ride_through=frequency_ride_through),
    )


def _generic_preset(*, id, label, short_source, citation, envelope, overvoltage_envelope, vfd_dma,
                     fcease, vrpa, tdra, rampa, frecon, npa, nqa, ipmaxa=1.0, tdua_override=None) -> RideThroughPreset:
    """Construct one of the three generic tiers (Extended/Standard/Minimal) - same
    single-source-of-truth reasoning as `_standard_preset()`, but via
    `_generic_bundles()` since the cooling-VFD block genuinely needs its own
    `vfd_dma`."""
    return RideThroughPreset(
        id=id,
        label=label,
        category="Generic",
        status="Adopted (internal)",
        citation=citation,
        short_source=short_source,
        envelope=envelope,
        overvoltage_envelope=overvoltage_envelope,
        overcurrent_pu=None,
        recovery="n/a",
        **_generic_bundles(envelope, overvoltage_envelope, vfd_dma, fcease, vrpa, tdra, rampa, frecon, npa, nqa,
                            ipmaxa=ipmaxa, tdua_override=tdua_override),
    )


RIDE_THROUGH_PRESETS: dict[str, RideThroughPreset] = {
    "extended": _generic_preset(
        id="extended",
        label="Extended (ITI/CBEMA-plus)",
        short_source="Internal engineering tiering (Generic parameter tiers, §1)",
        citation="Internal engineering tiering - see the Generic parameter tiers page, §1",
        envelope=[RideThroughStep(0.50, 0.10)],
        overvoltage_envelope=[RideThroughStep(1.20, None)],
        vfd_dma=0.20,
        fcease=1.00, vrpa=0.70, tdra=60.0, rampa=30.0, frecon=1.00, npa=0, nqa=0,
        tdua_override=0.50,
    ),
    "standard_itic": _generic_preset(
        id="standard_itic",
        label="Standard (ITIC/CBEMA)",
        short_source="Internal engineering tiering (Generic parameter tiers, §1)",
        citation="Internal engineering tiering - see the Generic parameter tiers page, §1",
        envelope=[RideThroughStep(0.70, 0.02)],
        overvoltage_envelope=[RideThroughStep(1.10, None)],
        vfd_dma=0.10,
        fcease=1.00, vrpa=0.90, tdra=60.0, rampa=30.0, frecon=1.00, npa=0, nqa=0,
        tdua_override=0.50,
    ),
    "minimal": _generic_preset(
        id="minimal",
        label="Minimal / unknown",
        short_source="Internal engineering tiering (Generic parameter tiers, §1)",
        citation="Internal engineering tiering - see the Generic parameter tiers page, §1",
        envelope=[RideThroughStep(0.85, 0.01)],
        overvoltage_envelope=[RideThroughStep(1.05, None)],
        vfd_dma=0.02,
        fcease=1.00, vrpa=0.95, tdra=60.0, rampa=30.0, frecon=1.00, npa=1, nqa=1,
        tdua_override=0.50,
    ),
    "spp_hill": _standard_preset(
        id="spp_hill",
        label="SPP (HILL ride-through curve)",
        short_source="SPP High Impact Large Load Ride-Through Requirements v0.1, Table 1",
        status="Adopted (published)",
        citation="SPP, \"High Impact Large Load Ride-Through Requirements\" v0.1 "
        "(published 8/15/2025), Table 1 - read directly from the filed requirements "
        "document, not a derived/secondary chart. Table 1's own voltage tiers, "
        "confirmed by direct text extraction (0.50/0.80/0.90/1.10 pu undervoltage; "
        "1.10-1.20 pu overvoltage tier at 0.5 s). See this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.50, 0.15),
            RideThroughStep(0.80, 0.50),
            RideThroughStep(0.90, 2.00),
            RideThroughStep(1.10, None),
        ],
        overvoltage_envelope=[
            RideThroughStep(1.10, None),
            RideThroughStep(1.20, 0.50),
        ],
        overcurrent_pu=None,
        recovery="Constant-current (not constant-power) control required during "
        "disturbances; below 0.5 pu, load may transfer fully to UPS but must "
        "restore >=90% of pre-disturbance consumption within 5 cycles (~0.083 s) "
        "of V recovering to >=0.9 pu.",
        # TDRA=0.0/RAMPA=0.083 (5 cycles): SPP's own recovery clause - see
        # docs/user/presets/spp_hill.md's "Reconnect timing" section.
        # VDPA/DMA/VDUA/TDUA are all derived from envelope/overvoltage_envelope above.
        fcease=1.00, vrpa=0.90, tdra=0.0, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S, frecon=1.00, npa=1, nqa=1,
    ),
    "ercot_nogrr282": _standard_preset(
        id="ercot_nogrr282",
        label="ERCOT (NOGRR282)",
        short_source="ERCOT NOGRR282, Nodal Operating Guide §2.14, Table A",
        status="Adopted (PUCT-approved)",
        citation="ERCOT NOGRR282, \"Large Electronic Load Ride-Through Requirements\" "
        "(filed Nov 14, 2025), Nodal Operating Guide §2.14, Table A - read directly "
        "from the filed guide-language text, not a secondary chart. Proportional "
        "power-reduction allowance for the 0.50-0.80 pu band is unrestricted only "
        "for LELs approved after Jan 1, 2028; earlier LELs get an interim allowance. "
        "See this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.20, 0.15),
            RideThroughStep(0.50, 0.25),
            RideThroughStep(0.80, 0.50),
            RideThroughStep(0.90, 2.00),
            RideThroughStep(1.10, None),
        ],
        overvoltage_envelope=[
            RideThroughStep(1.10, None),
            RideThroughStep(1.20, 2.00),
        ],
        overcurrent_pu=1.25,
        recovery="May reduce active power for V<0.8 pu (proportional to the voltage "
        "drop, per a phase-in schedule through Jan 1, 2028); must restore >=90% of "
        "pre-disturbance P within 1 s of V returning above 0.9 pu. Current during "
        "any disturbance outside the continuous band must not exceed 125% of "
        "normal max.",
        # TDRA=0.917/RAMPA=0.083: ERCOT's own 1.0 s recovery window, split into
        # a confirmation dwell (TDRA) and this app's realistic power-electronics
        # ramp-rate benchmark (RAMPA) - see
        # docs/user/presets/ercot_nogrr282.md's "Reconnect timing" section.
        # VDPA/DMA/VDUA/TDUA are all derived from envelope/overvoltage_envelope above.
        fcease=1.00, vrpa=1.00, tdra=1.0 - REALISTIC_POWER_ELECTRONICS_RAMP_S, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S,
        frecon=1.00, npa=0, nqa=0, ipmaxa=1.25,
    ),
    "pjm_lcl": _standard_preset(
        id="pjm_lcl",
        label="PJM (LCL proposal)",
        short_source="PJM LCL Ride-through Requirements proposal (Sep 8, 2026), slide 5",
        status="Proposed",
        citation="PJM Planning Committee, \"PJM LCL Ride-through Requirements - PJM "
        "Interconnection Proposal\" (David Egan, Byoungkon Choi; Sep 8, 2026), slide 5 "
        "- read from the deck's own text layer, not a pixel-traced chart. Only two "
        "breakpoints are numerically marked on PJM's own envelope (0.25 s / 0.35 pu); "
        "the 0.35-0.90 pu band is drawn as one continuous, non-trip zone since PJM's "
        "slide states no additional trip allowance there. Driven by FERC Docket "
        "EL26-67-000 (Show Cause Order, Jun 18, 2026); FERC filing targeted Nov 2026. "
        "See this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.35, 0.25),
            RideThroughStep(0.90, None),
        ],
        overvoltage_envelope=[
            RideThroughStep(1.10, None),
            RideThroughStep(1.20, 1.00),
        ],
        overcurrent_pu=1.50,
        recovery="May reduce P proportional to voltage drop; must restore >=90% of "
        "pre-disturbance P within 2 s of V returning above 0.9 pu (and below 1.1 pu); "
        "cooling load allowed to trip for V<0.35 pu; overcurrent during a sag capped "
        "at 150% of normal max.",
        # TDRA=1.917/RAMPA=0.083: PJM's own 2.0 s recovery window, split into
        # a confirmation dwell (TDRA) and this app's realistic power-electronics
        # ramp-rate benchmark (RAMPA) - see
        # docs/user/presets/pjm_lcl.md's "Reconnect timing" section.
        # VDPA/DMA/VDUA/TDUA are all derived from envelope/overvoltage_envelope above.
        fcease=1.00, vrpa=1.00, tdra=2.0 - REALISTIC_POWER_ELECTRONICS_RAMP_S, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S,
        frecon=1.00, npa=0, nqa=0, ipmaxa=1.50,
        frequency_ride_through=FrequencyRideThrough(
            continuous_low_hz=58.8,
            continuous_high_hz=61.2,
            underfrequency=(FrequencyBand(57.0, 299.0),),
            overfrequency=(FrequencyBand(61.8, 299.0),),
            source="PJM LCL proposal (Sep 8, 2026 deck): continuous 58.8-61.2 Hz; may ride "
            "through down to 57.0 Hz / up to 61.8 Hz for up to 299 s while holding "
            "consumption within 10% of pre-disturbance level. See this preset's page in the Documentation tab.",
        ),
    ),
    "miso_draft": _standard_preset(
        id="miso_draft",
        label="MISO (draft)",
        short_source="MISO draft envelope, via PJM LCL deck (Sep 8, 2026), slide 11",
        status="Draft",
        citation="MISO Voltage Ride-through Envelope (draft), as reproduced in PJM "
        "Planning Committee, \"PJM LCL Ride-through Requirements\" (Sep 8, 2026), "
        "slide 11 - re-verified by tracing the slide's own vector-drawn curve "
        "coordinates (not OCR/pixel-reading), cross-checked against the axis "
        "gridlines the deck itself labels (0.15 s is a real gridline on this slide; "
        "0.25 s is not - a prior revision of this preset incorrectly borrowed an "
        "extra 0.20/0.25 tier from ERCOT's shape that MISO's own curve does not "
        "have). The traced curve has one early riser (0 -> ~0.5 pu at ~0.15 s), not "
        "two. Timing/voltage both approximate to the chart's gridline resolution; "
        "confirm against MISO's own draft document before relying on it for a real "
        "study. See this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.50, 0.15),
            RideThroughStep(0.80, 0.50),
            RideThroughStep(0.90, 2.00),
            RideThroughStep(1.10, None),
        ],
        overvoltage_envelope=[
            RideThroughStep(1.10, None),
            RideThroughStep(1.20, 0.50),
        ],
        overcurrent_pu=None,
        recovery="≥90% of pre-disturbance P within 1 s of V returning above 0.9 pu "
        "(stricter than ERCOT/PJM's 2 s), unless studies demonstrate a slower recovery "
        "is necessary for BES reliability.",
        # TDRA=0.917/RAMPA=0.083: MISO's own 1.0 s recovery window, split into
        # a confirmation dwell (TDRA) and this app's realistic power-electronics
        # ramp-rate benchmark (RAMPA) - see
        # docs/user/presets/miso_draft.md's "Reconnect timing" section.
        # VDPA/DMA/VDUA/TDUA are all derived from envelope/overvoltage_envelope above.
        fcease=1.00, vrpa=1.00, tdra=1.0 - REALISTIC_POWER_ELECTRONICS_RAMP_S, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S,
        frecon=1.00, npa=1, nqa=1,
    ),
    "nerc_llwg_sar": _standard_preset(
        id="nerc_llwg_sar",
        label="NERC LLWG SAR (pre-standard proposal)",
        short_source="NERC LLWG envelope, via PJM LCL deck (Sep 8, 2026), slides 12-13",
        status="Proposed",
        citation="NERC Reliability and Security Technical Committee (RSTC), Large Load "
        "Working Group (LLWG) computational-load disturbance-performance envelope, as "
        "reproduced in PJM Planning Committee, \"PJM LCL Ride-through Requirements\" "
        "(Sep 8, 2026), slides 12-13 - traced from the slide's own vector-drawn curve "
        "coordinates. This is NOT yet an adopted NERC Reliability Standard: the "
        "companion NERC SAR (\"Reliability Standards to Address Computational Load - "
        "Phase I,\" filed Feb 20, 2026) is still in the glossary/registration-criteria "
        "scoping stage, with the actual voltage/frequency ride-through requirement "
        "standard development explicitly deferred to a later phase extending through "
        "2027 - this envelope is NERC's own working proposal for what that standard "
        "may look like, not a filed or binding number. Overvoltage ceiling (~1.15 pu) "
        "is drawn flat with no interior step visible in the slide's 4 s window. See "
        "this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.50, 0.25),
            RideThroughStep(0.80, 0.50),
            RideThroughStep(0.90, 2.00),
            RideThroughStep(1.10, None),
        ],
        overvoltage_envelope=[RideThroughStep(1.15, None)],
        overcurrent_pu=None,
        recovery="Not specified in the slide beyond the shape of the envelope itself - "
        "no post-fault active-power recovery timing is shown for this proposal. This "
        "preset's own TDRA/RAMPA are therefore an app-chosen default (ERCOT NOGRR282's "
        "1.0 s recovery window), not a NERC-published number - see "
        "this preset's page in the Documentation tab.",
        # TDRA=0.917/RAMPA=0.083: no recovery timing is published for this proposal;
        # ERCOT's own 1.0 s window is used as a realistic default (this proposal's
        # trip envelope is itself modeled on ERCOT's shape), split into a
        # confirmation dwell (TDRA) and this app's realistic power-electronics
        # ramp-rate benchmark (RAMPA) - see
        # docs/user/presets/nerc_llwg_sar.md's "Reconnect timing" section.
        # VDPA/DMA are derived from envelope above; overvoltage_envelope has no
        # finite tier (flat ceiling), so TDUA needs the explicit override below.
        fcease=1.00, vrpa=1.00, tdra=1.0 - REALISTIC_POWER_ELECTRONICS_RAMP_S, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S,
        frecon=1.00, npa=1, nqa=1, tdua_override=0.50,
    ),
    "nerc_prc029": _standard_preset(
        id="nerc_prc029",
        label="NERC PRC-029-1 (IBR reference - not a load standard)",
        short_source="NERC PRC-029-1, Attachment 1 Table 2 and Attachment 2 Table 3",
        status="Adopted (FERC-approved, generator/IBR-side)",
        citation="NERC PRC-029-1, \"Frequency and Voltage Ride-through Requirements for "
        "Inverter-based Resources,\" Table 2 (\"Voltage Ride-through Requirements for "
        "All Other IBR\") - read directly from the Board-adopted standard text (Draft "
        "4_errata, Oct 2024; FERC Order 909 approved this standard Jul 24, 2025; "
        "effective Oct 1, 2026). This is the actual reference curve PJM's own slide 14 "
        "benchmarks ERCOT/MISO/NERC-LLWG-SAR's LOAD ride-through curves against - not "
        "ITIC. It governs generator/inverter-based-resource ride-through, NOT load "
        "ride-through; it is included here purely as that same industry comparison "
        "benchmark, mirroring PJM's own methodology - selecting it does not mean a data "
        "center facility is itself bound by PRC-029-1. Table 2's 1.05-1.10 pu band is "
        "technically 'Continuous Operation' capped at 1800 s (30 min), simplified here "
        "to a flat continuous ceiling at 1.10 pu since 1800 s is far beyond any "
        "duration this app ever simulates or plots. Table 1 (wind-specific IBR) has "
        "different, generally tighter numbers and is not modeled here. See "
        "this preset's page in the Documentation tab.",
        envelope=[
            RideThroughStep(0.25, 0.32),
            RideThroughStep(0.50, 1.20),
            RideThroughStep(0.70, 3.00),
            RideThroughStep(0.90, 6.00),
            RideThroughStep(1.10, None),
        ],
        overvoltage_envelope=[
            RideThroughStep(1.10, None),
            RideThroughStep(1.20, 1.00),
        ],
        overcurrent_pu=None,
        recovery="Real Power restored to pre-disturbance or available level (whichever "
        "is lesser) within 1.0 s of voltage returning from the mandatory/permissive "
        "operation region to the continuous operation region.",
        # TDRA=0.917/RAMPA=0.083: PRC-029-1's own 1.0 s recovery window, split into
        # a confirmation dwell (TDRA) and this app's realistic power-electronics
        # ramp-rate benchmark (RAMPA) - the sum still reaches 100% restored by
        # PRC-029-1's own 1.0 s deadline exactly - see
        # docs/user/presets/nerc_prc029.md's "Reconnect timing" section.
        # VDPA/DMA/VDUA/TDUA are all derived from envelope/overvoltage_envelope above.
        fcease=1.00, vrpa=1.00, tdra=1.0 - REALISTIC_POWER_ELECTRONICS_RAMP_S, rampa=REALISTIC_POWER_ELECTRONICS_RAMP_S,
        frecon=1.00, npa=1, nqa=1,
        frequency_ride_through=FrequencyRideThrough(
            continuous_low_hz=58.8,
            continuous_high_hz=61.2,
            underfrequency=(FrequencyBand(57.0, 299.0),),
            overfrequency=(FrequencyBand(61.8, 299.0),),
            source="NERC PRC-029-1, Attachment 2, Table 3 (\"Frequency Ride-through Capability "
            "Requirements\"): > 61.8 Hz may trip; > 61.2 Hz 299 s; 58.8-61.2 Hz continuous; "
            "< 58.8 Hz 299 s; < 57.0 Hz may trip. Durations are cumulative over a 10-minute "
            "window; RoCoF up to 5 Hz/s must be ridden through (R3) - neither is modeled.",
        ),
    ),
}


PRESET_CATEGORY_ORDER = ["Generic", "Grid operator standard"]


def presets_by_category() -> dict[str, list[RideThroughPreset]]:
    """Group presets by category, preserving insertion order within each group -
    used to build the grouped dropdown (a disabled separator row per category)."""
    grouped: dict[str, list[RideThroughPreset]] = {cat: [] for cat in PRESET_CATEGORY_ORDER}
    for preset in RIDE_THROUGH_PRESETS.values():
        grouped.setdefault(preset.category, []).append(preset)
    return grouped
