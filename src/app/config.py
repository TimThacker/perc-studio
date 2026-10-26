"""Shared configuration values for PERC Studio."""

import os

from app.resources import resource_path

# CURENT (curent.utk.edu) brand green, sampled from the official logo mark.
# This is the app's primary chrome color (header, active tab, buttons, focus
# ring). TVA_NAVY is kept for TVA-specific attribution accents and for the
# response plot's voltage-trace color, which is an unrelated semantic choice
# (see PLOT_VOLTAGE_COLOR in preview/style.py) - it is not part of the app chrome
# palette anymore.
CURENT_GREEN = "#007800"
CURENT_GREEN_DARK = "#004A00"
CURENT_GREEN_ACCENT = "#4CA04C"
CURENT_GREEN_TINT = "#E6F2E6"
CURENT_GREEN_FOCUS = "#8CC28C"

TVA_NAVY = "#003057"
TVA_CHARCOAL = "#4a4a4a"
TVA_ACCENT = "#4a90c4"
TVA_BG = "#f5f7f9"

# Packaged branding assets - both CURENT (originating research center) and TVA
# (development partner) are credited in the app header/footer and the
# generated HTML report footer.
ASSETS_DIR = str(resource_path("assets", "branding"))
CURENT_LOGO_PATH = os.path.join(ASSETS_DIR, "curent_logo.png")
CURENT_ICON_PATH = os.path.join(ASSETS_DIR, "curent_icon.png")
TVA_LOGO_PATH = os.path.join(ASSETS_DIR, "tva_logo.png")
# The CURENT mark on a white square (packaging/make_icon.py) - the window,
# taskbar and desktop-shortcut icon.
APP_ICON_PATH = os.path.join(ASSETS_DIR, "app_icon.ico")

# A local file dropped next to export/report.py under one of these names overrides
# the packaged CURENT_LOGO_PATH above (e.g. for a locally-customized report
# header) without any code change.
LOGO_FILENAME_CANDIDATES = [
    "curent_logo.png",
    "curent_logo.jpg",
    "curent_logo.jpeg",
    "curent_logo.svg",
]

ENGINEERING_TOOL_NOTICE = (
    "Generated profiles are intended for simulation, testing, and engineering "
    "analysis. Users should validate selected assumptions and parameters for "
    "their specific application before relying on exported results."
)

DEFAULTS = {
    "facility_name": "Example Data Center",
    "bus_number": 100001,
    "bus_name": "DC_POI",
    "load_id_it": "1",
    "load_id_vfd": "2",
    "load_id_motor": "3",
    "total_mw": 300.0,
    "power_factor": 0.99,
    "pct_it": 70.0,
    "pct_cooling_vfd": 20.0,
    "pct_cooling_motor": 5.0,
    "pct_other": 5.0,
    "use_case": "AI Training",
    "use_case_pct": 100,
    "screening_active_power_mw": 50.0,
    "screening_reactive_power_mvar": 20.0,
    "it_ups_mode": "Double conversion (online)",
    "it_data_confidence": "Placeholder (generic defaults) - not yet field-validated",
    "it_advanced": False,
    "include_vfd_block": True,
    "vfd_type": "Active front-end (regenerative, near-unity PF)",
    "vfd_data_confidence": "Placeholder (generic defaults) - not yet field-validated",
    "vfd_advanced": False,
    "include_motor_block": False,
    "motor_facility_type": "Mixed - moderate mix of large & small motors",
    "motor_has_lighting": False,
    "motor_advanced": False,
    "has_onsite_gen": False,
    "gen_notes": "",
    "commissioning_status": "In design",
    "commissioning_date": "",
    "site_notes": "",
    "field_measurement_summary": "",
    "prepared_by": "",
    "data_source_note": "",
    "logo_bytes": None,
    "logo_mime": None,
    "logo_filename": None,
}
