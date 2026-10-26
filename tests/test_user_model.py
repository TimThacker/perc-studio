"""A user-defined (black-box) block: the user's own records, exported unchanged except for the bus/number and
load ID that attach them to the facility's load."""

import re

import pytest

from app.config import DEFAULTS
from dev.validation.case_model import (
    SCHEMA_VERSION,
    block_dyr_record,
    from_dict,
    from_json,
    schema_problems,
    to_dict,
    to_json,
    ui_state_to_case,
)
from editor.user_model import USER_DEFINED_ID, placed_records, read_external_model
from export.dyr import build_dyr_text
from export.report import build_html_report

USER_DYR = (
    "@! a vendor model and an unrelated machine\n"
    "4021 'USRLOD' '7' 'FAKETRIP' 12 1 0 14 0 0 0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n"
    "4021 'GENROU' 1 6.5 0.05 0.6 0.05 4.0 0 1.8 1.75 0.3 0.55 0.25 0.2 0.1 0.3 /\n"
)
TWO_LOADS = USER_DYR + "4022 'USRLOD' '8' 'FAKETRIP' 12 1 0 14 0 0 0.6 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0 0 0 0 0 /\n"


def _cons(record: str) -> list[str]:
    return record.rstrip(" /").split()[4:]


def test_reading_a_file_takes_the_chosen_loads_records():
    model = read_external_model(USER_DYR, "vendor.dyr", 0, dlls=["C:/models/fake.dll"])
    assert model.source_file == "vendor.dyr" and model.dlls == ("C:/models/fake.dll",)
    assert (model.scope, model.number, model.load_id) == ("bus", 4021, "7")
    assert len(model.records) == 1 and "'FAKETRIP'" in model.records[0]
    assert model.original_header == "bus 4021, load '7'"


def test_the_load_choices_are_listed_and_a_file_without_a_load_is_rejected():
    assert len(read_external_model(TWO_LOADS, "two.dyr", None)) == 2
    assert read_external_model(TWO_LOADS, "two.dyr", 1).load_id == "8"
    with pytest.raises(ValueError, match="no load-model record"):
        read_external_model("1 'GENROU' 1 6.5 /\n", "machine.dyr", None)


def test_placing_changes_only_the_first_field_and_the_load_id():
    model = read_external_model(USER_DYR, "vendor.dyr", 0)
    placed = placed_records(model, 100001, "1")
    assert placed[0].startswith("100001 'USRLOD' '1' 'FAKETRIP' ")
    assert _cons(placed[0]) == _cons(model.records[0])  # model name, header, ICONs and CONs untouched


def user_state(**extra) -> dict:
    model = read_external_model(USER_DYR, "vendor.dyr", 0, dlls=["C:/models/fake.dll"])
    state = dict(DEFAULTS)
    state.update(model.state_keys("it"))
    state.update({"include_vfd_block": True, "include_motor_block": True, "it_advanced": True, "vfd_advanced": False,
                  "motor_advanced": False, **extra})
    return state


def test_a_mixed_facility_exports_the_user_record_beside_perc1_and_clod():
    text = build_dyr_text(user_state())
    assert "/ User-defined model from vendor.dyr (not edited or simulated by this app)." in text
    assert "Original record: bus 4021, load '7'" in text and "fake.dll" in text
    user_line = next(line for line in text.splitlines() if "'FAKETRIP'" in line)
    assert user_line.startswith(f"{DEFAULTS['bus_number']} 'USRLOD' '{DEFAULTS['load_id_it']}' 'FAKETRIP'")
    assert "0.7 0.2 1.2 1.0 57 63 0.5 0.9 1.0 2.0" in user_line
    assert "'PERCBL'" in text  # the VFD block is still PERC1 DLL
    assert re.search(r"'CLOD(BL)?'", text)


def test_the_report_describes_the_user_block_and_draws_no_chart_for_it():
    html = build_html_report(user_state())
    assert "User-defined model</strong> (not edited or simulated by this app): vendor.dyr" in html
    assert "fake.dll" in html
    assert "plot-it" not in html and "plot-vfd" in html


def test_the_case_model_carries_a_user_block_through_json():
    case = ui_state_to_case(user_state())
    assert case.schema_version == SCHEMA_VERSION == 3
    assert case.it_block.model_id == USER_DEFINED_ID and case.it_block.cons == {}
    assert case.it_block.external["records"] and case.it_block.external["dlls"] == ["C:/models/fake.dll"]
    assert schema_problems(case) == []
    restored = from_json(to_json(case))
    assert restored == case
    record = block_dyr_record(restored, "it", "5")
    assert f"{case.facility.bus_number} 'USRLOD' '5' 'FAKETRIP'" in record


def test_a_user_block_without_records_is_a_schema_problem():
    case = ui_state_to_case(user_state(it_user_records=[]))
    assert any("no records" in p for p in schema_problems(case))


def test_schema_2_json_still_loads(sample_case_preset):
    case = sample_case_preset()
    v2 = to_dict(case)
    v2["schema_version"] = 2
    for name in ("it_block", "vfd_block", "motor_block"):
        del v2[name]["external"]
    assert from_dict(v2) == case
