from load_models.perc1_dll.cons import PERC1_CON_ORDER
from presets.ridethrough import (
    RIDE_THROUGH_PRESETS,
    collapsed_overvoltage_point,
    collapsed_point,
    multi_stage_undervoltage,
)


def test_ridethrough_preset_bundles_cover_every_con():
    for preset in RIDE_THROUGH_PRESETS.values():
        for bundle in (preset.it_bundle, preset.vfd_bundle):
            missing = [name for name in PERC1_CON_ORDER if name not in bundle]
            assert not missing, f"{preset.id} is missing CONs: {missing}"


def test_ridethrough_preset_envelopes_sorted_by_voltage():
    for preset in RIDE_THROUGH_PRESETS.values():
        voltages = [step.voltage_pu for step in preset.envelope]
        assert voltages == sorted(voltages), f"{preset.id} envelope not sorted: {voltages}"


def test_ridethrough_preset_con_bundles_agree_with_their_own_envelope():
    """VDPA/DMA/VDUA must always equal collapsed_point()/collapsed_overvoltage_point()
    of the preset's own envelope/overvoltage_envelope - guards against a preset's
    exported CON bundle silently drifting from the envelope table it's supposed to
    summarize (see ridethrough_presets.py's _standard_preset()/_generic_preset())."""
    for preset in RIDE_THROUGH_PRESETS.values():
        undervoltage = collapsed_point(preset.envelope)
        overvoltage = collapsed_overvoltage_point(preset.overvoltage_envelope)
        for bundle in (preset.it_bundle, preset.vfd_bundle):
            assert bundle["VDPA"] == undervoltage.voltage_pu, preset.id
            assert bundle["VDUA"] == overvoltage.voltage_pu, preset.id
        # DMA is the one field the three generic tiers deliberately override for
        # the VFD block (a genuinely longer trip delay, not envelope drift) - see
        # _generic_bundles(); every other preset's IT/DMA must match the envelope.
        assert preset.it_bundle["DMA"] == undervoltage.min_duration_s, preset.id


def test_ridethrough_preset_bundles_encode_full_multistage_curve():
    """PSS/E testing confirmed, via direct PSS/E simulation
    against the real compiled PERC2_V35.dll, that Option 3's 4-stage table is
    always evaluated - so every preset's it_bundle/vfd_bundle must populate
    VDPA1-3/DMA1-3/VDUA1-3/TDUA1-3 from its own real envelope, not leave them
    at PERC1_FIXED_DEFAULTS' vendor-sample values. This guards against
    that regression for every preset in the library, not just one hand-picked
    example (see test_ercot_nogrr282_bundle_matches_the_psse_validated_full_
    curve_fixture below for the one preset pinned to exact, PSS/E-confirmed
    numbers)."""
    for preset in RIDE_THROUGH_PRESETS.values():
        undervoltage_stages = multi_stage_undervoltage(preset.envelope)
        for bundle in (preset.it_bundle, preset.vfd_bundle):
            for suffix, (voltage, _duration) in zip(("", "1", "2", "3"), undervoltage_stages):
                # VFD's own stage delay is an intentional per-block override
                # for the three generic tiers (ridethrough_presets.
                # _generic_bundles()) - only the voltage breakpoints, not the
                # VFD-specific delay, are guaranteed to match the IT-derived
                # multi_stage_undervoltage() list here.
                assert bundle[f"VDPA{suffix}"] == voltage, (preset.id, suffix)

            # Overvoltage: VDUA's own arming voltage is the continuous
            # ceiling (see collapsed_overvoltage_point()'s docstring for why
            # - a published "up to X pu: tolerate at least Y s" row describes
            # the whole band above the continuous ceiling, not a threshold
            # that starts mattering only at X pu). Stages 2-4 arm at the
            # published tier's own (higher-or-equal) voltage with TDUA=0.0 -
            # every preset in this library is explicit that anything above
            # its own highest published tier is an immediate trip condition,
            # never a higher, invented breakpoint.
            vdua = bundle["VDUA"]
            for suffix in ("1", "2", "3"):
                assert bundle[f"VDUA{suffix}"] >= vdua, (preset.id, suffix)
                assert bundle[f"TDUA{suffix}"] == 0.0, (preset.id, suffix)


def test_ercot_nogrr282_bundle_matches_the_psse_validated_full_curve_fixture():
    """The undervoltage side is the exact set of values directly validated
    against the real PERC2_V35.dll in PSS/E (see
    tests/fixtures/multistage_trip/ercot_nogrr282_full_curve_stages.dyr) - pinned here so this
    specific, PSS/E-confirmed-safe encoding can't drift.

    The overvoltage side models ERCOT's own explicit "above 1.20 pu: may ride
    through or trip" language literally, and also its "up to 1.20 pu: must
    tolerate for at least 2.0 s" row correctly as a BAND above the continuous
    ceiling (1.10 pu) - not a threshold that only starts mattering at
    1.20 pu. A swell over 1.10 pu can trip after the published 2.0 s
    (VDUA=1.10/TDUA=2.00); a swell over 1.20 pu can trip immediately,
    regardless of how long (VDUA1-3=1.20/TDUA1-3=0.0). No intermediate
    voltage breakpoint is invented - both 1.10 and 1.20 are ERCOT's own
    published setpoints."""
    bundle = RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle
    assert (bundle["VDPA"], bundle["DMA"]) == (0.90, 2.00)
    assert (bundle["VDPA1"], bundle["DMA1"]) == (0.80, 0.50)
    assert (bundle["VDPA2"], bundle["DMA2"]) == (0.50, 0.25)
    assert (bundle["VDPA3"], bundle["DMA3"]) == (0.20, 0.15)
    assert (bundle["VDUA"], bundle["TDUA"]) == (1.10, 2.00)
    assert (bundle["VDUA1"], bundle["TDUA1"]) == (1.20, 0.0)
    assert (bundle["VDUA2"], bundle["TDUA2"]) == (1.20, 0.0)
    assert (bundle["VDUA3"], bundle["TDUA3"]) == (1.20, 0.0)


def test_ridethrough_preset_categories_are_generic_or_standard():
    for preset in RIDE_THROUGH_PRESETS.values():
        assert preset.category in ("Generic", "Grid operator standard")


def test_collapsed_point_uses_shallowest_mandatory_step():
    ercot = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    point = collapsed_point(ercot.envelope)
    assert point.voltage_pu == 0.90
    assert point.min_duration_s == 2.00


def test_frequency_tables_are_encoded_into_the_single_trip_point():
    """The vendor model has one frequency trip point per direction (stages 2-4
    are NOT USED). It arms at the continuous band's edge with the innermost
    row's duration - PRC-029-1: below 58.8 Hz / above 61.2 Hz for 299 s - and
    reconnects at that same edge. Stages 2-4 keep the vendor's values."""
    from load_models.perc1_dll.cons import PERC1_FIXED_DEFAULTS

    bundle = RIDE_THROUGH_PRESETS["nerc_prc029"].it_bundle

    assert (bundle["FUFTP1"], bundle["TUFTP1"], bundle["FUFRN1"]) == (58.8, 299.0, 58.8)
    assert (bundle["FOFTP1"], bundle["TOFTP1"], bundle["FOFRN1"]) == (61.2, 299.0, 61.2)
    for name in ("FUFTP2", "TUFTP2", "FOFRN3", "RUFRN4"):
        assert bundle[name] == PERC1_FIXED_DEFAULTS[name]


def test_presets_without_a_frequency_table_keep_vendor_frequency_defaults():
    from load_models.perc1_dll.cons import PERC1_FIXED_DEFAULTS

    with_table = {pid for pid, p in RIDE_THROUGH_PRESETS.items() if p.frequency_ride_through}
    assert with_table == {"pjm_lcl", "nerc_prc029"}
    for pid, preset in RIDE_THROUGH_PRESETS.items():
        if pid in with_table:
            continue
        for name in ("FUFTP1", "TUFTP1", "FOFTP1", "TOFTP1", "FUFTP2", "TUFTP2"):
            assert preset.it_bundle[name] == PERC1_FIXED_DEFAULTS[name], (pid, name)


def test_frequency_table_bound_and_trip_permitted():
    table = RIDE_THROUGH_PRESETS["pjm_lcl"].frequency_ride_through

    assert table.bound("under", 100.0) == 57.0
    assert table.bound("under", 299.0) == 58.8
    assert table.bound("over", 100.0) == 61.8
    assert not table.trip_permitted(59.0, 1000.0)  # continuous band
    assert not table.trip_permitted(58.0, 200.0)   # mandatory band, not held long enough
    assert table.trip_permitted(58.0, 300.0)
    assert table.trip_permitted(56.9, 0.1)         # beyond the outermost limit
    assert table.trip_permitted(61.9, 0.1)


def test_every_encoded_frequency_trip_point_complies_with_its_own_table():
    for preset in RIDE_THROUGH_PRESETS.values():
        table = preset.frequency_ride_through
        if table is None:
            continue
        f, d = preset.it_bundle["FUFTP1"], preset.it_bundle["TUFTP1"]
        assert f <= table.bound("under", d), preset.id
        f, d = preset.it_bundle["FOFTP1"], preset.it_bundle["TOFTP1"]
        assert f >= table.bound("over", d), preset.id


def test_every_preset_has_a_concise_short_source():
    for preset in RIDE_THROUGH_PRESETS.values():
        assert preset.short_source, preset.id
        assert len(preset.short_source) <= 80, preset.id


def test_every_preset_page_embeds_current_voltage_and_frequency_figures():
    from pathlib import Path

    docs = Path(__file__).resolve().parents[1] / "docs" / "user"
    for preset in RIDE_THROUGH_PRESETS.values():
        page = (docs / "presets" / f"{preset.id}.md").read_text(encoding="utf-8")
        for figure in (f"envelope_{preset.id}.svg", f"frequency_{preset.id}.svg"):
            assert f"../figures/{figure}" in page, (preset.id, figure)
            assert (docs / "figures" / figure).is_file(), figure
        assert "## Frequency ride-through" in page, preset.id
