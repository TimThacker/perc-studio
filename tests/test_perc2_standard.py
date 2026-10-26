"""The PERC2 standard model (PSS/E 36.7 PERCxx2U): record format, validated limits, preset mapping. Every number asserted
here was measured in PSS/E 36.7.1, in the PSS/E validation library (not published)."""


import pytest

from load_models import LOAD_MODELS, find_model_for_dyr, get_load_model
from load_models.base import RECORD_SCOPES
from load_models.perc2_standard import MODEL, preset_gaps, validate_cons
from load_models.perc2_standard.cons import (
    CON_NAMES,
    CON_ONLY_NAMES,
    CON_SPECS,
    DEFAULT_CONS,
    ICON_NAMES,
    effective_limits,
    long_time_point,
    post_fault_peak_pu,
)
from load_models.perc2_standard.dyr import (
    build_perc2_standard_dyr_block,
    parse_perc2_standard_header,
    parse_perc2_standard_record,
    parse_perc2_standard_records,
)
from load_models.perc2_standard.presets import RECONNECT_VOLTAGE_CEILING
from presets.ridethrough import RIDE_THROUGH_PRESETS


def _record_lines(text):
    return [line for line in text.splitlines() if not line.startswith("@!")]


# --- layout ------------------------------------------------------------------------------------------------------------

def test_six_flags_then_57_cons_in_data_sheet_order():
    assert ICON_NAMES == ("VLMflag", "VHMflag", "VLLflag", "VLHflag", "FLflag", "FHflag")
    assert len(CON_ONLY_NAMES) == 57 and CON_NAMES == ICON_NAMES + CON_ONLY_NAMES
    # the slots the earlier exploration got wrong, as PSS/E confirmed them
    assert CON_ONLY_NAMES[2:5] == ("Tt", "Tv", "Tf")
    assert CON_ONLY_NAMES[23:33] == ("fcease", "VLcease", "VHcease", "Tcease", "Tdelay", "frecon", "VLrecon", "VHrecon",
                                     "Tramp", "Trecon")
    assert CON_ONLY_NAMES[35:43] == ("VLC1", "TVLC1", "VLC2", "TVLC2", "VLC3", "TVLC3", "VLC4", "TVLC4")
    assert CON_ONLY_NAMES[-4:] == ("FLC1", "TFLC1", "FHC1", "TFHC1")
    assert tuple(CON_SPECS) == CON_NAMES


def test_registered_under_its_own_id():
    assert get_load_model("perc2_standard") is MODEL
    assert MODEL.dyr_model_name == "PERCBL2U"
    assert set(LOAD_MODELS) >= {"perc1_dll", "perc1_standard", "perc2_standard", "clod"}


def test_default_cons_raise_no_validation_issues():
    assert validate_cons(DEFAULT_CONS) == []
    assert DEFAULT_CONS["Tdelay"] == 0.0


# --- the .dyr record -----------------------------------------------------------------------------------------------------

def test_record_has_the_documented_header_and_flags_before_the_cons():
    main, perc = _record_lines(build_perc2_standard_dyr_block(101, "1", DEFAULT_CONS))[:2]
    assert main.startswith("101 'MAINBL10' '1' 1 0 0 0 0 0 0 0 0 0  1 0 0 0 0 0 0 0 0 0 /")
    assert perc.startswith("101 'USRLODC' '1' 'PERCBL2U' 230 1 6 57 8 44 16 1 'PERC2 load' 1 0 0 0 0 0")


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_every_scope_names_its_model_and_it(scope):
    number = 0 if scope == "all" else 7
    text = build_perc2_standard_dyr_block(number, "1", DEFAULT_CONS, scope=scope)
    sc = RECORD_SCOPES[scope]
    assert f"'PERC{sc.suffix}2U' 230 {sc.it} 6 57 8 44 16" in text and f"'MAIN{sc.suffix}10'" in text
    assert parse_perc2_standard_header(text)["scope"] == scope
    assert find_model_for_dyr(text) is MODEL


def test_record_round_trips_with_integer_flags():
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
    parsed = parse_perc2_standard_record(build_perc2_standard_dyr_block(101, "A1", cons))
    assert parsed == pytest.approx(cons)
    assert all(isinstance(parsed[n], int) for n in ICON_NAMES)


def test_partial_load_adds_a_static_remainder_and_records_parse_with_their_fraction():
    text = build_perc2_standard_dyr_block(5, "1", DEFAULT_CONS, load_fraction=0.3)
    assert "'LSTCBL'" in text
    [rec] = parse_perc2_standard_records(text)
    assert rec["load_fraction"] == pytest.approx(0.3) and rec["error"] is None


def test_wrong_value_count_is_reported_not_parsed():
    good = build_perc2_standard_dyr_block(101, "1", DEFAULT_CONS)
    bad = good.replace(" 100 /", " /", 1)
    assert parse_perc2_standard_records(bad)[0]["error"]
    with pytest.raises(ValueError):
        parse_perc2_standard_record(bad)


def test_values_psse_would_turn_into_nonsense_are_refused():
    for bad in ({"Imax": 0.0}, {"Ipmax": 0.0, "Ipmin": 1.0}, {"VHcease": 0.9}, {"FLflag": 1, "FLC1": 60.5}):
        with pytest.raises(ValueError):
            build_perc2_standard_dyr_block(101, "1", {**DEFAULT_CONS, **bad})
    with pytest.raises(ValueError):
        build_perc2_standard_dyr_block(101, "ABC", DEFAULT_CONS)


# --- validate_cons: what PSS/E 36.7.1 does with each value ------------------------------------------------------------

def _issue(cons, con):
    return [i for i in validate_cons({**DEFAULT_CONS, **cons}) if i.con == con]


def test_vhcease_caps_the_reconnect_window_even_with_the_high_check_off():
    [issue] = _issue({"VHMflag": 0, "VHcease": 0.0}, "VHcease")
    assert issue.level == "error" and "never reconnects" in issue.message


def test_ldfact_above_ipmax_cannot_carry_its_own_load():
    issues = _issue({"Ldfact": 1.5, "Ipmax": 1.25}, "Ipmax")
    assert issues and "83%" in issues[0].message


def test_long_point_3_is_timed_by_point_1():
    assert long_time_point(3) == 1 and long_time_point(2) == 2
    [issue] = _issue({"VLLflag": 1, "VLC1": 0.5, "VLC2": 0.5, "VLC4": 0.5, "VLC3": 0.6, "VLrecon": 0.7}, "VLC3")
    assert "TVLC1" in issue.message


def test_a_long_point_above_the_reconnect_window_warns_of_cycling():
    [issue] = _issue({"VLLflag": 1, "VLC1": 0.9, "VLrecon": 0.7, "VLC2": 0.5, "VLC4": 0.5}, "VLC1")
    assert "cycling" in issue.message


def test_thresholds_on_the_wrong_side_of_nominal_cease_at_t0():
    assert _issue({"VLMflag": 1, "VLcease": 1.05, "VLrecon": 1.06}, "VLcease")[0].level == "error"
    assert _issue({"FLflag": 1, "FLC1": 60.0}, "FLC1")[0].level == "error"


def test_flags_other_than_0_and_1_are_flagged():
    assert _issue({"VLMflag": 2}, "VLMflag")


def test_limits_follow_the_block_diagram_not_note_16():
    ip_hi, ip_lo, iq_hi, iq_lo = effective_limits({**DEFAULT_CONS, "Ipmax": 1.25, "Ipmin": -2.0, "Imax": 1.0, "Iqmax": 2.0},
                                                  ip=0.8)
    assert (ip_hi, ip_lo) == (1.0, -1.0)
    assert iq_hi == pytest.approx(0.6) and iq_lo == pytest.approx(-0.6)
    assert effective_limits({**DEFAULT_CONS, "Imax": -1.0})[0] == 1.0  # |Imax|


def test_post_fault_peak_uses_the_imax_cap():
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 0.0, "Ipmax": 1.25, "Imax": 2.0, "Ldfact": 0.8}) == pytest.approx(1.5625)
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 0.0, "Ipmax": 1.25, "Imax": 1.0, "Ldfact": 0.8}) == pytest.approx(1.25)
    assert post_fault_peak_pu({**DEFAULT_CONS, "nP": 1.0}) == 1.0


# --- presets -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("preset_id", list(RIDE_THROUGH_PRESETS))
@pytest.mark.parametrize("block", ["it", "vfd"])
def test_every_preset_maps_to_cons_psse_takes_as_written(preset_id, block):
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS[preset_id], block)
    assert validate_cons(cons) == []
    assert cons["VLC3"] == 0.0 and cons["VHC3"] == 99.0  # point 3 off
    assert cons["VLrecon"] <= RECONNECT_VOLTAGE_CEILING
    assert cons["VLrecon"] >= max(cons[f"VLC{i}"] for i in (1, 2, 4))  # no cycling
    assert cons["VHrecon"] <= min(cons[f"VHC{i}"] for i in (1, 2, 4)) and cons["VHrecon"] <= cons["VHcease"]
    assert cons["Tramp"] * cons["Ldfact"] == pytest.approx(RIDE_THROUGH_PRESETS[preset_id].it_bundle["RAMPA"]
                                                          if block == "it" else
                                                          RIDE_THROUGH_PRESETS[preset_id].vfd_bundle["RAMPA"])


def test_a_four_stage_preset_puts_its_deepest_stage_on_the_momentary_check():
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
    assert (cons["VLMflag"], cons["VLcease"], cons["Tcease"]) == (1, 0.2, 0.15)
    assert [(cons[f"VLC{i}"], cons[f"TVLC{i}"]) for i in (1, 2, 4)] == [(0.9, 2.0), (0.8, 0.5), (0.5, 0.25)]
    assert (cons["Trecon"], cons["Tramp"]) == (cons["TLreconL"], cons["TLrampL"])


def test_preset_gaps_name_the_permanent_frequency_cease_and_the_reconnect_ceiling():
    gaps = preset_gaps(RIDE_THROUGH_PRESETS["ercot_nogrr282"])
    assert any("never reconnects" in g for g in gaps) and any("0.95" in g for g in gaps)


# --- the PSS/E library ----------------------------------------------------------------------------------------------------
