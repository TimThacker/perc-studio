import pytest

from dev.validation.checks import (
    MULTISTAGE_OVERVOLTAGE_PROBE,
    MULTISTAGE_UNDERVOLTAGE_PROBE,
    CaseValidationReport,
    evaluate_multistage_probe,
    expected_trip_for_scenario,
    validate_case,
    validate_result,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS
from psse.runner import FaultScenario, SimulationResult


def _result(scenario_id, *, tripped, block_name="it", trip_time_s=None, trip_type=None):
    return SimulationResult(
        case_id="case-1", block_name=block_name, scenario_id=scenario_id,
        time_s=[0.0, 1.0], voltage_pu=[1.0, 1.0], active_power_pu=[1.0, 1.0], reactive_power_pu=None,
        tripped=tripped, trip_time_s=trip_time_s, trip_type=trip_type, reconnect_time_s=None,
        final_power_pu=1.0, runner_id="mock", raw_case_path=None, dyr_text_sha256="deadbeef",
    )


ERCOT = RIDE_THROUGH_PRESETS["ercot_nogrr282"]


# --- expected_trip_for_scenario ---------------------------------------------


def test_expected_trip_undervoltage_below_the_required_floor():
    scenario = FaultScenario(id="s1", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    expected, reason = expected_trip_for_scenario(ERCOT, scenario)
    assert expected is True
    assert "Undervoltage" in reason


def test_expected_trip_undervoltage_at_or_above_the_required_floor():
    scenario = FaultScenario(id="s2", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.85)
    expected, _ = expected_trip_for_scenario(ERCOT, scenario)
    assert expected is False


def test_expected_trip_overvoltage_above_the_required_ceiling():
    scenario = FaultScenario(id="s3", fault_start_s=0.5, fault_duration_s=0.1, fault_voltage_pu=1.25)
    expected, reason = expected_trip_for_scenario(ERCOT, scenario)
    assert expected is True
    assert "Overvoltage" in reason


def test_expected_trip_overvoltage_at_or_below_the_required_ceiling():
    scenario = FaultScenario(id="s4", fault_start_s=0.5, fault_duration_s=0.1, fault_voltage_pu=1.15)
    expected, _ = expected_trip_for_scenario(ERCOT, scenario)
    assert expected is False


# --- validate_result / validate_case ----------------------------------------


def test_validate_result_passes_when_actual_matches_expected():
    scenario = FaultScenario(id="s1", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    point = validate_result(ERCOT, scenario, _result("s1", tripped=True, trip_time_s=1.1))
    assert point.passed is True
    assert point.actual_trip is True
    assert point.expected_trip is True


def test_validate_result_fails_when_actual_diverges_from_expected():
    scenario = FaultScenario(id="s1", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    point = validate_result(ERCOT, scenario, _result("s1", tripped=False))
    assert point.passed is False
    assert "Mismatch" in point.notes


def test_validate_case_aggregates_all_passed(sample_case_preset):
    case = sample_case_preset("ercot_nogrr282")
    sag = FaultScenario(id="sag", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    ride = FaultScenario(id="ride", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.85)
    pairs = [
        (sag, _result("sag", tripped=True, trip_time_s=1.1)),
        (ride, _result("ride", tripped=False)),
    ]
    report = validate_case(case, "it", pairs)
    assert isinstance(report, CaseValidationReport)
    assert report.all_passed is True
    assert report.preset_id == "ercot_nogrr282"
    assert len(report.points) == 2


def test_validate_case_flags_a_single_failure(sample_case_preset):
    case = sample_case_preset("ercot_nogrr282")
    sag = FaultScenario(id="sag", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    pairs = [(sag, _result("sag", tripped=False))]  # should have tripped
    report = validate_case(case, "it", pairs)
    assert report.all_passed is False
    assert report.points[0].passed is False


def test_validate_case_requires_explicit_preset_for_defaults_sourced_case(sample_case_defaults):
    case = sample_case_defaults()
    sag = FaultScenario(id="sag", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    with pytest.raises(ValueError, match="preset_id"):
        validate_case(case, "it", [(sag, _result("sag", tripped=True))])


def test_validate_case_accepts_an_explicit_preset_override(sample_case_defaults):
    case = sample_case_defaults()
    sag = FaultScenario(id="sag", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.75)
    report = validate_case(case, "it", [(sag, _result("sag", tripped=True, trip_time_s=1.1))], preset=ERCOT)
    assert report.preset_id == "ercot_nogrr282"


# --- evaluate_multistage_probe --------------------------------------------------


def test_multistage_probe_inconclusive_when_neither_fixture_trips_undervoltage():
    vendor_default = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=False),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=False),
    }
    full_curve = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=False),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=False),
    }
    verdict = evaluate_multistage_probe(vendor_default, full_curve)
    assert verdict.stages_live is None


def test_multistage_probe_live_when_vendor_default_stages_trip_overvoltage_but_full_curve_does_not():
    vendor_default = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=True, trip_time_s=1.1),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=True, trip_time_s=0.5),
    }
    full_curve = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=True, trip_time_s=1.1),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=False),
    }
    verdict = evaluate_multistage_probe(vendor_default, full_curve)
    assert verdict.stages_live is True


def test_multistage_probe_inert_when_both_fixtures_agree_throughout():
    vendor_default = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=True, trip_time_s=1.1),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=False),
    }
    full_curve = {
        MULTISTAGE_UNDERVOLTAGE_PROBE.id: _result(MULTISTAGE_UNDERVOLTAGE_PROBE.id, tripped=True, trip_time_s=1.1),
        MULTISTAGE_OVERVOLTAGE_PROBE.id: _result(MULTISTAGE_OVERVOLTAGE_PROBE.id, tripped=False),
    }
    verdict = evaluate_multistage_probe(vendor_default, full_curve)
    assert verdict.stages_live is False


# --- Frequency scenarios -------------------------------------------------------


def test_frequency_scenario_is_validated_against_the_presets_frequency_table():
    from dev.validation.checks import expected_trip_for_scenario
    from presets.ridethrough import RIDE_THROUGH_PRESETS
    from psse.runner import FaultScenario

    preset = RIDE_THROUGH_PRESETS["nerc_prc029"]
    short = FaultScenario(id="uf_short", fault_start_s=0.5, fault_duration_s=100.0, fault_frequency_hz=58.0)
    long = FaultScenario(id="uf_long", fault_start_s=0.5, fault_duration_s=300.0, fault_frequency_hz=58.0)

    assert expected_trip_for_scenario(preset, short)[0] is False
    assert expected_trip_for_scenario(preset, long)[0] is True


def test_frequency_scenario_needs_a_frequency_table():
    import pytest

    from dev.validation.checks import expected_trip_for_scenario
    from presets.ridethrough import RIDE_THROUGH_PRESETS
    from psse.runner import FaultScenario

    scenario = FaultScenario(id="uf", fault_start_s=0.5, fault_duration_s=100.0, fault_frequency_hz=58.0)
    with pytest.raises(ValueError, match="no frequency ride-through table"):
        expected_trip_for_scenario(RIDE_THROUGH_PRESETS["ercot_nogrr282"], scenario)
