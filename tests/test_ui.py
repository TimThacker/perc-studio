import importlib

import pytest
from PySide6.QtWidgets import QApplication

from presets.ridethrough import (
    RIDE_THROUGH_PRESETS,
)


def test_post_commissioning_state_includes_advanced_override_fields():
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    state = window._state_from_post_form()

    assert state["it_advanced"] is True
    assert state["vfd_advanced"] is True
    assert state["motor_advanced"] is True
    assert "it_adv_NPA" in state
    assert "vfd_adv_TDRA" in state
    assert "clod_adv_lm" in state
    # Multi-stage ride-through curve (Option 3) fields must be real, editable
    # widgets in the Advanced panel - not just present in src/load_models/perc1_dll/cons.py's
    # PERC1_DISPLAY_FIELDS - see ui.py's PERC1_FIELD_GROUPS.
    for suffix in ("1", "2", "3"):
        assert f"it_adv_VDPA{suffix}" in state
        assert f"it_adv_DMA{suffix}" in state
        assert f"it_adv_VDUA{suffix}" in state
        assert f"it_adv_TDUA{suffix}" in state
    window.close()
    app.processEvents()


def test_selecting_a_preset_populates_the_multistage_curve_widgets():
    """Selecting ERCOT NOGRR282 in the Post-Commissioning IT block's preset
    dropdown must populate the Advanced editor's new multi-stage widgets with
    that preset's own real 4-stage curve - not just VDPA/DMA/VDUA/TDUA - and
    that curve must match the PSS/E-validated numbers pinned in
    test_ercot_nogrr282_bundle_matches_the_psse_validated_full_curve_fixture."""
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    window._apply_preset_to_block("it", "ercot_nogrr282")

    fields = window.pc_it_fields
    expected = RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle
    for name in ("VDPA", "DMA", "VDPA1", "DMA1", "VDPA2", "DMA2", "VDPA3", "DMA3",
                 "VDUA", "TDUA", "VDUA1", "TDUA1", "VDUA2", "TDUA2", "VDUA3", "TDUA3"):
        assert fields[name].value() == pytest.approx(expected[name]), name
    window.close()
    app.processEvents()


def test_event_toggle_switches_sliders_between_voltage_and_frequency():
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    voltage_depth = window.pc_it_depth_slider.value()

    window.pc_it_kind_group.buttons()[1].click()  # "Frequency event"
    assert window._event_kind("it") == "frequency"
    assert (window.pc_it_depth_slider.minimum(), window.pc_it_depth_slider.maximum()) == (-40, 40)
    window.pc_it_depth_slider.setValue(-12)
    window.pc_it_fault_slider.setValue(240)
    assert window._fault_frequency_hz("it") == pytest.approx(58.8)
    assert window._fault_duration_s("it") == 240.0
    state = window._state_from_post_form()
    assert state["it_event_kind"] == "frequency"
    assert state["it_fault_frequency_hz"] == pytest.approx(58.8)

    window.pc_it_kind_group.buttons()[0].click()  # back to "Voltage event"
    assert window.pc_it_depth_slider.value() == voltage_depth  # voltage setting kept
    window.close()
    app.processEvents()


def test_preset_values_without_an_editor_field_reach_the_preview_and_export():
    """CONs with no editor field must come from the active preset - not the
    vendor defaults - in both the live preview and the exported state."""
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    window._apply_preset_to_block("it", "pjm_lcl")
    bundle = RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle
    fields = window.pc_it_fields

    params = window._collect_block_params("it")
    state = window._state_from_post_form()

    non_field = [name for name in bundle if name not in fields]
    assert non_field
    for name in non_field:
        assert params[name] == bundle[name], name
        assert state[f"it_adv_{name}"] == bundle[name], name
    window.close()
    app.processEvents()


def test_record_format_selector_drives_the_exported_dyr():
    from export import dyr

    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    records = window.pc_records
    assert not records.number_spin.isVisibleTo(window)  # Bus needs no extra number

    records.scope_combo.setCurrentIndex(records.scope_combo.findData("owner"))
    records.number_spin.setValue(7)
    records.load_id_edits["load_id_it"].setText("DC")
    assert records.number_spin.isVisibleTo(window)
    assert records.number_label.text() == "Owner number"

    text = dyr.build_dyr_text(window._state_from_post_form())
    assert "7 'USRLOD' 'DC' 'PERCOW' 12 2 2 173 33 250 0" in text
    window.close()
    app.processEvents()


def test_documentation_tab_navigates_between_documents():
    from PySide6.QtCore import QUrl

    ui = importlib.import_module("ui.main_window")
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow("post-commissioning")
    docs = window.docs_tab

    assert docs.title_label.text() == "Getting started"  # opens on the library's first page
    docs.open_document(ui.PRESET_DOCS_DIR / "README.md")
    docs._on_link(QUrl("pjm_lcl.md"))  # a relative link, as a click delivers it
    assert docs.tree.currentItem().text(0) == RIDE_THROUGH_PRESETS["pjm_lcl"].label
    docs._on_link(QUrl("../model_behavior.md#frequency-droop-is-large-and-always-on"))
    assert docs.title_label.text() == "Model behavior and limitations"
    # The #fragment scrolls to its heading.
    assert docs.browser.textCursor().block().text() == "Frequency droop is large and always on"
    docs.browser.backward()
    assert docs.title_label.text() == RIDE_THROUGH_PRESETS["pjm_lcl"].label

    # A block's "Docs" button opens its preset's page in the same tab.
    window._apply_preset_to_block("it", "ercot_nogrr282")
    window._show_preset_docs("it")
    assert window.tabs.currentWidget() is docs
    assert docs.title_label.text() == RIDE_THROUGH_PRESETS["ercot_nogrr282"].label
    window.close()
    app.processEvents()


def test_every_documentation_entry_exists():
    ui = importlib.import_module("ui.main_window")
    for _group, entries in ui.DocumentationPanel._contents():
        for title, url in entries:
            if url.scheme() != "app":
                path = __import__("pathlib").Path(url.toLocalFile())
                assert path.is_file(), title


def test_preset_badge_and_source_follow_the_preset():
    """The model bar's badge says where the preset comes from ("Internal" for the app's generic tiers,
    "Published standard" otherwise, with the status on hover); the preset's source and citation are on the
    preset selector's tooltip."""
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    for preset in RIDE_THROUGH_PRESETS.values():
        window._apply_preset_to_block("it", preset.id)
        badge = window.pc_it_status_label
        assert badge.text() == ("Internal" if preset.category == "Generic" else "Published standard")
        assert badge.toolTip() == preset.status
        assert preset.short_source in window.pc_it_preset_combo.toolTip()
        assert preset.citation in window.pc_it_preset_combo.toolTip()
    window.close()
    app.processEvents()


def test_frequency_event_opens_the_deadband_controls():
    app = QApplication.instance() or QApplication([])
    window = importlib.import_module("ui.main_window").MainWindow("post-commissioning")
    rows = {s.title_label.text(): s for s in window.pc_it_inner_sections}
    assert not rows["Frequency ride-through"].is_expanded()

    window.pc_it_kind_group.buttons()[1].click()  # "Frequency event"
    assert rows["Frequency ride-through"].is_expanded()
    assert not rows["Voltage ride-through"].is_expanded()
    # the deadband fields are in the opened row's editor
    assert window.pc_it_fields["FUFTP1"].isVisibleTo(rows["Frequency ride-through"])
    window.close()
    app.processEvents()


def test_screening_report_is_perc1_only_and_post_report_is_full():
    import re

    from export import report

    ui = importlib.import_module("ui.main_window")
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow("screening")

    def headings(state):
        html = report.build_html_report(state)
        return [re.sub("<[^>]+>", "", h) for h in re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html)], html

    screening, html = headings(window._state_from_screening_report_form())
    assert screening[0] == "Screening Report"
    assert "Load" in screening and not any("Facility" in h or "Composition" in h for h in screening)
    assert not any("VFD" in h or "Motor" in h for h in screening)
    assert "PSS/E .dyr (PERC1 DLL)" in html

    post, _ = headings(window._state_from_post_form())
    assert post[0] == "Data Center Load Model Report"
    assert "Facility Summary" in post and "Load Composition" in post
    window.close()
    app.processEvents()
