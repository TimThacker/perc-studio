"""Expected-vs-actual comparison engine: given a ride-through preset's own
envelope and a fault scenario, decide whether a trip is expected, then
compare that against a SimulationResult's actual trip/no-trip outcome.

Reuses presets/envelope.py's pure envelope-geometry helpers
(envelope_segments_from_steps/overvoltage_segments_from_steps/envelope_bound)
unchanged - no duplicated geometry logic.

Also directly operationalizes the question of whether the
compiled PERC1 DLL always evaluates Option 3's stepped trip table): see
MULTISTAGE_UNDERVOLTAGE_PROBE/MULTISTAGE_OVERVOLTAGE_PROBE/evaluate_multistage_probe.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from presets.envelope import (
    envelope_bound,
    envelope_segments_from_steps,
    overvoltage_segments_from_steps,
)
from presets.ridethrough import RideThroughPreset
from psse.runner import FaultScenario, SimulationResult


@dataclass(frozen=True)
class TestPointVerdict:
    scenario_id: str
    block_name: str
    expected_trip: bool
    expected_reason: str
    actual_trip: bool
    actual_trip_time_s: float | None
    passed: bool
    notes: str

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "block_name": self.block_name,
            "expected_trip": self.expected_trip,
            "expected_reason": self.expected_reason,
            "actual_trip": self.actual_trip,
            "actual_trip_time_s": self.actual_trip_time_s,
            "passed": self.passed,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CaseValidationReport:
    case_id: str
    preset_id: str | None
    block_name: str
    points: list
    all_passed: bool
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "preset_id": self.preset_id,
            "block_name": self.block_name,
            "points": [p.to_dict() for p in self.points],
            "all_passed": self.all_passed,
            "metadata": dict(self.metadata),
        }


def expected_trip_for_scenario(preset: RideThroughPreset, scenario: FaultScenario) -> tuple:
    """Undervoltage (fault_voltage_pu < 1.0): the required floor at
    scenario.fault_duration_s, from preset.envelope. Overvoltage
    (fault_voltage_pu > 1.0): the mirror, from preset.overvoltage_envelope.
    Both via presets/envelope.py's pure geometry helpers, reused as-is."""
    if scenario.event_kind == "frequency":
        return _expected_frequency_trip(preset, scenario)
    if scenario.fault_voltage_pu < 1.0:
        segments = envelope_segments_from_steps(preset.envelope)
        bound = envelope_bound(segments, scenario.fault_duration_s)
        expected = scenario.fault_voltage_pu < bound
        reason = (
            f"Undervoltage: {preset.label}'s envelope requires riding through down to "
            f"{bound:.2f} pu for a {scenario.fault_duration_s:.2f}s event. The scenario sags to "
            f"{scenario.fault_voltage_pu:.2f} pu, which is "
            f"{'below' if expected else 'at or above'} that floor, so a trip is "
            f"{'permitted' if expected else 'NOT expected (must ride through)'}."
        )
    elif scenario.fault_voltage_pu > 1.0:
        segments = overvoltage_segments_from_steps(preset.overvoltage_envelope)
        bound = envelope_bound(segments, scenario.fault_duration_s)
        expected = scenario.fault_voltage_pu > bound
        reason = (
            f"Overvoltage: {preset.label}'s envelope requires tolerating swells up to "
            f"{bound:.2f} pu for a {scenario.fault_duration_s:.2f}s event. The scenario swells to "
            f"{scenario.fault_voltage_pu:.2f} pu, which is "
            f"{'above' if expected else 'at or below'} that ceiling, so a trip is "
            f"{'permitted' if expected else 'NOT expected (must ride through)'}."
        )
    else:
        expected = False
        reason = "fault_voltage_pu == 1.0 pu (no disturbance); no trip expected."
    return expected, reason


def _expected_frequency_trip(preset: RideThroughPreset, scenario: FaultScenario) -> tuple:
    """Frequency counterpart of the voltage branches above, against the
    preset's own `frequency_ride_through` table."""
    table = preset.frequency_ride_through
    if table is None:
        raise ValueError(
            f"preset {preset.id!r} publishes no frequency ride-through table, so a frequency "
            "scenario has nothing to validate against"
        )
    f, duration = scenario.fault_frequency_hz, scenario.fault_duration_s
    expected = table.trip_permitted(f, duration)
    if table.continuous_low_hz <= f <= table.continuous_high_hz:
        reason = (f"{f:.2f} Hz is inside {preset.label}'s continuous band "
                  f"({table.continuous_low_hz:.1f}-{table.continuous_high_hz:.1f} Hz); no trip expected.")
    else:
        direction = "under" if f < table.continuous_low_hz else "over"
        bound = table.bound(direction, duration)
        reason = (
            f"{direction.capitalize()}-frequency: {preset.label} requires riding through "
            f"{'down' if direction == 'under' else 'up'} to {bound:.2f} Hz for a {duration:.1f}s event. "
            f"The scenario holds {f:.2f} Hz, so a trip is "
            f"{'permitted' if expected else 'NOT expected (must ride through)'}."
        )
    return expected, reason


def validate_result(preset: RideThroughPreset, scenario: FaultScenario, result: SimulationResult) -> TestPointVerdict:
    expected_trip, reason = expected_trip_for_scenario(preset, scenario)
    passed = expected_trip == result.tripped
    notes = (
        ""
        if passed
        else (
            f"Mismatch: expected_trip={expected_trip}, actual tripped={result.tripped}"
            + (f" at t={result.trip_time_s}s" if result.tripped and result.trip_time_s is not None else "")
        )
    )
    return TestPointVerdict(
        scenario_id=scenario.id,
        block_name=result.block_name,
        expected_trip=expected_trip,
        expected_reason=reason,
        actual_trip=result.tripped,
        actual_trip_time_s=result.trip_time_s,
        passed=passed,
        notes=notes,
    )


def _event_category(scenario: FaultScenario) -> str:
    if scenario.event_kind == "frequency":
        return "frequency"
    return "overvoltage" if scenario.fault_voltage_pu > 1.0 else "undervoltage"


def _apply_model_limits(point: TestPointVerdict, scenario: FaultScenario, model) -> TestPointVerdict:
    """A disturbance the model has no logic for cannot fail the envelope: report it as not modelled."""
    category = _event_category(scenario)
    if category not in model.unmodelled_events or point.passed:
        return point
    return replace(point, passed=True, notes=(
        f"Not modelled: {model.label} has no {category} response, so the expected trip cannot occur in this model."))


def validate_case(case, block_name: str, results, *, preset: RideThroughPreset | None = None) -> CaseValidationReport:
    """`results` is a list of (FaultScenario, SimulationResult) pairs - a
    verdict needs both the scenario (what was expected) and the result (what
    happened). `preset` defaults to ridethrough_presets.RIDE_THROUGH_PRESETS[
    case block's preset_id] when the block's source=="preset"; raises
    ValueError asking the caller to pass it explicitly for a defaults- or
    overrides-sourced block, which has no envelope of its own to validate
    against."""
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    block = case.block(block_name)
    if block is None:
        raise ValueError(f"case {case.case_id!r} has no {block_name} block")

    if preset is None:
        preset_id = getattr(block, "preset_id", None)
        if not preset_id:
            raise ValueError(
                f"case {case.case_id!r}'s {block_name} block has no preset_id "
                f"(source={block.source!r}); pass preset= explicitly to validate "
                "against a specific envelope"
            )
        preset = RIDE_THROUGH_PRESETS[preset_id]

    points = [_apply_model_limits(validate_result(preset, scenario, result), scenario, block.model)
              for scenario, result in results]
    return CaseValidationReport(
        case_id=case.case_id,
        preset_id=preset.id,
        block_name=block_name,
        points=points,
        all_passed=all(p.passed for p in points),
    )


# --- Multi-stage trip table probe ------------------------------------------
# PERC1's "Option 3" (vendor-manual term) is its 4-stage stepped voltage trip
# table (VDPA1-3/DMA1-3, VDUA1-3/TDUA1-3). These probes answered
# whether the compiled DLL always evaluates those
# stages (it does) - and now guard that finding as a regression test.

MULTISTAGE_UNDERVOLTAGE_PROBE = FaultScenario(
    id="multistage_undervoltage_probe",
    fault_start_s=0.5,
    fault_duration_s=0.6,
    fault_voltage_pu=0.75,
    description=(
        "Sag to 0.75pu held 0.6s - establishes whether Option 3's stage-2 "
        "undervoltage tier (VDPA1=0.80pu/DMA1=0.50s, identical in both multi-stage "
        "fixtures) is evaluated at all. VDPA=0.90pu/DMA=2.0s (Option 1's own point, "
        "also identical in both fixtures) would not have tripped yet at 0.6s."
    ),
)
MULTISTAGE_OVERVOLTAGE_PROBE = FaultScenario(
    id="multistage_overvoltage_probe",
    fault_start_s=0.5,
    fault_duration_s=0.1,
    fault_voltage_pu=1.25,
    description=(
        "Swell to 1.25pu held 0.1s - the case that actually distinguishes the two "
        "regression fixtures. Both share VDUA=1.20pu/TDUA=2.0s (0.1s alone never "
        "trips it); the only difference is TDUA1-3=0.0s (vendor-default-stages fixture, an "
        "instant trip if Option 3's stages are live) vs. TDUA1-3=2.0s (full-curve-stages "
        "fixture, no trip within 0.1s either way)."
    ),
)


@dataclass(frozen=True)
class MultiStageProbeVerdict:
    stages_live: bool | None  # True/False = conclusive; None = inconclusive
    explanation: str


def evaluate_multistage_probe(vendor_default_results: dict, full_curve_results: dict) -> MultiStageProbeVerdict:
    """`vendor_default_results`/`full_curve_results` are dicts keyed by scenario id
    (MULTISTAGE_UNDERVOLTAGE_PROBE.id, MULTISTAGE_OVERVOLTAGE_PROBE.id) mapping to
    SimulationResult - the results of running
    tests/fixtures/multistage_trip/ercot_nogrr282_vendor_default_stages.dyr and ..._full_curve_stages.dyr (IT
    block) against both probe scenarios. Reproduces the decision table the
    original PSS/E investigation used."""
    uv_id, ov_id = MULTISTAGE_UNDERVOLTAGE_PROBE.id, MULTISTAGE_OVERVOLTAGE_PROBE.id
    vendor_uv, vendor_ov = vendor_default_results[uv_id].tripped, vendor_default_results[ov_id].tripped
    full_uv, full_ov = full_curve_results[uv_id].tripped, full_curve_results[ov_id].tripped

    if not vendor_uv and not full_uv:
        return MultiStageProbeVerdict(
            stages_live=None,
            explanation=(
                "Neither fixture tripped on the undervoltage probe (sag to 0.75pu/0.6s) - "
                "Option 3's stage-2 undervoltage tier does not appear to be evaluated under "
                "this scenario, so the overvoltage probe result alone is not conclusive. "
                "Option 1's own VDPA=0.90pu/DMA=2.0s point also would not trip at 0.6s."
            ),
        )

    if vendor_ov and not full_ov:
        return MultiStageProbeVerdict(
            stages_live=True,
            explanation=(
                "ercot_nogrr282_vendor_default_stages.dyr tripped on the overvoltage probe (swell to "
                "1.25pu/0.1s) while ercot_nogrr282_full_curve_stages.dyr rode through it. Both share "
                "VDUA=1.20pu/TDUA=2.0s (0.1s alone never trips it), so this can only come from "
                "the untouched Option-3 stage TDUA1-3=0.0s in the vendor-default-stages fixture being "
                "evaluated. Option 3's stages are live: every preset this app has ever exported "
                "carries an unintended trip condition - see docs/developer/PERC1_MODEL.md."
            ),
        )

    if vendor_uv and full_uv and vendor_ov == full_ov:
        return MultiStageProbeVerdict(
            stages_live=False,
            explanation=(
                "Both fixtures tripped on the undervoltage probe and agreed with each other on "
                "the overvoltage probe - Option 3's stages appear inert under Option-1-only use. "
                "The current fixed defaults are safe as-is."
            ),
        )

    return MultiStageProbeVerdict(
        stages_live=None,
        explanation=(
            f"Inconclusive: undervoltage probe tripped=(vendor_default_stages={vendor_uv}, full_curve_stages={full_uv}), "
            f"overvoltage probe tripped=(vendor_default_stages={vendor_ov}, full_curve_stages={full_ov}). This combination "
            "doesn't match either clean outcome - investigate manually."
        ),
    )
