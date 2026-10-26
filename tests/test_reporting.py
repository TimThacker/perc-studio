
from load_models.perc1_dll import MODEL as PERC1_DLL
from presets.ridethrough import (
    RIDE_THROUGH_PRESETS,
)
from preview.perc1_dll import build_recovery_panel_html, render_perc1_response_page


def test_response_page_marks_trip_and_no_trip_boundaries():
    params = dict(PERC1_DLL.default_cons)
    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]

    page = render_perc1_response_page(
        params, "IT/UPS block", envelope=preset.envelope, envelope_label=preset.label,
        overvoltage_envelope=preset.overvoltage_envelope, include_plotlyjs="cdn",
    )

    assert "No damage expected" in page
    assert "Trip permitted (undervoltage)" in page
    assert "Trip permitted (overvoltage)" in page
    assert "Reconnect" in page
    assert "Vcease" in page
    assert "Vrecon" in page
    assert "recovery-panel" in page
    assert preset.label in page
    assert "ITIC" not in page


def test_response_figure_plots_all_4_stages_per_direction_and_moves_with_edits():
    """Panel 3 must show all 4 undervoltage and all 4 overvoltage Option-3
    stage points, not just VDPA/DMA and VDUA/TDUA - PSS/E testing
    confirmed the compiled DLL always evaluates all 4, so each is a real,
    independent trip condition worth showing. Editing a stage's own CON must
    move only that stage's own marker."""
    from preview.perc1_dll import build_perc1_response_figure

    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    params = dict(preset.it_bundle)

    fig = build_perc1_response_figure(
        params, "IT block", envelope=preset.envelope, envelope_label=preset.label,
        overvoltage_envelope=preset.overvoltage_envelope,
    )
    markers = [t for t in fig.data if t.mode == "markers" and "voltage" in t.name]
    assert len(markers) == 8
    under_markers = [t for t in markers if "undervoltage" in t.name]
    over_markers = [t for t in markers if "overvoltage" in t.name]
    assert len(under_markers) == 4
    assert len(over_markers) == 4
    assert [t.x[0] for t in under_markers] == [2.00, 0.50, 0.25, 0.15]
    assert [t.y[0] for t in under_markers] == [0.90, 0.80, 0.50, 0.20]

    edited = dict(params)
    edited["VDPA1"] = 0.65
    edited["DMA1"] = 1.1
    fig2 = build_perc1_response_figure(
        edited, "IT block", envelope=preset.envelope, envelope_label=preset.label,
        overvoltage_envelope=preset.overvoltage_envelope,
    )
    under_markers2 = [t for t in fig2.data if t.mode == "markers" and "undervoltage" in t.name]
    assert (under_markers2[1].x[0], under_markers2[1].y[0]) == (1.1, 0.65)
    # Every other stage's marker is unaffected by editing stage 2 alone.
    assert (under_markers2[0].x[0], under_markers2[0].y[0]) == (2.00, 0.90)
    assert (under_markers2[2].x[0], under_markers2[2].y[0]) == (0.25, 0.50)
    assert (under_markers2[3].x[0], under_markers2[3].y[0]) == (0.15, 0.20)


def test_response_page_without_preset_shows_placeholder_not_itic():
    params = dict(PERC1_DLL.default_cons)

    page = render_perc1_response_page(params, "IT/UPS block", include_plotlyjs="cdn")

    assert "Select a ride-through preset" in page
    assert "No damage expected" not in page
    assert "ITIC" not in page


def test_recovery_panel_collapses_to_single_state_when_block_rides_through():
    params = {**PERC1_DLL.default_cons, "FCEASE": 0.0}  # rides through: no load trips

    html = build_recovery_panel_html(params, "IT/UPS block")

    assert "rides through" in html.lower()
    assert "Load tripped" not in html


def test_recovery_panel_reports_tripped_and_reconnected_mw():
    params = dict(PERC1_DLL.default_cons)

    html = build_recovery_panel_html(params, "IT/UPS block", block_mw=100.0)

    assert "Load tripped" in html
    assert "100.00 MW" in html
    assert "Ramp time" in html


def test_response_figure_shows_both_tolerance_maps_and_the_frequency_event():
    from preview.perc1_dll import build_perc1_response_figure

    preset = RIDE_THROUGH_PRESETS["nerc_prc029"]
    fig = build_perc1_response_figure(
        dict(preset.it_bundle), "IT block", envelope=preset.envelope, envelope_label=preset.label,
        overvoltage_envelope=preset.overvoltage_envelope,
        frequency_ride_through=preset.frequency_ride_through,
        event_kind="frequency", fault_duration_s=310.0, fault_frequency_hz=58.5,
    )
    names = [t.name or "" for t in fig.data]
    assert sum("frequency trip point" in n for n in names) == 2  # one per direction
    assert sum("voltage trip stage" in n for n in names) == 8
    event = next(t for t in fig.data if t.name == "Simulated event")
    assert (event.x[0], event.y[0]) == (310.0, 58.5)
    titles = [a.text for a in fig.layout.annotations]
    assert "System frequency" in titles
    assert any(title.startswith("Frequency vs. NERC PRC-029-1") and "● OK" in title for title in titles)


def test_frequency_map_without_a_table_shows_the_trip_points_and_says_why():
    from preview.perc1_dll import build_perc1_response_figure

    preset = RIDE_THROUGH_PRESETS["ercot_nogrr282"]
    fig = build_perc1_response_figure(
        dict(preset.it_bundle), "IT block", envelope=preset.envelope, envelope_label=preset.label,
        overvoltage_envelope=preset.overvoltage_envelope,
    )
    text = " ".join(a.text for a in fig.layout.annotations)
    assert "no published frequency table" in text
    points = [t for t in fig.data if "frequency trip point" in (t.name or "")]
    assert [(t.x[0], t.y[0]) for t in points] == [(100.0, 58.0), (100.01, 62.0)]


def test_live_page_has_event_status_and_refits_the_chart_to_its_container():
    params = dict(RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle)

    page = render_perc1_response_page(
        params, "IT/UPS block", include_plotlyjs="cdn", fill_viewport=True,
        event_kind="frequency", fault_duration_s=310.0, fault_frequency_hz=58.5,
    )

    assert 'id="event-status"' in page
    assert "TRIPS" in page and "underfrequency trip" in page
    assert "under-frequency event, 58.50 Hz held 310 s" in page
    assert "ResizeObserver" in page
    assert "after frequency recovers" in page


def test_short_event_on_a_long_timeline_is_labeled_and_the_axis_starts_at_zero():
    """A fast frequency trip followed by the vendor's 100 s reconnect delay
    draws the 1 s event as a sliver on the shared timeline, so it gets an
    arrow label."""
    from preview.perc1_dll import build_perc1_response_figure

    params = dict(RIDE_THROUGH_PRESETS["pjm_lcl"].it_bundle)
    params.update({"FUFTP1": 58.8, "TUFTP1": 0.5})
    fig = build_perc1_response_figure(params, "IT block", event_kind="frequency",
                                      fault_duration_s=1.0, fault_frequency_hz=56.0)

    assert any(a.text == "56.00 Hz for 1.00 s" and a.showarrow for a in fig.layout.annotations)
    assert fig.layout.xaxis.range[0] == 0


def test_frequency_map_shades_the_blocks_deadband():
    from preview.perc1_dll import build_perc1_response_figure

    for preset_id, low, high in (("ercot_nogrr282", 58.0, 62.0), ("pjm_lcl", 58.8, 61.2)):
        preset = RIDE_THROUGH_PRESETS[preset_id]
        fig = build_perc1_response_figure(
            dict(preset.it_bundle), "IT block", envelope=preset.envelope, envelope_label=preset.label,
            overvoltage_envelope=preset.overvoltage_envelope,
            frequency_ride_through=preset.frequency_ride_through,
        )
        bands = [s for s in fig.layout.shapes if s.type == "rect" and (s.y0, s.y1) == (low, high)]
        assert len(bands) == 1, preset_id
        corners = [t for t in fig.data if t.name == "Deadband trip region"]
        assert sorted(t.y[1] for t in corners) == [low, high]
        text = " ".join(a.text for a in fig.layout.annotations)
        assert f"Deadband {low:.2f}-{high:.2f} Hz" in text


def test_frequency_event_timeline_labels_the_deadband_edges():
    from preview.perc1_dll import build_perc1_response_figure

    params = dict(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    fig = build_perc1_response_figure(params, "IT block", event_kind="frequency",
                                      fault_duration_s=20.0, fault_frequency_hz=58.5)
    text = " ".join(a.text for a in fig.layout.annotations)
    assert "Deadband low 58.00 Hz" in text and "Deadband high 62.00 Hz" in text


def test_status_and_recovery_panel_report_a_block_that_stays_tripped():
    """ERCOT's VRPA = 1.00: after a sag, the block stays tripped at a 1.00 pu
    recovery. The status line and recovery strip must say so, not show a
    reconnect."""
    from load_models.perc1_dll.simulation import simulate_perc1_response
    from preview.perc1_dll import event_status

    params = dict(RIDE_THROUGH_PRESETS["ercot_nogrr282"].it_bundle)
    verdict, _color, detail = event_status(simulate_perc1_response(params, 0.5, 0.3))
    html = build_recovery_panel_html(params, "IT/UPS block", fault_duration_s=0.5, fault_voltage_pu=0.3)

    assert verdict == "TRIPS"
    assert "stays tripped" in detail and "reconnects" not in detail
    assert "Does not reconnect" in html and "Ramping" not in html
