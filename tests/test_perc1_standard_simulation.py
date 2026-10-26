"""The analytic simulator of the PERC1 standard model. Its match to PSS/E 36.7.1 traces was checked against the
PSS/E validation library, which is not published; these tests pin the behavior that does not need those traces."""


import pytest

from load_models.perc1_standard import MODEL
from load_models.perc1_standard.cons import DEFAULT_CONS
from load_models.perc1_standard.simulation import (
    simulate_perc1_standard_frequency_response as sim_f,
)
from load_models.perc1_standard.simulation import (
    simulate_perc1_standard_response as sim_v,
)


def test_overvoltage_and_frequency_never_cease():
    c = dict(DEFAULT_CONS)
    assert not sim_v(c, 2.0, 1.25)["trips"]
    assert not sim_f(c, 60.0, 57.0)["trips"]


def test_zero_pu_voltage_is_flagged():
    assert sim_v(dict(DEFAULT_CONS), 0.5, 0.0)["psse_nan_hazard"]


def test_response_shape_for_every_preset_and_the_registry_hooks():
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    assert MODEL.can_run_mock and MODEL.simulate_frequency is not None
    for preset in RIDE_THROUGH_PRESETS.values():
        cons = MODEL.cons_for_preset(preset, "it")
        out = MODEL.simulate(cons, cons["Tcease"] + 2.0, 0.1)
        assert out["trips"] and out["markers"]["reconnect_end"] > out["markers"]["reconnect_start"]
        assert len(out["p_points"]) < 5000
        assert out["p_points"][-1][1] == pytest.approx(1.0, abs=2e-3)  # fcease 1, frecon 1: back to full load


# --- the developer loop on this model ----------------------------------------------

def test_case_export_mock_run_and_validation_loop():
    from dev.validation.case_model import (
        FacilityInfo,
        LoadComposition,
        block_dyr_record,
        case_from_preset,
        schema_problems,
    )
    from dev.validation.checks import validate_case
    from psse.runner import FaultScenario, MockPsseRunner

    facility = FacilityInfo(name="T", bus_number=101, bus_name="B", use_case="AI Training", use_case_pct=100,
                            total_mw=300.0, power_factor=0.99)
    load = LoadComposition(pct_it=70.0, pct_cooling_vfd=20.0, pct_cooling_motor=5.0, pct_other=5.0)
    case = case_from_preset("pjm_lcl", facility=facility, load_composition=load, model_id="perc1_standard",
                            include_vfd=False, include_motor=False)
    assert schema_problems(case) == []
    dyr = block_dyr_record(case, "it", "1")
    assert "'PERCBL1U'" in dyr and "'MAINBL10'" in dyr
    runner = MockPsseRunner()
    scenarios = [
        FaultScenario(id="deep_long", fault_start_s=0.5, fault_duration_s=3.0, fault_voltage_pu=0.2),
        FaultScenario(id="shallow", fault_start_s=0.5, fault_duration_s=0.3, fault_voltage_pu=0.6),
        FaultScenario(id="swell", fault_start_s=0.5, fault_duration_s=5.0, fault_voltage_pu=1.25),
        FaultScenario(id="underfreq", fault_start_s=0.5, fault_duration_s=30.0, fault_voltage_pu=1.0, fault_frequency_hz=57.0),
    ]
    results = [(s, runner.run(None, dyr, s, block_name="it", case_id=case.case_id)) for s in scenarios]
    by_id = {s.id: r for s, r in results}
    assert by_id["deep_long"].tripped and not by_id["shallow"].tripped
    assert not by_id["swell"].tripped and not by_id["underfreq"].tripped
    report = validate_case(case, "it", results)
    notes = {p.scenario_id: p.notes for p in report.points}
    assert all(p.passed for p in report.points), notes
    assert "Not modelled" in notes["swell"] or report.points[2].expected_trip is False
