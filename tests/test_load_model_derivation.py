from load_models.clod.cons import derive_clod_params
from load_models.perc1_dll import MODEL as PERC1_DLL
from load_models.perc1_dll.cons import (
    PERC1_CON_ORDER,
    PERC1_DEFAULT_CONS,
    PERC1_FIXED_DEFAULTS,
)

# The PERC1 DLL's 10 core CONs, as the removed qualitative derivation set them for its default answers
# (double conversion, Standard ITIC/CBEMA tier, full facility trips, staged reconnect). Snapshotted before
# that derivation was removed, so the literal defaults that replaced it are pinned to the same values.
_SNAPSHOT_CORE_CONS = {
    "NPA": 0, "NQA": 0, "TRA": 0.02, "VDPA": 0.7, "DMA": 0.02, "FCEASE": 1.0,
    "VRPA": 0.9, "TDRA": 60.0, "RAMPA": 30.0, "FRECON": 1.0,
}


def test_perc1_dll_default_cons_match_the_snapshot():
    assert PERC1_DLL.default_cons == PERC1_DEFAULT_CONS
    assert list(PERC1_DEFAULT_CONS) and set(PERC1_DEFAULT_CONS) == set(PERC1_CON_ORDER)
    expected = {**PERC1_FIXED_DEFAULTS, **_SNAPSHOT_CORE_CONS}
    for suffix in ("1", "2", "3"):
        expected[f"VDPA{suffix}"], expected[f"DMA{suffix}"] = 0.7, 0.02
        expected[f"VDUA{suffix}"], expected[f"TDUA{suffix}"] = PERC1_FIXED_DEFAULTS["VDUA"], PERC1_FIXED_DEFAULTS["TDUA"]
    assert PERC1_DEFAULT_CONS == expected


def test_perc1_dll_defaults_repeat_single_point_into_every_trip_stage():
    """The defaults have no multi-tier data to encode, so they repeat their single VDPA/DMA (and VDUA/TDUA)
    point into every Option-3 stage rather than leaving PERC1_FIXED_DEFAULTS' vendor-sample values - the same
    regression test_ridethrough_preset_bundles_encode_full_multistage_curve guards for presets."""
    params = PERC1_DEFAULT_CONS
    for suffix in ("1", "2", "3"):
        assert params[f"VDPA{suffix}"] == params["VDPA"]
        assert params[f"DMA{suffix}"] == params["DMA"]
        assert params[f"VDUA{suffix}"] == params["VDUA"]
        assert params[f"TDUA{suffix}"] == params["TDUA"]


def test_derive_clod_params_handles_defaults():
    params = derive_clod_params("Mixed - moderate mix of large & small motors", False)

    assert params["PC_LM"] == 35.0
    assert params["PC_SM"] == 35.0
    assert params["PC_TX"] == 5.0
    assert params["PC_DL"] == 5.0
    assert params["PC_CP"] == 10.0


def test_stage_labels_are_numbered():
    from load_models.perc1_dll.cons import PERC1_DISPLAY_FIELDS

    labels = {name: label for name, label, _ in PERC1_DISPLAY_FIELDS}
    assert labels["VDPA"] == "Undervoltage stage 1 trip (pu)"
    assert labels["DMA2"] == "Undervoltage stage 3 delay (s)"
    assert labels["VDUA3"] == "Overvoltage stage 4 trip (pu)"
    assert not any(ordinal in label for label in labels.values() for ordinal in ("2nd", "3rd", "4th"))


def test_frequency_trip_points_are_labeled_as_a_deadband():
    from load_models.perc1_dll.cons import PERC1_DISPLAY_FIELDS

    labels = {name: label for name, label, _ in PERC1_DISPLAY_FIELDS}
    assert labels["FUFTP1"] == "Frequency deadband low (Hz)"
    assert labels["FOFTP1"] == "Frequency deadband high (Hz)"
    assert labels["TUFTP1"] == "Trip delay below deadband (s)"
    assert labels["TOFTP1"] == "Trip delay above deadband (s)"
