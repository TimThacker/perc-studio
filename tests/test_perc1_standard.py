"""The PERC1 standard model (PSS/E 36.7 PERCxx1U): record format, validated limits,
preset mapping. Every number asserted here was measured in PSS/E 36.7.1, in the PSS/E
validation library (not published)."""


import pytest

from load_models import LOAD_MODELS, find_model_for_dyr, get_load_model
from load_models.base import RECORD_SCOPES
from load_models.perc1_standard import MODEL, preset_gaps, validate_cons
from load_models.perc1_standard.cons import (
    CON_NAMES,
    CON_SPECS,
    DEFAULT_CONS,
    SHEET_EXAMPLE_CONS,
    TDELAY_HAZARD,
)
from load_models.perc1_standard.dyr import (
    build_perc1_standard_dyr_block,
    parse_perc1_standard_header,
    parse_perc1_standard_record,
)
from load_models.perc1_standard.presets import RECONNECT_VOLTAGE_CEILING
from presets.ridethrough import RIDE_THROUGH_PRESETS


def _record_lines(text):
    return [line for line in text.splitlines() if not line.startswith("@!")]


# --- layout -------------------------------------------------------------------

def test_thirty_cons_in_data_sheet_order():
    assert len(CON_NAMES) == 30
    assert CON_NAMES[0] == "Ldfact" and CON_NAMES[4] == "Kdroop" and CON_NAMES[19] == "fcease"
    assert CON_NAMES[-3:] == ("Tt", "Tv", "Tf")


def test_registered_under_its_own_id_not_as_the_dll_model():
    assert get_load_model("perc1_standard") is MODEL
    assert MODEL.dyr_model_name == "PERCBL1U"
    assert set(LOAD_MODELS) >= {"perc1_dll", "perc1_standard", "clod"}


def test_defaults_are_the_sheet_example_with_four_documented_changes():
    changed = {n for n in CON_NAMES if DEFAULT_CONS[n] != SHEET_EXAMPLE_CONS[n]}
    assert changed == {"Tdelay", "Kvp", "Kvq", "Kdroop", "nP", "nQ"}
    assert DEFAULT_CONS["Tdelay"] == 0.0


def test_default_cons_raise_no_validation_issues():
    assert validate_cons(DEFAULT_CONS) == []


def test_every_con_has_a_spec_and_the_sheet_limits():
    assert tuple(CON_SPECS) == CON_NAMES
    assert CON_SPECS["dbfl"].hi == 0.0 and CON_SPECS["dbfh"].lo == 0.0
    assert CON_SPECS["fcease"].lo == 0.0 and CON_SPECS["fcease"].hi == 1.0


# --- the record -----------------------------------------------------------------

def test_record_matches_the_data_sheet_syntax():
    text = build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS)
    main, perc = _record_lines(text)
    assert main.startswith("101 'MAINBL10' '1' 1 0 0 0 0 0 0 0 0 0  1 0 0 0 0 0 0 0 0 0 /")
    # IBUS 'USRLODC' ID 'PERCxx1U' 230 IT 0 30 8 24 2 CompNum 'CompDesc' CON(J)..CON(J+29) /
    assert perc.startswith("101 'USRLODC' '1' 'PERCBL1U' 230 1 0 30 8 24 2 1 'PERC1 load' ")
    assert perc.endswith(" /")
    assert len(perc.split("'PERC1 load' ")[1].removesuffix(" /").split()) == 30


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_each_scope_writes_matching_suffix_it_and_main(scope):
    suffix, it = RECORD_SCOPES[scope].suffix, RECORD_SCOPES[scope].it
    number = 0 if scope == "all" else 7
    main, perc = _record_lines(build_perc1_standard_dyr_block(number, "1", DEFAULT_CONS, scope=scope))
    assert f"'MAIN{suffix}10'" in main
    assert f"'PERC{suffix}1U' 230 {it} 0 30 8 24 2 1" in perc
    assert main.split()[0] == perc.split()[0] == str(number)
    assert parse_perc1_standard_header(perc)["scope"] == scope


def test_partial_load_adds_a_static_remainder_with_fraction_minus_one():
    main, _perc, static = _record_lines(build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS, load_fraction=0.3))
    assert "0.3 -1 0 0 0 0 0 0 0 0" in main and "1 1 0 0 0 0 0 0 0 0" in main
    assert static.startswith("101 'LSTCBL' '1' 2 'Static remainder' ")
    assert len(static.split("'Static remainder' ")[1].removesuffix(" /").split()) == 11


def test_component_slot_moves_the_main_entry_and_header():
    main, perc = _record_lines(build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS, component=2))
    assert " 0 1 0 0 0 0 0 0 0 0  0 1 0 0 0 0 0 0 0 0 /" in main
    assert "2 'PERC1 load'" in perc


def test_round_trip_through_parse():
    cons = {**DEFAULT_CONS, "Vcease": 0.8, "Tramp": 12.5, "Iqmin": -0.65}
    assert parse_perc1_standard_record(build_perc1_standard_dyr_block(101, "A1", cons)) == pytest.approx(cons)


def test_parse_handles_continuation_lines_and_comments():
    text = ("@! comment\n101 'USRLODC' '1' 'PERCBL1U' 230 1 0 30 8 24 2 1 'EV'\n   "
            + " ".join(f"{DEFAULT_CONS[n]:g}" for n in CON_NAMES[:10]) + "\n   "
            + " ".join(f"{DEFAULT_CONS[n]:g}" for n in CON_NAMES[10:]) + " /\n")
    assert parse_perc1_standard_record(text) == pytest.approx(DEFAULT_CONS)


def test_parse_rejects_other_headers_and_the_dll_record():
    good = build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS)
    for bad in (good.replace(" 230 ", " 12 "), good.replace(" 24 2 1 ", " 24 0 1 "), good.replace("'USRLODC'", "'USRLOD'")):
        with pytest.raises(ValueError):
            parse_perc1_standard_record(bad)
    dll = get_load_model("perc1_dll").build_dyr_record(101, "1", get_load_model("perc1_dll").default_cons)
    with pytest.raises(ValueError):
        parse_perc1_standard_record(dll)


def test_each_models_records_are_found_only_by_that_model():
    standard = build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS)
    dll_model = get_load_model("perc1_dll")
    assert find_model_for_dyr(standard) is MODEL
    assert find_model_for_dyr(dll_model.build_dyr_record(101, "1", dll_model.default_cons)) is dll_model


def test_builder_rejects_what_psse_rejects_or_cannot_represent():
    for bad in ({"dbfl": 0.01}, {"dbfh": -0.01}, {"Ipmax": 0.0, "Ipmin": 1.0}, {"Iqmax": -0.7, "Iqmin": 0.7}):
        with pytest.raises(ValueError):
            build_perc1_standard_dyr_block(101, "1", {**DEFAULT_CONS, **bad})
    with pytest.raises(ValueError, match="load_fraction"):
        build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS, load_fraction=0.0)
    with pytest.raises(ValueError, match="component"):
        build_perc1_standard_dyr_block(101, "1", DEFAULT_CONS, component=11)
    with pytest.raises(ValueError):
        build_perc1_standard_dyr_block(101, "ABC", DEFAULT_CONS)  # PSS/E load ids are two characters


# --- validate_cons ----------------------------------------------------------------

@pytest.mark.parametrize(("override", "level", "con"), [
    ({"dbfl": 0.005}, "error", "dbfl"),
    ({"dbfh": -0.005}, "error", "dbfh"),
    ({"Ipmax": 0.4, "Ipmin": 0.5}, "error", "Ipmax"),
    ({"Iqmax": -0.8}, "error", "Iqmax"),
    ({"Tdelay": 0.05}, "warning", "Tdelay"),
    ({"Ldfact": 0.0}, "warning", "Ldfact"),
    ({"Ldfact": 1.2}, "warning", "Ldfact"),
    ({"fcease": 1.2}, "warning", "fcease"),
    ({"Vrecon": 0.4, "Vcease": 0.5}, "warning", "Vrecon"),
    ({"Vrecon": 1.0}, "warning", "Vrecon"),
    ({"Tcease": -1.0}, "warning", "Tcease"),
    ({"Tt": 0.005}, "warning", "Tt"),
    ({"Kvp": 0.2, "Tvp": 0.0}, "warning", "Tvp"),
    ({"Tbp": 0.0, "Tap": 1.0}, "warning", "Tap"),
])
def test_validate_cons_flags_exactly_what_psse_changes_or_rejects(override, level, con):
    issues = validate_cons({**DEFAULT_CONS, **override})
    assert any(i.level == level and i.con == con for i in issues), issues


def test_tdelay_hazard_text_names_the_failure():
    assert "NaN" in TDELAY_HAZARD and "Tdelay = 0" in TDELAY_HAZARD


def test_validate_cons_reports_missing_and_non_finite():
    assert validate_cons({"Ldfact": 0.8})[0].level == "error"
    assert validate_cons({**DEFAULT_CONS, "Vcease": float("nan")})[0].level == "error"


# --- presets ----------------------------------------------------------------------

@pytest.mark.parametrize("preset_id", list(RIDE_THROUGH_PRESETS))
@pytest.mark.parametrize("block", ["it", "vfd"])
def test_preset_cons_are_clean_and_exportable(preset_id, block):
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS[preset_id], block)
    assert set(cons) == set(CON_NAMES)
    assert validate_cons(cons) == []
    assert cons["Tdelay"] == 0.0
    assert cons["Vcease"] <= cons["Vrecon"] <= RECONNECT_VOLTAGE_CEILING
    assert parse_perc1_standard_record(MODEL.build_dyr_record(101, "1", cons)) == pytest.approx(cons)


def test_preset_cease_point_is_the_collapsed_envelope_point_and_droop_is_rescaled():
    from presets.ridethrough import collapsed_point

    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    cons = MODEL.cons_for_preset(preset, "it")
    point = collapsed_point(preset.envelope)
    assert (cons["Vcease"], cons["Tcease"]) == (point.voltage_pu, point.min_duration_s)
    # DLL: dP/P0 = DROOPA * df. Standard: dP/MVA = Kdroop * df with MVA = P0 / Ldfact  =>  Kdroop = DROOPA * Ldfact.
    assert cons["Kdroop"] == pytest.approx(preset.it_bundle["DROOPA"] * preset.it_bundle["LFM"])
    assert cons["Ldfact"] == preset.it_bundle["LFM"]


def test_preset_vrecon_of_1_pu_is_capped_so_the_load_can_reconnect():
    assert RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle["VRPA"] == 1.0
    assert MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")["Vrecon"] == RECONNECT_VOLTAGE_CEILING


def test_only_it_and_vfd_blocks_have_presets():
    with pytest.raises(ValueError, match="'it' and 'vfd'"):
        MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "motor")


def test_preset_gaps_name_what_the_single_cycle_model_cannot_hold():
    assert preset_gaps(RIDE_THROUGH_PRESETS["extended"]) == []
    prc = preset_gaps(RIDE_THROUGH_PRESETS["nerc_prc029"])
    assert any("undervoltage envelope" in g for g in prc)
    assert any("overvoltage" in g for g in prc)
    assert any("frequency" in g for g in prc)


# --- the PSS/E library ---------------------------------------------------------------

# --- the post-fault power peak ---------------------------------------------------------

def test_post_fault_peak_is_ipmax_over_ldfact_for_constant_power_and_absent_otherwise():
    from load_models.perc1_standard.cons import (
        post_fault_peak_pu,
        post_fault_peak_warning,
    )

    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 0.0, "Ipmax": 1.25, "Ldfact": 0.8}) == pytest.approx(1.5625)
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 0.0, "Ipmax": 1.0, "Ldfact": 1.0}) == 1.0
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 1.0, "Ipmax": 3.0}) == 1.0
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 2.0}) == 1.0
    assert post_fault_peak_warning({**DEFAULT_CONS, "nP": 1.0, "Ipmax": 3.0}) is None
    assert post_fault_peak_warning({**DEFAULT_CONS, "Ipmax": 1.0, "Ldfact": 1.0}) is None
    text = post_fault_peak_warning({**DEFAULT_CONS, "nP": 0.0, "Ipmax": 1.25, "Ldfact": 0.8})
    assert "156%" in text and "Ipmax" in text
