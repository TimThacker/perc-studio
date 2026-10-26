import pytest

from load_models.perc1_dll.cons import PERC1_FIXED_DEFAULTS
from load_models.perc1_dll.dyr import build_perc1_dyr_block
from psse.runner import FaultScenario, MockPsseRunner, SimulationResult, get_runner


def _dyr_text(**overrides):
    params = dict(PERC1_FIXED_DEFAULTS)
    params.update({"VDPA": 0.70, "DMA": 0.02, "FCEASE": 1.0, "VRPA": 0.90, "TDRA": 60.0, "RAMPA": 30.0,
                   "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02, "VDUA": 1.10, "TDUA": 0.5})
    params.update(overrides)
    return build_perc1_dyr_block(101, "I1", params)


def assert_runner_contract(runner):
    """Shared contract checks any PsseRunner implementation must satisfy -
    parametrized over MockPsseRunner today; extend with a real-runner case
    (skipif-gated) once one exists."""
    dyr_text = _dyr_text()
    scenario = FaultScenario(id="contract_probe", fault_start_s=0.5, fault_duration_s=0.6, fault_voltage_pu=0.5)

    result = runner.run(None, dyr_text, scenario, block_name="it", case_id="contract-case")

    assert isinstance(result, SimulationResult)
    assert result.case_id == "contract-case"
    assert result.block_name == "it"
    assert result.scenario_id == "contract_probe"
    assert len(result.time_s) == len(result.voltage_pu) == len(result.active_power_pu)
    assert result.time_s == sorted(result.time_s)
    assert result.runner_id
    assert result.dyr_text_sha256 is not None
    # round-trips through JSON cleanly
    assert SimulationResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("runner", [MockPsseRunner()])
def test_runner_satisfies_the_shared_contract(runner):
    assert_runner_contract(runner)


def test_get_runner_mock_returns_a_mock_runner():
    runner = get_runner("mock")
    assert isinstance(runner, MockPsseRunner)


def test_get_runner_psse_needs_a_selected_install(monkeypatch, tmp_path):
    monkeypatch.delenv("PERC_STUDIO_PSSE_VERSION", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))  # no saved selection
    with pytest.raises(NotImplementedError, match="no PSS/E install is selected"):
        get_runner("psse")


def test_get_runner_psse_runs_real_cases(monkeypatch, fake_psse_install):
    monkeypatch.setenv("PERC_STUDIO_PSSE_VERSION", fake_psse_install.version)
    monkeypatch.setenv("PERC_STUDIO_PSSE_DIR", fake_psse_install.install_dir)
    monkeypatch.setenv("PERC_STUDIO_PSSE_PYTHON", fake_psse_install.python_exe)
    runner = get_runner("psse")
    dyr = ("101 'USRLOD' '1' 'FAKETRIP' 12 1 0 14 0 0 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /")
    trip = runner.run(None, dyr, FaultScenario("s1", 0.5, 0.5, 0.5), block_name="it", case_id="c")
    ride = runner.run(None, dyr, FaultScenario("s2", 0.5, 0.1, 0.5), block_name="it", case_id="c")
    assert trip.tripped and trip.trip_type == "undervoltage" and trip.reconnect_time_s is not None
    assert not ride.tripped and ride.runner_id == "psse"


def test_get_runner_unknown_name_raises_value_error():
    with pytest.raises(ValueError):
        get_runner("not-a-real-runner")


def test_mock_runner_trips_when_sag_exceeds_trip_threshold():
    runner = MockPsseRunner()
    dyr_text = _dyr_text(VDPA=0.70, DMA=0.02)
    scenario = FaultScenario(id="deep_sag", fault_start_s=0.5, fault_duration_s=0.1, fault_voltage_pu=0.3)

    result = runner.run(None, dyr_text, scenario, block_name="it", case_id="c1")

    assert result.tripped is True
    assert result.trip_type == "undervoltage"
    assert result.trip_time_s is not None


def test_mock_runner_rides_through_shallow_short_sag():
    runner = MockPsseRunner()
    dyr_text = _dyr_text(VDPA=0.70, DMA=2.0)
    scenario = FaultScenario(id="shallow_sag", fault_start_s=0.5, fault_duration_s=0.1, fault_voltage_pu=0.9)

    result = runner.run(None, dyr_text, scenario, block_name="it", case_id="c2")

    assert result.tripped is False
    assert result.trip_type is None


def test_mock_runner_trips_on_overvoltage():
    runner = MockPsseRunner()
    dyr_text = _dyr_text(VDUA=1.10, TDUA=0.05)
    scenario = FaultScenario(id="swell", fault_start_s=0.5, fault_duration_s=0.2, fault_voltage_pu=1.25)

    result = runner.run(None, dyr_text, scenario, block_name="it", case_id="c3")

    assert result.tripped is True
    assert result.trip_type == "overvoltage"


def test_mock_runner_warns_when_fault_start_s_ignored():
    runner = MockPsseRunner()
    dyr_text = _dyr_text()
    scenario = FaultScenario(id="s", fault_start_s=1.5, fault_duration_s=0.1, fault_voltage_pu=0.9)

    result = runner.run(None, dyr_text, scenario, block_name="it", case_id="c4")

    assert any("fault_start_s" in w for w in result.warnings)


def test_frequency_scenario_round_trips_and_runs_through_the_mock_runner():
    scenario = FaultScenario(id="uf", fault_start_s=0.5, fault_duration_s=150.0, fault_frequency_hz=57.9)
    assert scenario.event_kind == "frequency"
    assert FaultScenario.from_dict(scenario.to_dict()) == scenario
    # Voltage scenarios written before frequency support still load.
    legacy = {"id": "v", "fault_start_s": 0.5, "fault_duration_s": 0.1, "fault_voltage_pu": 0.5}
    assert FaultScenario.from_dict(legacy).event_kind == "voltage"

    result = MockPsseRunner().run(None, _dyr_text(), scenario, block_name="it", case_id="c")

    assert result.tripped and result.trip_type == "underfrequency"  # vendor stage 1: 58.0 Hz / 100 s
    assert result.frequency_hz is not None and min(result.frequency_hz) == 57.9
    assert len(result.time_s) <= 5001
    assert SimulationResult.from_dict(result.to_dict()).frequency_hz == result.frequency_hz
