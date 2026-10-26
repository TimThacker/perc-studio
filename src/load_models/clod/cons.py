"""CLOD (PSS/E composite motor load) composition fields and derivation."""


# Short descriptions shown alongside each CLOD composition parameter -
# mirrors load_models.perc1_dll.cons.PERC1_DISPLAY_FIELDS as the single source of truth for both
# the desktop UI (advanced editor, review table) and the HTML report.
CLOD_DISPLAY_FIELDS = [
    ("PC_LM", "PC_LM — large motor share (big constant-speed motors: chillers, large pumps)"),
    ("PC_SM", "PC_SM — small motor share (small fans/pumps, fractional-hp motors)"),
    ("PC_TX", "PC_TX — transformer exciting current share (nearby transformer magnetizing current)"),
    ("PC_DL", "PC_DL — discharge lighting share (fluorescent/HID lighting)"),
    ("PC_CP", "PC_CP — constant power share (electronically regulated load)"),
]


def derive_clod_params(facility_type, has_lighting):
    presets = {
        "Modern - large chillers, mostly VFD elsewhere, some fixed-speed backup": {
            "PC_LM": 60.0,
            "PC_SM": 15.0,
            "PC_TX": 5.0,
            "PC_DL": 0.0,
            "PC_CP": 15.0,
        },
        "Mixed - moderate mix of large & small motors": {
            "PC_LM": 35.0,
            "PC_SM": 35.0,
            "PC_TX": 5.0,
            "PC_DL": 5.0,
            "PC_CP": 10.0,
        },
        "Legacy - many small fixed-speed fan/pump motors, older CRAC units": {
            "PC_LM": 15.0,
            "PC_SM": 55.0,
            "PC_TX": 5.0,
            "PC_DL": 10.0,
            "PC_CP": 5.0,
        },
    }
    p = dict(presets.get(facility_type, presets["Mixed - moderate mix of large & small motors"]))
    if has_lighting:
        shift = min(10.0, p["PC_LM"] + p["PC_SM"])
        if shift > 0:
            lm_share = p["PC_LM"] / (p["PC_LM"] + p["PC_SM"])
            p["PC_LM"] -= shift * lm_share
            p["PC_SM"] -= shift * (1 - lm_share)
            p["PC_DL"] += shift
    return p
