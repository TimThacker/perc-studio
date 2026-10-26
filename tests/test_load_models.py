"""Contract tests every registered load model must pass, plus an end-to-end
run of the developer loop on a non-PERC1 model.

A newly added model is picked up here automatically through
`load_models.LOAD_MODELS` - no new test code is needed to check that it is
internally consistent and round-trips through `.dyr` export.
"""

import json

import pytest
from fixtures.example_load_model import MODEL as EXAMPLE_MODEL

from dev.cli.main import cli
from dev.validation.case_model import (
    FacilityInfo,
    LoadComposition,
    block_dyr_record,
    case_from_model_defaults,
    case_from_preset,
    case_with_overrides,
    from_json,
    schema_problems,
    to_json,
)
from dev.validation.sweep import run_sweep
from load_models import (
    LOAD_MODELS,
    find_model_for_dyr,
    get_load_model,
    register_load_model,
)
from psse.runner import FaultScenario, MockPsseRunner

ALL_MODELS = [*LOAD_MODELS.values(), EXAMPLE_MODEL]
_ids = [model.id for model in ALL_MODELS]

FACILITY = FacilityInfo(name="Test", bus_number=101, bus_name="BUS_101", use_case="AI Training",
                        use_case_pct=100, total_mw=300.0, power_factor=0.99)
LOAD = LoadComposition(pct_it=70.0, pct_cooling_vfd=20.0, pct_cooling_motor=5.0, pct_other=5.0)


# --- Contract: every model -------------------------------------------------


@pytest.mark.parametrize("model", ALL_MODELS, ids=_ids)
def test_con_names_are_unique_and_fully_defaulted(model):
    assert model.con_names, "a model needs at least one CON"
    assert len(set(model.con_names)) == len(model.con_names)
    assert set(model.default_cons) == set(model.con_names)


@pytest.mark.parametrize("model", ALL_MODELS, ids=_ids)
def test_display_fields_name_real_cons(model):
    for name, label, *_ in model.display_fields:
        assert name in model.con_names
        assert label


@pytest.mark.parametrize("model", ALL_MODELS, ids=_ids)
def test_dyr_record_names_the_model(model, monkeypatch):
    monkeypatch.setitem(LOAD_MODELS, model.id, model)
    text = model.build_dyr_record(101, "1", model.default_cons)
    assert f"'{model.dyr_model_name}'" in text
    assert find_model_for_dyr(text) is model


@pytest.mark.parametrize("model", [m for m in ALL_MODELS if m.parse_dyr_record], ids=lambda m: m.id)
def test_dyr_record_round_trips(model):
    text = model.build_dyr_record(101, "1", model.default_cons)
    parsed = model.parse_dyr_record(text)
    assert parsed == pytest.approx(dict(model.default_cons))


@pytest.mark.parametrize("model", [m for m in ALL_MODELS if m.simulate], ids=lambda m: m.id)
@pytest.mark.parametrize("fault_voltage_pu", [0.3, 0.95, 1.25])
def test_simulate_returns_the_response_shape_the_runner_needs(model, fault_voltage_pu):
    response = model.simulate(dict(model.default_cons), 0.2, fault_voltage_pu)
    for key in ("v_points", "p_points", "sim_end", "trips", "trip_type", "markers"):
        assert key in response, key
    assert response["trip_type"] in (None, "undervoltage", "overvoltage")


@pytest.mark.parametrize("model", [m for m in ALL_MODELS if m.simulate_frequency], ids=lambda m: m.id)
@pytest.mark.parametrize("fault_frequency_hz", [57.0, 59.9, 62.5])
def test_simulate_frequency_returns_the_response_shape_the_runner_needs(model, fault_frequency_hz):
    response = model.simulate_frequency(dict(model.default_cons), 120.0, fault_frequency_hz)
    for key in ("v_points", "f_points", "p_points", "sim_end", "trips", "trip_type", "markers"):
        assert key in response, key
    assert response["trip_type"] in (None, "underfrequency", "overfrequency")


@pytest.mark.parametrize("model", [m for m in ALL_MODELS if m.cons_for_preset], ids=lambda m: m.id)
def test_cons_for_preset_covers_every_con(model):
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    for preset in RIDE_THROUGH_PRESETS.values():
        cons = model.cons_for_preset(preset, "it")
        assert set(cons) == set(model.con_names), preset.id


# --- Registry ----------------------------------------------------------------


def test_registry_keys_match_model_ids():
    for key, model in LOAD_MODELS.items():
        assert key == model.id


def test_register_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="already registered"):
        register_load_model(get_load_model("perc1_dll"))


def test_unknown_model_lists_registered_ids():
    with pytest.raises(KeyError, match="perc1_dll"):
        get_load_model("nope")


# --- The developer loop on a non-PERC1 model -------------------------------


def test_defaults_case_exports_validates_and_overrides(example_model):
    case = case_from_model_defaults(example_model.id, facility=FACILITY, load_composition=LOAD)
    assert schema_problems(case) == []
    assert "'STPTRP'" in block_dyr_record(case, "it", "1")

    case = case_with_overrides(case, "it", {"VUV": 0.5})
    assert case.it_block.cons["VUV"] == 0.5
    with pytest.raises(ValueError, match="VDPA"):
        case_with_overrides(case, "it", {"VDPA": 0.5})  # a PERC1 CON, not this model's

    assert from_json(to_json(case)) == case


def test_mock_runner_dispatches_to_the_records_own_model(example_model):
    case = case_from_preset("ercot_nogrr282", facility=FACILITY, load_composition=LOAD,
                            model_id=example_model.id, include_vfd=False, include_motor=False)
    dyr_text = block_dyr_record(case, "it", "1")
    deep_long_sag = FaultScenario(id="deep", fault_start_s=0.5, fault_duration_s=3.0, fault_voltage_pu=0.5)

    result = MockPsseRunner().run(None, dyr_text, deep_long_sag, block_name="it", case_id=case.case_id)

    assert result.tripped
    assert result.metadata["model_id"] == example_model.id


def test_sweep_runs_a_non_perc1_model_end_to_end(example_model, tmp_path):
    spec = {
        "sweep_id": "example_model_sweep",
        "model": example_model.id,
        "presets": ["ercot_nogrr282"],
        "scenarios": [
            {"id": "deep_long_sag", "fault_start_s": 0.5, "fault_duration_s": 3.0, "fault_voltage_pu": 0.5},
            {"id": "shallow_sag", "fault_start_s": 0.5, "fault_duration_s": 0.1, "fault_voltage_pu": 0.95},
        ],
    }
    summary = run_sweep(spec, str(tmp_path), runner=MockPsseRunner())

    assert summary["total_cases"] == 2
    assert summary["all_passed"], summary
    case_files = [p for p in (tmp_path / "cases").iterdir() if p.suffix == ".json"]
    assert json.loads(case_files[0].read_text())["it_block"]["model_id"] == example_model.id


def test_sweep_rejects_a_model_that_cannot_encode_presets(tmp_path):
    spec = {"model": "clod", "presets": ["ercot_nogrr282"], "scenarios": []}
    with pytest.raises(ValueError, match="cons_for_preset"):
        run_sweep(spec, str(tmp_path), runner=MockPsseRunner())


def test_cli_lists_models_and_builds_a_defaults_case(example_model, cli_runner, tmp_path):
    listed = json.loads(cli_runner.invoke(cli, ["models", "list"]).output)
    assert {m["id"] for m in listed["data"]["models"]} >= {"perc1_dll", "clod", example_model.id}

    shown = json.loads(cli_runner.invoke(cli, ["models", "show", "clod"]).output)
    assert shown["data"]["con_names"] == ["PC_LM", "PC_SM", "PC_TX", "PC_DL", "PC_CP"]
    assert shown["data"]["capabilities"]["mock_run"] is False

    out = str(tmp_path / "case.json")
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "defaults", "--model", example_model.id,
                                     "--out", out])
    assert result.exit_code == 0, result.output
    assert cli_runner.invoke(cli, ["params", "validate", out]).exit_code == 0

    ran = cli_runner.invoke(cli, ["run", out, "--fault-duration-s", "0.5", "--fault-voltage-pu", "0.5"])
    assert ran.exit_code == 0, ran.output
    assert json.loads(ran.output)["data"]["result"]["tripped"] is True

    unknown = cli_runner.invoke(cli, ["params", "generate", "--source", "defaults", "--model", "nope"])
    assert unknown.exit_code == 2
