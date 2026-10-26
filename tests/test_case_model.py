import pytest

from dev.validation.case_model import (
    FacilityInfo,
    LoadComposition,
    case_from_preset,
    case_to_ui_state,
    case_with_overrides,
    from_dict,
    from_json,
    to_dict,
    to_json,
    ui_state_to_case,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS


def test_case_from_preset_cons_match_the_preset_bundle_exactly(sample_case_preset):
    case = sample_case_preset("ercot_nogrr282")
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]

    assert case.it_block.cons == preset.it_bundle
    assert case.vfd_block.cons == preset.vfd_bundle
    assert case.it_block.source == "preset"
    assert case.it_block.preset_id == "ercot_nogrr282"


def test_case_from_preset_unknown_id_raises_key_error():
    facility = FacilityInfo("F", 1, "B", "AI", 100, 300.0, 0.99)
    load_composition = LoadComposition(70, 20, 5, 5)
    with pytest.raises(KeyError):
        case_from_preset("not_a_real_preset", facility=facility, load_composition=load_composition)


def test_case_from_model_defaults_carries_the_model_default_cons(sample_case_defaults):
    from load_models import get_load_model

    case = sample_case_defaults()
    assert case.it_block.cons == get_load_model("perc1_dll").default_cons
    assert case.it_block.source == "defaults"
    assert case.vfd_block is None and case.motor_block is None
    assert case.is_load_split_valid is True


def test_case_from_preset_motor_block_is_archetype_sourced(sample_case_preset):
    case = sample_case_preset("ercot_nogrr282")
    assert case.motor_block.source == "archetype"
    assert case.motor_block.qualitative["facility_type"] == "Mixed - moderate mix of large & small motors"


def test_mw_properties_are_computed_not_stored(sample_case_preset):
    case = sample_case_preset()
    assert case.mw_it == pytest.approx(300.0 * 0.70)
    assert case.mw_vfd == pytest.approx(300.0 * 0.20)
    assert case.mw_motor == pytest.approx(300.0 * 0.05)


def test_to_dict_from_dict_round_trip(sample_case_preset):
    case = sample_case_preset()
    restored = from_dict(to_dict(case))
    assert restored == case


def test_to_json_from_json_round_trip_via_string(sample_case_preset):
    case = sample_case_preset()
    text = to_json(case)
    restored = from_json(text)
    assert restored == case


def test_to_json_from_json_round_trip_via_file(sample_case_preset, tmp_path):
    case = sample_case_preset()
    path = str(tmp_path / "case.json")
    to_json(case, path)
    restored = from_json(path)
    assert restored == case


def test_from_dict_rejects_unknown_schema_version(sample_case_preset):
    d = to_dict(sample_case_preset())
    d["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        from_dict(d)


def test_from_dict_migrates_schema_1_json(sample_case_preset):
    """Case JSON written before blocks carried a model_id (schema 1) still loads."""
    case = sample_case_preset()
    v1 = to_dict(case)
    v1["schema_version"] = 1
    v1["model_variant"] = "dll"
    for name in ("it_block", "vfd_block"):
        del v1[name]["model_id"]
    motor = v1["motor_block"]
    del motor["model_id"]
    qualitative = motor.pop("qualitative")
    motor["facility_type"] = qualitative["facility_type"]
    motor["has_lighting"] = qualitative["has_lighting"]

    assert from_dict(v1) == case


def test_case_with_overrides_updates_cons_and_tracks_provenance(sample_case_preset):
    case = sample_case_preset()
    updated = case_with_overrides(case, "it", {"VDPA": 0.55})
    assert updated.it_block.cons["VDPA"] == 0.55
    assert updated.it_block.overrides == {"VDPA": 0.55}
    # original is untouched (frozen dataclasses, no mutation)
    assert case.it_block.cons["VDPA"] != 0.55


def test_case_with_overrides_rejects_unknown_con_name(sample_case_preset):
    case = sample_case_preset()
    with pytest.raises(ValueError, match="unknown CON name"):
        case_with_overrides(case, "it", {"NOT_A_REAL_CON": 1.0})


def test_case_with_overrides_rejects_unknown_block(sample_case_preset):
    case = sample_case_preset()
    with pytest.raises(ValueError, match="unknown block"):
        case_with_overrides(case, "bogus", {"VDPA": 0.5})


def test_case_to_ui_state_forces_advanced_flags_true(sample_case_preset):
    case = sample_case_preset()
    state = case_to_ui_state(case)
    assert state["it_advanced"] is True
    assert state["vfd_advanced"] is True
    assert state["motor_advanced"] is True
    assert state["it_adv_VDPA"] == case.it_block.cons["VDPA"]


def test_case_to_ui_state_and_back_round_trips_cons(sample_case_preset):
    case = sample_case_preset()
    state = case_to_ui_state(case)
    restored = ui_state_to_case(state)
    assert restored.it_block.cons == case.it_block.cons
    assert restored.vfd_block.cons == case.vfd_block.cons
    assert restored.motor_block.cons == case.motor_block.cons
    assert restored.facility.total_mw == case.facility.total_mw


def test_ui_state_to_case_works_from_a_plain_dict_literal():
    # ui_state_to_case must work from a plain dict literal without importing
    # PySide6/QApplication - this is the whole point of the converter.
    state = {
        "facility_name": "Plain Dict Facility",
        "bus_number": 42,
        "bus_name": "BUS_42",
        "total_mw": 100.0,
        "power_factor": 0.98,
        "pct_it": 80.0,
        "pct_cooling_vfd": 10.0,
        "pct_cooling_motor": 5.0,
        "pct_other": 5.0,
        "use_case": "Inference",
        "it_ups_mode": "Double conversion (online)",
        "vfd_type": "Standard front-end (diode rectifier)",
        "motor_facility_type": "Mixed - moderate mix of large & small motors",
        "motor_has_lighting": False,
        "include_vfd_block": True,
        "include_motor_block": True,
        "it_advanced": False,
        "vfd_advanced": False,
        "motor_advanced": False,
    }
    case = ui_state_to_case(state)
    assert case.facility.name == "Plain Dict Facility"
    # With no *_adv_* keys, the PERC1 blocks take the model's default CONs and the motor block its archetype.
    from load_models import get_load_model

    assert case.it_block.source == "overrides"
    assert case.it_block.cons == get_load_model("perc1_dll").default_cons
    assert case.motor_block.source == "archetype"


def test_block_dyr_record_scopes(sample_case_preset):
    from dev.validation.case_model import block_dyr_record

    case = sample_case_preset()
    assert "101 'USRLOD' '1' 'PERCBL' 12 1" in block_dyr_record(case, "it", "1")
    assert "5 'USRLOD' '1' 'PERCAR' 12 4" in block_dyr_record(case, "it", "1", scope="area", subsystem_number=5)
    assert "0 'USRLOD' '1' 'PERCAL' 12 5" in block_dyr_record(case, "it", "1", scope="all")
    with pytest.raises(ValueError, match="Zone-scoped records need the zone number"):
        block_dyr_record(case, "it", "1", scope="zone")
