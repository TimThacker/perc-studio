"""Reading a .dyr file back into the app: record discovery, model detection, tolerant parsing and warnings."""

import os

import pytest

from editor.dyr_import import import_record, list_records
from load_models import get_load_model
from load_models.base import RECORD_SCOPES
from load_models.perc1_dll.cons import PERC1_CON_ORDER
from load_models.perc1_dll.dyr import build_perc1_dyr_block
from load_models.perc1_standard.cons import CON_NAMES
from load_models.perc1_standard.dyr import build_perc1_standard_dyr_block
from presets.ridethrough import RIDE_THROUGH_PRESETS

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "multistage_trip")
DLL_CONS = get_load_model("perc1_dll").cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
STD_CONS = get_load_model("perc1_standard").cons_for_preset(RIDE_THROUGH_PRESETS["pjm_lcl"], "it")


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_dll_round_trip_for_every_scope(scope):
    number = 0 if scope == "all" else 7
    imported = import_record(build_perc1_dyr_block(number, "1", DLL_CONS, scope=scope))
    assert imported.model_id == "perc1_dll" and imported.ref.scope == scope and imported.ref.number == number
    assert list(imported.cons) == PERC1_CON_ORDER
    assert imported.cons == DLL_CONS
    assert imported.warnings == ()


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_standard_round_trip_for_every_scope(scope):
    number = 0 if scope == "all" else 9
    imported = import_record(build_perc1_standard_dyr_block(number, "S1", STD_CONS, scope=scope))
    assert imported.model_id == "perc1_standard" and imported.ref.scope == scope and imported.ref.load_id == "S1"
    assert list(imported.cons) == list(CON_NAMES)
    for name in CON_NAMES:
        assert imported.cons[name] == pytest.approx(STD_CONS[name], rel=1e-5, abs=1e-9), name
    assert imported.extras["load_fraction"] == 1.0 and imported.extras["component"] == 1


def test_standard_partial_load_fraction_is_read_from_the_main_record():
    text = build_perc1_standard_dyr_block(5, "1", STD_CONS, load_fraction=0.6, component=2)
    imported = import_record(text)
    assert imported.extras["load_fraction"] == pytest.approx(0.6) and imported.extras["component"] == 2


@pytest.mark.parametrize("name", ["ercot_nogrr282_vendor_default_stages.dyr", "ercot_nogrr282_full_curve_stages.dyr"])
def test_regression_fixtures_import(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
        imported = import_record(f.read())
    assert imported.model_id == "perc1_dll" and imported.ref.number == 100001
    assert imported.cons["VDPA"] == 0.90 and len(imported.cons) == 173


def test_tolerates_commas_crlf_and_rewrapped_values():
    text = build_perc1_dyr_block(101, "1", DLL_CONS)
    flat = " ".join(line for line in text.splitlines() if not line.startswith("@!"))
    rewrapped = flat.replace(" ", ",\r\n", 40).replace("/", "\r\n/")
    assert import_record(rewrapped).cons == DLL_CONS


def test_lists_every_record_in_file_order_and_flags_clod():
    dll = build_perc1_dyr_block(1, "1", DLL_CONS)
    std = build_perc1_standard_dyr_block(2, "2", STD_CONS)
    clod = "   3, 'CLODBL', '3', 0.1, 0.2, 0.3, 0.4, 0.5  /"
    refs = list_records(f"{std}\n{clod}\n{dll}")
    assert [(r.model_id, r.number, r.inspectable) for r in refs] == [
        ("perc1_standard", 2, True), ("clod", 3, False), ("perc1_dll", 1, True)]
    assert [r.index for r in refs] == [0, 1, 2]


def test_a_multi_record_file_needs_a_choice_and_the_choice_is_honoured():
    text = "\n".join([build_perc1_dyr_block(1, "1", DLL_CONS), build_perc1_standard_dyr_block(2, "2", STD_CONS)])
    with pytest.raises(ValueError, match="2 records"):
        import_record(text)
    refs = list_records(text)
    imported = import_record(text, refs[1])
    assert imported.model_id == "perc1_standard" and any("2 records" in w for w in imported.warnings)
    assert import_record(text, 0).model_id == "perc1_dll"


def test_two_records_of_one_model_are_told_apart_by_load_id():
    text = "\n".join([build_perc1_dyr_block(1, "1", DLL_CONS), build_perc1_dyr_block(1, "2", {**DLL_CONS, "VDPA": 0.5})])
    refs = list_records(text)
    assert [r.load_id for r in refs] == ["1", "2"]
    assert import_record(text, refs[1]).cons["VDPA"] == 0.5


def test_errors_say_what_is_wrong():
    with pytest.raises(ValueError, match="no PERC1"):
        import_record("@! nothing here\n1 'GENROU' 1 /")
    clod = "3 'CLODBL' '3' 1 2 3 4 5 /"
    with pytest.raises(ValueError, match="CLOD"):
        import_record(clod)
    truncated = build_perc1_dyr_block(1, "1", DLL_CONS).replace(" 0 0\n", " 0 0\n", 1)
    short = "\n".join(truncated.splitlines()[:-1]) + "/"
    with pytest.raises(ValueError, match="got 1[0-9][0-9]"):
        import_record(short)
    with pytest.raises(ValueError, match="expected 30 CON values"):
        import_record(build_perc1_standard_dyr_block(1, "1", STD_CONS).replace(" 1 'PERC1 load'", " 1 'PERC1 load'", 1).rsplit(" ", 2)[0] + " /")
    with pytest.raises(ValueError, match="no record #4"):
        import_record(build_perc1_dyr_block(1, "1", DLL_CONS), 4)


def test_out_of_range_values_import_with_a_warning():
    text = build_perc1_dyr_block(1, "1", {**DLL_CONS, "VDPA": 1.5})
    imported = import_record(text)
    assert imported.cons["VDPA"] == 1.5
    assert any(w.startswith("VDPA = 1.5") for w in imported.warnings)


def test_nonzero_icons_are_warned_about():
    text = build_perc1_dyr_block(1, "1", DLL_CONS).replace("\n 0 0\n", "\n 1 1\n")
    assert any("ICON" in w for w in import_record(text).warnings)


def _vendor_style(text, first_field="IBUS", load_id="'ID '", extra_cons=""):
    """A record shaped like the vendor samples: placeholder first field, vendor load ID, optional V2.3 CONs."""
    header, rest = text.split("\n", 2)[1], text.split("\n", 2)[2]
    _number, _usrlod, _quoted_id, tail = header.split(" ", 3)
    if extra_cons:
        tail = tail.replace(" 173 ", " 179 ", 1)
        rest = rest.rstrip("/") + "\n" + extra_cons + "/"
    return f"{first_field} 'USRLOD' {load_id} {tail}\n{rest}"


def test_vendor_sample_with_a_placeholder_bus_imports_with_a_warning():
    imported = import_record(_vendor_style(build_perc1_dyr_block(1, "1", DLL_CONS)))
    assert imported.cons == DLL_CONS and imported.ref.number == 0 and imported.ref.load_id == "ID "
    assert "IBUS (placeholder)" in imported.ref.label
    assert any("placeholder 'IBUS'" in w for w in imported.warnings)


def test_perc2_v2p3_record_imports_as_the_perc2_dll_with_all_179_cons():
    text = _vendor_style(build_perc1_dyr_block(1, "1", DLL_CONS), first_field="3005", load_id="1",
                         extra_cons=" 0.0 0.0\n 1.0 1.0\n 0.9 1.09")
    imported = import_record(text)
    assert imported.model_id == "perc2_dll" and imported.ref.number == 3005 and imported.ref.load_id == "1"
    assert {k: imported.cons[k] for k in DLL_CONS} == DLL_CONS
    assert {k: imported.cons[k] for k in ("TAQ", "TBQ", "RAMPAMC", "RAMPUAMC", "VLRCMC", "VURCMC")} == {
        "TAQ": 0.0, "TBQ": 0.0, "RAMPAMC": 1.0, "RAMPUAMC": 1.0, "VLRCMC": 0.9, "VURCMC": 1.09}
    assert imported.cons["FREQ50"] == 0 and imported.cons["MCFLAG"] == 0
    assert "PERC2 DLL v2.3" in imported.ref.label


def test_a_con_count_that_is_neither_perc1_nor_v2p3_is_reported():
    text = build_perc1_dyr_block(1, "1", DLL_CONS).replace(" 173 ", " 175 ", 1)
    with pytest.raises(ValueError, match="175 CONs"):
        import_record(text)
