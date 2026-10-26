"""Parameter rows: one per field group, each CON in exactly one row, with a one-line summary."""

import pytest

from editor.model_ui import DLL_MODEL_ID, STANDARD_MODEL_ID, get_ui_spec
from editor.parameter_rows import row_for_con, rows_for
from presets.ridethrough import RIDE_THROUGH_PRESETS


@pytest.mark.parametrize("model_id", [DLL_MODEL_ID, STANDARD_MODEL_ID])
def test_every_con_is_in_exactly_one_row(model_id):
    spec = get_ui_spec(model_id)
    cons = [c for row in rows_for(model_id) for c in row.cons]
    assert sorted(cons) == sorted(spec.field_names())
    assert len(cons) == len(set(cons))


def test_load_voltage_response_and_current_limits_are_separate_rows():
    rows = {row.id: row for row in rows_for(DLL_MODEL_ID)}
    assert rows["load_voltage_response"].cons == ("NPA", "NQA")
    assert rows["current_limits"].cons == ("IPMAXA", "IPMINA", "IQMAXA", "IQMINA")
    assert [r.title for r in rows_for(DLL_MODEL_ID)] == [
        "Voltage ride-through", "Frequency ride-through", "Trip / reconnect fractions",
        "Load voltage response", "Current limits", "Frequency droop", "Measurement and converter"]


def test_dll_summaries_match_the_design():
    values = get_ui_spec(DLL_MODEL_ID).preset_params(RIDE_THROUGH_PRESETS["standard_itic"], "it")
    summaries = {row.id: row.summary(DLL_MODEL_ID, values) for row in rows_for(DLL_MODEL_ID)}
    assert summaries["voltage_ride_through"] == f"UV {values['VDPA']:.2f} pu · {values['DMA']:.2f} s"
    assert summaries["frequency_ride_through"] == "58.0–62.0 Hz"
    assert summaries["trip_reconnect_fractions"] == "1.00 / 1.00"
    assert summaries["load_voltage_response"] == f"NPA {int(values['NPA'])}"
    assert summaries["current_limits"].startswith("IPMAX ")
    assert summaries["frequency_droop"] == f"DROOPA {values['DROOPA']:g}"


@pytest.mark.parametrize(("ipmax", "text"), [(1.0, "IPMAX 1.0"), (1.2, "IPMAX 1.2"), (1.25, "IPMAX 1.25"), (0, "IPMAX 0")])
def test_current_limit_summary_edge_values(ipmax, text):
    row = row_for_con(rows_for(DLL_MODEL_ID), "IPMAXA")
    assert row.summary(DLL_MODEL_ID, {"IPMAXA": ipmax}) == text


def test_a_missing_value_gives_an_empty_summary():
    row = row_for_con(rows_for(DLL_MODEL_ID), "VDPA")
    assert row.summary(DLL_MODEL_ID, {}) == ""


def test_standard_rows_summarise_their_own_cons():
    values = get_ui_spec(STANDARD_MODEL_ID).preset_params(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
    rows = {row.id: row for row in rows_for(STANDARD_MODEL_ID)}
    assert rows["voltage_ride_through"].summary(STANDARD_MODEL_ID, values).startswith("Vcease ")
    assert rows["current_limits"].summary(STANDARD_MODEL_ID, values) == "Ipmax 1.25"
    assert rows["voltage_ride_through"].sections[0][0] == "Cease"
