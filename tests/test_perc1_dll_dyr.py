import os

import pytest

from load_models.perc1_dll.cons import PERC1_FIXED_DEFAULTS
from load_models.perc1_dll.dyr import build_perc1_dyr_block, parse_perc1_dyr_block
from presets.ridethrough import RIDE_THROUGH_PRESETS

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "multistage_trip")


def test_parse_round_trips_fixed_defaults():
    from load_models.perc1_dll.cons import PERC1_CON_ORDER

    params = dict(PERC1_FIXED_DEFAULTS)
    params.update({"VDPA": 0.7, "DMA": 0.02, "FCEASE": 1.0, "VRPA": 0.9, "TDRA": 60.0, "RAMPA": 30.0,
                   "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02})
    dyr_text = build_perc1_dyr_block(101, "I1", params)

    parsed = parse_perc1_dyr_block(dyr_text)

    assert set(parsed) == set(PERC1_CON_ORDER)
    for name in PERC1_CON_ORDER:
        assert parsed[name] == params[name], name


def test_parse_round_trips_a_preset_bundle():
    bundle = RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle
    dyr_text = build_perc1_dyr_block(202, "I1", bundle)

    parsed = parse_perc1_dyr_block(dyr_text)

    assert parsed == bundle


def test_parse_vendor_default_stages_fixture_has_documented_stage_values():
    with open(os.path.join(FIXTURE_DIR, "ercot_nogrr282_vendor_default_stages.dyr"), "r", encoding="utf-8") as f:
        parsed = parse_perc1_dyr_block(f.read())

    assert parsed["VDPA"] == 0.90
    assert parsed["DMA"] == 2.00
    assert parsed["VDPA1"] == 0.80
    assert parsed["DMA1"] == 0.50
    assert parsed["VDUA1"] == 1.20
    assert parsed["TDUA1"] == 0.0


def test_parse_full_curve_stages_fixture_has_documented_stage_values():
    with open(os.path.join(FIXTURE_DIR, "ercot_nogrr282_full_curve_stages.dyr"), "r", encoding="utf-8") as f:
        parsed = parse_perc1_dyr_block(f.read())

    assert parsed["VDPA"] == 0.90
    assert parsed["DMA"] == 2.00
    assert parsed["VDPA1"] == 0.80
    assert parsed["DMA1"] == 0.50
    assert parsed["VDPA2"] == 0.50
    assert parsed["DMA2"] == 0.25
    assert parsed["VDPA3"] == 0.20
    assert parsed["DMA3"] == 0.15
    assert parsed["VDUA1"] == 1.20
    assert parsed["TDUA1"] == 2.0


def test_build_perc1_dyr_block_rejects_load_id_longer_than_2_chars():
    """Regression test: PSS/E's real Load/USRLOD identifier field is
    character*2 - confirmed directly against PSS/E v35.6.4's own
    `load_data_6` API, which rejected this app's own past load-id defaults
    ('SCREEN1', 'SWEEP1', and the tests/fixtures/multistage_trip fixtures' 'IT1') with
    "Load identifier is more than two characters"."""
    params = dict(PERC1_FIXED_DEFAULTS)
    params.update({"VDPA": 0.7, "DMA": 0.02, "FCEASE": 1.0, "VRPA": 0.9, "TDRA": 60.0, "RAMPA": 30.0,
                   "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02})
    from load_models.perc1_dll.dyr import build_perc1_dyr_block

    with pytest.raises(ValueError, match="1-2 characters"):
        build_perc1_dyr_block(101, "TOOLONG", params)
    with pytest.raises(ValueError, match="1-2 characters"):
        build_perc1_dyr_block(101, "", params)

    # 1 and 2 character ids are both valid.
    assert "'1'" in build_perc1_dyr_block(101, "1", params)
    assert "'I1'" in build_perc1_dyr_block(101, "I1", params)


def test_parse_raises_on_no_record_found():
    with pytest.raises(ValueError, match="no PERCBL"):
        parse_perc1_dyr_block("this text has no PERCBL record in it")


def _full_params(**overrides):
    params = dict(PERC1_FIXED_DEFAULTS)
    params.update({"VDPA": 0.70, "DMA": 0.02, "FCEASE": 1.0, "VRPA": 0.90, "TDRA": 60.0, "RAMPA": 30.0,
                   "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02})
    params.update(overrides)
    return params


def test_parse_raises_on_multiple_records_without_load_id():
    from load_models.perc1_dll.dyr import build_perc1_dyr_block

    text = build_perc1_dyr_block(101, "I1", _full_params()) + "\n" + build_perc1_dyr_block(
        101, "V1", _full_params()
    )
    with pytest.raises(ValueError, match="multiple PERCBL"):
        parse_perc1_dyr_block(text)


def test_parse_disambiguates_multiple_records_with_load_id():
    from load_models.perc1_dll.dyr import build_perc1_dyr_block

    it_params = dict(PERC1_FIXED_DEFAULTS)
    it_params.update({"VDPA": 0.61, "DMA": 0.02, "FCEASE": 1.0, "VRPA": 0.9, "TDRA": 60.0, "RAMPA": 30.0,
                       "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02})
    vfd_params = dict(PERC1_FIXED_DEFAULTS)
    vfd_params.update({"VDPA": 0.72, "DMA": 0.05, "FCEASE": 1.0, "VRPA": 0.9, "TDRA": 60.0, "RAMPA": 30.0,
                        "FRECON": 1.0, "NPA": 0, "NQA": 0, "TRA": 0.02})
    text = build_perc1_dyr_block(101, "I1", it_params) + "\n" + build_perc1_dyr_block(101, "V1", vfd_params)

    assert parse_perc1_dyr_block(text, load_id="I1")["VDPA"] == 0.61
    assert parse_perc1_dyr_block(text, load_id="V1")["VDPA"] == 0.72


@pytest.mark.parametrize("scope, suffix, it, number", [
    ("bus", "BL", 1, 100001), ("owner", "OW", 2, 7), ("zone", "ZN", 3, 12), ("area", "AR", 4, 3), ("all", "AL", 5, 0),
])
def test_every_record_scope_writes_the_vendor_name_and_it_code(scope, suffix, it, number):
    """Vendor Rev7 "DYRE FORMAT": 'PERC**' with ** = BL/OW/ZN/AR/AL and IT = 1-5."""
    from load_models import find_model_for_dyr
    from load_models.perc1_dll.dyr import parse_perc1_record_scope

    bundle = RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle
    text = build_perc1_dyr_block(number, "1", bundle, scope)

    assert f"{number} 'USRLOD' '1' 'PERC{suffix}' 12 {it} 2 173 33 250 0" in text
    assert parse_perc1_record_scope(text) == (scope, number)
    assert parse_perc1_dyr_block(text) == bundle
    assert find_model_for_dyr(text).id == "perc1_dll"


def test_record_name_and_it_code_must_agree():
    from load_models.perc1_dll.dyr import parse_perc1_record_scope

    text = build_perc1_dyr_block(7, "1", RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle, "owner")
    with pytest.raises(ValueError, match="IT=2"):
        parse_perc1_record_scope(text.replace("'PERCOW' 12 2", "'PERCOW' 12 1"))


def test_clod_record_follows_the_scope():
    from load_models.clod.dyr import clod_record

    cons = {"PC_LM": 35.0, "PC_SM": 35.0, "PC_TX": 5.0, "PC_DL": 5.0, "PC_CP": 10.0}
    assert "'CLODBL'" in clod_record(100001, "3", cons)
    assert clod_record(12, "3", cons, "zone").strip().startswith("12, 'CLODZN', '3'")
