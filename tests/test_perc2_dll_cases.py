"""The PERC2 DLL v2.3 through the UI/case converters, .dyr import, the editor, the preview and the report page: the
state <-> case round trip, 173-CON records importing as the PERC1 DLL and 179-CON ones as the PERC2 DLL, the editor
(field set, 0/1 flags, preset values, notes, export, screening) and the report page (RAMPA x LFM, the momentary-
cessation note)."""

import importlib
import json

import pytest
from PySide6.QtWidgets import QApplication, QSpinBox

from blackbox.intake import load_targets, scan_dyr
from dev.cli.main import cli
from dev.validation.case_model import (
    UI_BLOCK_MODELS,
    case_to_ui_state,
    from_json,
    ui_state_to_case,
)
from editor.dyr_import import import_record, list_records
from editor.model_ui import PERC2_DLL_MC_NOTE, get_ui_spec
from editor.parameter_rows import rows_for
from load_models import get_load_model
from load_models.perc1_dll.dyr import build_perc1_dyr_block
from load_models.perc2_dll.cons import (
    CON_NAMES,
    DISPLAY_FIELDS,
    EXTRA_CONS,
    ICON_NAMES,
    RAMP_CONS,
)
from load_models.perc2_dll.dyr import build_perc2_dll_dyr_block, parse_perc2_dll_records
from presets.ridethrough import RIDE_THROUGH_PRESETS
from preview.model import Event, build_preview
from preview.perc2_dll import (
    build_perc2_dll_live_update_js,
    render_perc2_dll_response_page,
)

MODEL = get_load_model("perc2_dll")
# The ERCOT, PJM, MISO and both NERC presets map to VRPA = 1.0, which the v2.3 validate_cons rejects; ITIC does not.
ITIC = RIDE_THROUGH_PRESETS["standard_itic"]
P2D_CONS = MODEL.cons_for_preset(ITIC, "it")
DLL_CONS = get_load_model("perc1_dll").default_cons


def _env(result):
    return json.loads(result.output)


# --- the case model -------------------------------------------------------------------------------------------------


def test_the_ui_offers_perc2_dll_on_it_and_vfd():
    assert "perc2_dll" in UI_BLOCK_MODELS["it"] and "perc2_dll" in UI_BLOCK_MODELS["vfd"]


def test_ui_state_round_trip_keeps_perc2_dll_and_its_cons(cli_runner, tmp_path):
    path = str(tmp_path / "case.json")
    result = cli_runner.invoke(cli, ["params", "generate", "--source", "preset", "--preset-id", "standard_itic",
                                     "--out", path, "--model", "perc2_dll"])
    assert result.exit_code == 0, result.output
    with open(path, encoding="utf-8") as f:
        case = from_json(f.read())
    assert case.it_block.model_id == "perc2_dll"
    state = case_to_ui_state(case)
    assert state["it_model_id"] == "perc2_dll" and "it_adv_MCFLAG" in state and "it_adv_VURCMC" in state
    restored = ui_state_to_case(state)
    assert restored.it_block.model_id == "perc2_dll"
    assert list(restored.it_block.cons) == list(CON_NAMES)
    assert restored.it_block.cons == pytest.approx(case.it_block.cons)


# --- the editor spec ------------------------------------------------------------------------------------------------


def test_the_editor_spec_covers_every_display_con_with_integer_flags():
    spec = get_ui_spec("perc2_dll")
    names = spec.field_names()
    assert len(names) == len(set(names)) and set(names) == {n for n, _label, _tip in DISPLAY_FIELDS}
    assert set(EXTRA_CONS) | set(ICON_NAMES) | {"VLBLK", "VUBLK", "TBLK", "TDELY", "LFM"} <= set(names)
    assert set(spec.field_kinds) == set(names) and set(spec.field_labels) == set(names)
    assert {n for n, kind in spec.field_kinds.items() if kind == "flag"} == set(ICON_NAMES)
    assert {n for n, kind in spec.field_kinds.items() if kind == "zip"} == {"NPA", "NQA"}
    assert all(n in spec.field_ranges for n in names if spec.field_kinds[n] == "float")
    assert list(spec.default_params()) == list(CON_NAMES)
    for name in RAMP_CONS:
        assert "x LFM" in spec.field_tooltips[name] and "x LFM" in spec.field_labels[name], name
    assert "x LFM" not in spec.field_tooltips["RUFRN1"]
    assert {n for n, _label, _tip in spec.display_fields} == set(names)
    assert spec.preset_params(ITIC, "screening") == P2D_CONS


def test_parameter_rows_summarise_the_new_groups():
    rows = {row.id: row for row in rows_for("perc2_dll")}
    assert {"momentary_cessation", "reactive_lead_lag", "system_and_load_basis", "voltage_ride_through"} <= set(rows)
    assert rows["momentary_cessation"].summary("perc2_dll", P2D_CONS) == "off"
    on = {**P2D_CONS, "MCFLAG": 1}
    assert rows["momentary_cessation"].summary("perc2_dll", on) == "below 0.50 / above 1.10 pu"
    assert rows["system_and_load_basis"].summary("perc2_dll", {**P2D_CONS, "FREQ50": 1}).startswith("50 Hz")


def test_notes_show_validate_cons_issues_and_the_momentary_cessation_note():
    notes = get_ui_spec("perc2_dll").notes
    assert notes(P2D_CONS, ITIC) == []
    assert ("info", PERC2_DLL_MC_NOTE) in notes({**P2D_CONS, "MCFLAG": 1}, ITIC)
    assert any(level == "error" and text.startswith("VRPA:") for level, text in notes({**P2D_CONS, "VRPA": 1.05}, None))


# --- .dyr import ----------------------------------------------------------------------------------------------------


def test_173_con_records_import_as_perc1_dll_and_179_con_records_as_perc2_dll():
    assert import_record(build_perc1_dyr_block(1, "1", DLL_CONS)).model_id == "perc1_dll"
    imported = import_record(build_perc2_dll_dyr_block(2, "2", P2D_CONS))
    assert imported.model_id == "perc2_dll" and "PERC2 DLL v2.3" in imported.ref.label
    assert list(imported.cons) == list(CON_NAMES)
    for name in CON_NAMES:
        assert imported.cons[name] == pytest.approx(P2D_CONS[name], rel=1e-5, abs=1e-9), name
    assert imported.warnings == ()


def test_a_file_with_both_dlls_lists_each_record_once():
    text = "\n".join([build_perc1_dyr_block(1, "1", DLL_CONS), build_perc2_dll_dyr_block(2, "2", P2D_CONS),
                      build_perc1_dyr_block(3, "3", DLL_CONS)])
    refs = list_records(text)
    assert [(r.model_id, r.number) for r in refs] == [("perc1_dll", 1), ("perc2_dll", 2), ("perc1_dll", 3)]
    assert import_record(text, refs[1]).model_id == "perc2_dll"
    assert import_record(text, refs[2]).cons == pytest.approx(DLL_CONS)


def test_imported_flags_are_warned_about():
    text = build_perc2_dll_dyr_block(2, "2", {**P2D_CONS, "MCFLAG": 1, "FREQ50": 1, "FUFTP1": 48.0, "FOFTP1": 52.0})
    warnings = import_record(text).warnings
    assert any(w.startswith("MCFLAG (ICON(M+1)) = 1") for w in warnings)
    assert any(w.startswith("FREQ50 (ICON(M)) = 1") for w in warnings)


def test_the_blackbox_intake_reads_the_179_con_header():
    recs = scan_dyr(build_perc2_dll_dyr_block(101, "1", P2D_CONS))
    assert recs[0].header == {"ic": 12, "it": 1, "ni": 2, "nc": 179, "ns": 33, "nv": 250}
    assert len(load_targets(recs)) == 1


# --- preview and report page ----------------------------------------------------------------------------------------


def test_the_preview_and_the_page_ramp_over_the_con_times_lfm():
    cons = {**P2D_CONS, "RAMPA": 10.0, "LFM": 0.5}
    result = build_preview("perc2_dll", cons, Event("voltage", 3.0, 0.5), preset=ITIC, block_mw=100.0)
    assert result.trips and result.ramp == "5.00 s"
    html = render_perc2_dll_response_page(cons, "IT/UPS block", preset=ITIC, block_mw=100.0,
                                          fault_duration_s=3.0, fault_voltage_pu=0.5)
    assert "IT/UPS block · PERC2 DLL v2.3" in html and "Ramp time" in html and PERC2_DLL_MC_NOTE not in html
    assert "Momentary cessation is on" in render_perc2_dll_response_page({**cons, "MCFLAG": 1}, "IT/UPS block")
    assert "Plotly.react" in build_perc2_dll_live_update_js(cons, "IT/UPS block", ITIC, event_kind="frequency")


# --- the desktop editor ---------------------------------------------------------------------------------------------


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    yield win
    win.close()
    app.processEvents()


def _choose(window, block, model_id):
    combo = getattr(window, f"pc_{block}_model_combo")
    combo.setCurrentIndex(combo.findData(model_id))


def test_selecting_perc2_dll_gives_its_fields_flags_and_preset_values(window):
    _choose(window, "it", "perc2_dll")
    fields = window.pc_it_fields
    assert set(fields) == set(get_ui_spec("perc2_dll").field_names())
    for name in ICON_NAMES:
        assert isinstance(fields[name], QSpinBox) and (fields[name].minimum(), fields[name].maximum()) == (0, 1)
    window._apply_preset_to_block("it", "spp_hill")
    expected = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["spp_hill"], "it")
    params = window._collect_block_params("it")
    for name in CON_NAMES:
        assert params[name] == pytest.approx(expected[name], abs=1e-4), name
    assert all(isinstance(params[n], int) for n in ICON_NAMES)
    fields["MCFLAG"].setValue(1)
    assert "Momentary cessation is on" in window.pc_it_notes_label.text()


def test_perc2_dll_state_exports_its_record_and_report(window):
    from export.dyr import build_dyr_text
    from export.report import build_html_report

    _choose(window, "it", "perc2_dll")
    window._apply_preset_to_block("it", "standard_itic")
    window.pc_it_fields["TAQ"].setValue(0.05)
    window.pc_it_fields["TBQ"].setValue(0.1)
    state = window._state_from_post_form()
    assert state["it_model_id"] == "perc2_dll" and state["it_adv_TAQ"] == pytest.approx(0.05)
    text = build_dyr_text(state)
    assert " 12 1 2 179 33 250 0" in text and "PERC2_v35_v2p3.dll" in text
    exported = parse_perc2_dll_records(text)[0]["cons"]
    assert exported["TAQ"] == pytest.approx(0.05) and exported["RAMPA"] == pytest.approx(P2D_CONS["RAMPA"])
    html = build_html_report(state)
    assert "model PERC2 DLL v2.3" in html and "IT/UPS block · PERC2 DLL v2.3" in html


def test_screening_and_preview_with_perc2_dll(window):
    combo = window.pc_screening_model_combo
    combo.setCurrentIndex(combo.findData("perc2_dll"))
    window._generate_screening_output()
    text = window.screening_output.toPlainText()
    assert "PERC2 DLL v2.3" in text and " 12 1 2 179 33 250 0" in text
    _choose(window, "it", "perc2_dll")
    window._refresh_preview("it")
    window.pc_it_kind_group.buttons()[1].click()  # frequency event
    window._refresh_preview("it")
