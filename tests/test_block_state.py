"""The edit tracker: what a block's parameters are compared against, and what Reset returns to."""

import pytest

from editor.block_state import DEFAULTS, IMPORTED, PRESET, Baseline, EditTracker
from editor.parameter_rows import rows_for
from presets.ridethrough import RIDE_THROUGH_PRESETS

PRESET_VALUES = {"VDPA": 0.7, "DMA": 0.02, "FCEASE": 1.0, "NPA": 0}


def preset_tracker(values=PRESET_VALUES) -> EditTracker:
    return EditTracker(Baseline.from_preset(RIDE_THROUGH_PRESETS["standard_itic"], values))


def test_a_preset_baseline_starts_unedited():
    tracker = preset_tracker()
    assert tracker.baseline.kind == PRESET
    assert tracker.edited_count() == 0 and not tracker.can_reset
    assert tracker.reset_label() == "Reset to preset"
    assert tracker.baseline_note() == "Matches Standard (ITIC/CBEMA)"
    assert tracker.edited_pill() == "0 edited"


def test_an_edit_counts_and_editing_back_clears_it():
    tracker = preset_tracker()
    tracker.set_value("VDPA", 0.6)
    assert tracker.edited_cons() == {"VDPA"} and tracker.edited_count() == 1
    assert tracker.edited_pill() == "1 edited"
    assert tracker.baseline_note() == "Edits are shown against Standard (ITIC/CBEMA)"
    assert tracker.can_reset and tracker.needs_confirmation()
    tracker.set_value("VDPA", 0.7)
    assert tracker.edited_count() == 0 and not tracker.needs_confirmation()


def test_reset_returns_the_preset_values():
    tracker = preset_tracker()
    tracker.set_values({"VDPA": 0.5, "DMA": 1.0})
    assert tracker.reset() == PRESET_VALUES
    assert tracker.edited_count() == 0


def test_an_imported_baseline_keeps_the_file_and_resets_to_its_values():
    tracker = EditTracker(Baseline.from_import({"Vcease": 0.62, "Tt": 0.0123456}, "dc_poi_perc1.dyr", "#1 PERCBL1U"))
    assert tracker.baseline.kind == IMPORTED and tracker.baseline.file_name == "dc_poi_perc1.dyr"
    assert tracker.reset_label() == "Reset to file"
    assert tracker.baseline_note() == "Matches dc_poi_perc1.dyr"
    tracker.set_value("Vcease", 0.5)
    assert tracker.baseline_note() == "Edits are shown against dc_poi_perc1.dyr"
    assert tracker.reset() == {"Vcease": 0.62, "Tt": 0.0123456}


def test_a_value_the_field_cannot_show_exactly_is_not_an_edit():
    """A 4-decimal spin box shows 0.0123456 as 0.0123: within half its last digit of the file's value."""
    tracker = EditTracker(Baseline.from_import({"Tt": 0.0123456}, "f.dyr"), {"Tt": 0.0123}, {"Tt": 0.5e-4 + 1e-12})
    assert not tracker.is_edited("Tt")
    tracker.set_value("Tt", 0.0124)
    assert tracker.is_edited("Tt")


def test_rebasing_to_another_preset_clears_the_edits():
    tracker = preset_tracker()
    tracker.set_value("VDPA", 0.1)
    tracker.rebase(Baseline.from_preset(RIDE_THROUGH_PRESETS["pjm_lcl"], {"VDPA": 0.5}))
    assert tracker.edited_count() == 0
    assert tracker.baseline_note() == f"Matches {RIDE_THROUGH_PRESETS['pjm_lcl'].label}"


def test_defaults_baseline_wording():
    tracker = EditTracker(Baseline.defaults({"A": 1.0}))
    assert tracker.baseline.kind == DEFAULTS
    assert tracker.reset_label() == "Reset to defaults"
    assert tracker.baseline_note() == "Matches the model defaults"


def test_edited_rows_are_the_rows_holding_an_edited_con():
    rows = rows_for("perc1_dll")
    tracker = preset_tracker({"VDPA": 0.7, "FUFTP1": 58.0, "IPMAXA": 1.0, "NPA": 0})
    tracker.set_value("FUFTP1", 57.5)
    tracker.set_value("IPMAXA", 1.2)
    assert tracker.edited_rows(rows) == {"frequency_ride_through", "current_limits"}


@pytest.mark.parametrize("value", ["x", None])
def test_non_numeric_values_compare_by_equality(value):
    tracker = EditTracker(Baseline.defaults({"NAME": "x"}))
    tracker.set_value("NAME", value)
    assert tracker.is_edited("NAME") == (value != "x")
