"""The PERC2 DLL v2.3 model package (load_models/perc2_dll). Its rules were measured in PSS/E 35.6.4 and 36.7.1, in the
PSS/E validation library (not published)."""

from __future__ import annotations

import math

import pytest

from load_models import LOAD_MODELS, find_model_for_dyr, get_load_model
from load_models.base import RECORD_SCOPES
from load_models.perc1_dll.cons import PERC1_CON_ORDER
from load_models.perc2_dll import MODEL, preset_gaps, validate_cons
from load_models.perc2_dll.cons import (
    CON_NAMES,
    CON_ONLY_NAMES,
    DEFAULT_CONS,
    EXTRA_CONS,
    ramp_seconds,
)
from load_models.perc2_dll.dyr import (
    build_perc2_dll_dyr_block,
    is_perc2_dll_record,
    parse_perc2_dll_record,
    parse_perc2_dll_records,
)
from load_models.perc2_dll.presets import cons_for_preset
from load_models.perc2_dll.simulation import (
    perc1_equivalent,
    simulate_perc2_dll_response,
)
from presets.ridethrough import RIDE_THROUGH_PRESETS


def _issues(cons, level=None, **kw):
    return {i.con for i in validate_cons(cons, **kw) if level is None or i.level == level}


def test_two_icons_then_the_perc1_dll_cons_then_six_more():
    assert CON_NAMES[:2] == ("FREQ50", "MCFLAG")
    assert CON_ONLY_NAMES[:173] == tuple(PERC1_CON_ORDER)
    assert EXTRA_CONS == ("TAQ", "TBQ", "RAMPAMC", "RAMPUAMC", "VLRCMC", "VURCMC")
    assert len(CON_ONLY_NAMES) == 179


def test_registered_under_its_own_id():
    assert get_load_model("perc2_dll") is MODEL is LOAD_MODELS["perc2_dll"]


def test_defaults_raise_no_issues_and_switch_momentary_cessation_off():
    assert validate_cons(DEFAULT_CONS) == []
    assert DEFAULT_CONS["MCFLAG"] == 0 and DEFAULT_CONS["FREQ50"] == 0


def test_header_says_179_and_the_icons_have_their_own_line():
    text = build_perc2_dll_dyr_block(101, "1", DEFAULT_CONS)
    lines = [ln for ln in text.splitlines() if not ln.startswith("@!")]
    assert lines[0] == "101 'USRLOD' '1' 'PERCBL' 12 1 2 179 33 250 0"
    assert lines[1].split() == ["0", "0"]
    assert text.rstrip().endswith("/")


@pytest.mark.parametrize("scope", sorted(RECORD_SCOPES))
def test_every_scope_round_trips(scope):
    cons = {**DEFAULT_CONS, "MCFLAG": 1}
    text = build_perc2_dll_dyr_block(7, "1", cons, scope)
    got = parse_perc2_dll_record(text)
    assert all(abs(float(got[n]) - float(cons[n])) < 1e-4 for n in CON_NAMES)
    assert got["MCFLAG"] == 1 and isinstance(got["MCFLAG"], int)


def test_perc1_and_perc2_dll_records_are_told_apart_by_their_con_count():
    p1 = LOAD_MODELS["perc1_dll"]
    p1_text = p1.build_dyr_record(101, "1", p1.default_cons)
    p2_text = build_perc2_dll_dyr_block(101, "1", DEFAULT_CONS)
    assert find_model_for_dyr(p1_text) is p1
    assert find_model_for_dyr(p2_text) is MODEL
    assert not is_perc2_dll_record(p1_text) and is_perc2_dll_record(p2_text)
    assert parse_perc2_dll_records(p1_text) == []
    with pytest.raises(ValueError):
        find_model_for_dyr(p1_text + "\n" + p2_text)  # two record types


def test_only_rampa_and_rampua_are_scaled_by_lfm():
    c = {**DEFAULT_CONS, "LFM": 0.5, "RAMPA": 2.0, "RAMPUA": 2.0, "RUFRN1": 2.0, "ROFRN1": 2.0, "RAMPAMC": 2.0,
         "RAMPUAMC": 2.0}
    assert ramp_seconds(c, "RAMPA") == ramp_seconds(c, "RAMPUA") == 1.0
    assert all(ramp_seconds(c, n) == 2.0 for n in ("RUFRN1", "ROFRN1", "RAMPAMC", "RAMPUAMC"))
    assert ramp_seconds({**c, "LFM": 0.0}, "RAMPA") == pytest.approx(1.6)  # LFM < 0.001 -> 0.8


@pytest.mark.parametrize("preset_id", sorted(RIDE_THROUGH_PRESETS))
def test_presets_keep_the_perc1_dll_ramp_seconds(preset_id):
    preset = RIDE_THROUGH_PRESETS[preset_id]
    cons = cons_for_preset(preset, "it")
    b = preset.it_bundle
    assert ramp_seconds(cons, "RAMPA") == pytest.approx(float(b["RAMPA"]), abs=1e-5)
    assert ramp_seconds(cons, "RAMPUA") == pytest.approx(float(b["RAMPUA"]), abs=1e-5)
    assert cons["MCFLAG"] == 0
    assert cons["VRPA"] == min(float(b["VRPA"]), 0.95)
    assert bool(preset_gaps(preset)) == (float(b["VRPA"]) > 0.95)
    assert not [i for i in validate_cons(cons) if i.level == "error"]


def test_hazards_psse_showed_are_flagged():
    d = DEFAULT_CONS
    assert "FCEASE" in _issues({**d, "FCEASE": 1.5}, "error")
    assert "FCEASE" in _issues({**d, "FCEASE": -0.5}, "error")
    assert "FRECON" in _issues({**d, "FRECON": -0.5}, "error")
    assert "RAMPA" in _issues({**d, "RAMPA": -1.0}, "error")
    assert "TA" in _issues({**d, "TA": 2.0, "TB": 0.0}, "error")
    assert "TAQ" in _issues({**d, "TAQ": 2.0, "TBQ": 0.0}, "error")
    assert "TB" in _issues({**d, "TA": 2.0, "TB": 0.5}, "error", psse_version="36.7")
    assert "TB" in _issues({**d, "TA": 2.0, "TB": 0.5}, "warning", psse_version="35.6")
    assert "FREQ50" in _issues({**d, "FREQ50": 1})
    mc = {**d, "MCFLAG": 1, "FRECON": 0.5, "VDPA2": 0.5}
    assert "VUBLK" in _issues(mc, "error", psse_version="36.7")
    assert {"FRECON", "VLBLK"} <= _issues(mc, "warning")
    assert "VLRCMC" in _issues({**mc, "VLRCMC": 0.95, "VURCMC": 0.9}, "error")
    assert "VURCMC" in _issues({**mc, "VURCMC": 0.98}, "error")


def test_momentary_cessation_in_the_simulator():
    mc = {**DEFAULT_CONS, "MCFLAG": 1, "FCEASE": 0.6, "FRECON": 0.5, "VLBLK": 0.5, "VLRCMC": 0.8, "TBLK": 0.1,
          "TDELY": 0.05, "RAMPAMC": 0.6, "TVM": 0.02,
          **{f"VDPA{s}": 0.0 for s in ("", "1", "2", "3")}}
    r = simulate_perc2_dll_response(mc, 0.4, 0.3)
    assert r["trip_type"] == "low-voltage momentary cessation"
    assert r["trip_events"][0]["time"] == pytest.approx(0.5 + 0.02 * math.log(0.7 / 0.2), abs=1e-3)  # filtered V crosses 0.5
    ev = r["reconnect_events"][0]
    assert ev["end"] - ev["start"] == pytest.approx(0.6)  # RAMPAMC, not x LFM
    assert r["reconnects"] and not r["escalated"]
    # a stage at 0.5 pu / 0.3 s takes over a longer sag
    r2 = simulate_perc2_dll_response({**mc, "VDPA": 0.5, "DMA": 0.3, "TDRA": 0.3}, 0.5, 0.3)
    assert r2["escalated"] and r2["reconnect_events"][0]["kind"] == "under"


def test_perc1_equivalent_converts_ramps_and_lfm():
    p = perc1_equivalent({**DEFAULT_CONS, "LFM": 0.0, "RAMPA": 10.0, "TDRA": -1.0})
    assert p["LFM"] == 0.8 and p["RAMPA"] == pytest.approx(8.0) and p["TDRA"] == 0.0
