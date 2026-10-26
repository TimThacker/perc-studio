"""Per-model description of the parameter editor: which fields a model has, how they are
grouped, labelled and bounded, and where their starting values come from.

The desktop UI builds its Advanced editor from a `ModelUiSpec`, so choosing a PERC1
variant swaps the whole field set. The DLL variant's field groups, labels and bounds
were moved here unchanged from ui/main_window.py; the standard variant's come from
`load_models.perc1_standard.cons.CON_SPECS`, whose limits were measured in PSS/E 36.7.1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from load_models import get_load_model
from load_models.common import flag_on
from load_models.perc1_dll.cons import (
    PERC1_DISPLAY_FIELDS,
    PERC1_FIXED_DEFAULTS,
    PERC1_ZIP_FIELDS,
    ZIP_EXPONENT_MAP,
)
from load_models.perc1_standard.cons import (
    CON_SPECS,
    DEFAULT_CONS,
    post_fault_peak_warning,
    validate_cons,
)
from load_models.perc1_standard.presets import preset_gaps
from load_models.perc2_dll.cons import DISPLAY_FIELDS as PERC2_DLL_DISPLAY_FIELDS
from load_models.perc2_dll.cons import ICON_NAMES as PERC2_DLL_FLAG_NAMES
from load_models.perc2_dll.cons import RAMP_CONS as PERC2_DLL_RAMP_CONS
from load_models.perc2_dll.cons import validate_cons as perc2_dll_validate_cons
from load_models.perc2_standard.cons import CON_SPECS as PERC2_CON_SPECS
from load_models.perc2_standard.cons import DEFAULT_CONS as PERC2_DEFAULT_CONS
from load_models.perc2_standard.cons import ICON_NAMES as PERC2_FLAG_NAMES
from load_models.perc2_standard.cons import (
    post_fault_peak_warning as perc2_post_fault_peak_warning,
)
from load_models.perc2_standard.cons import validate_cons as perc2_validate_cons
from load_models.perc2_standard.presets import preset_gaps as perc2_preset_gaps

DLL_MODEL_ID = "perc1_dll"
STANDARD_MODEL_ID = "perc1_standard"
PERC2_MODEL_ID = "perc2_standard"
PERC2_DLL_MODEL_ID = "perc2_dll"
# The built-in PSS/E 36.7 models, which share the data sheets' CON names (fcease, frecon, nP, ...).
STANDARD_STYLE_MODEL_IDS = (STANDARD_MODEL_ID, PERC2_MODEL_ID)

# Field kinds edited as integers, with their spin-box range: the DLL's ZIP selectors and PERC2's 0/1 flags.
INTEGER_FIELD_RANGES = {"zip": (0, 2), "flag": (0, 1)}


def uses_standard_names(model_id: str) -> bool:
    """A model whose CONs carry the PSS/E data-sheet names (fcease/frecon), not the DLL's (FCEASE/FRECON)."""
    return model_id in STANDARD_STYLE_MODEL_IDS

# Advanced PERC1 fields exposed for hand-editing. Names are the real PSS/E PERC1 CON
# mnemonics (see load_models.perc1_dll.cons.PERC1_DISPLAY_FIELDS, the single source of truth shared with
# the HTML report) - not a fictional simplified parameter set - so a value entered
# here maps directly onto a specific CON in the exported .dyr record. NPA/NQA are a
# genuine 3-way ZIP exponent selector (0/1/2), not a continuous value, so they get a
# spin box restricted to that range rather than a decimal field.
PERC1_ADVANCED_FIELDS = [
    (name, label, "zip" if name in PERC1_ZIP_FIELDS else "float")
    for name, label, _tooltip in PERC1_DISPLAY_FIELDS
]
_PERC1_FIELD_KIND = {name: kind for name, _label, kind in PERC1_ADVANCED_FIELDS}
_PERC1_FIELD_LABEL = {name: label for name, label, _tooltip in PERC1_DISPLAY_FIELDS}
# The CON mnemonic (plus PSS/E-model alias, e.g. "Vcease / VDPA", where one
# exists) - shown as a hover tooltip on the plain-English label above, not
# inline, since an engineer who wants "trip voltage (pu)" to read at a glance
# shouldn't have to parse "Vcease / VDPA —" first to get there.
_PERC1_FIELD_TOOLTIP = {name: tooltip for name, _label, tooltip in PERC1_DISPLAY_FIELDS}

# The inner-level grouping for the nested "Advanced adjustments" disclosure
# - splits the ~17 advanced CONs across named,
# independently-collapsible sub-groups instead of one flat list. Under-
# and over-voltage share one "Voltage ride-through" group (not split into a
# separate "high-voltage trip" group) since they're the same underlying
# concept - a voltage tolerance band - just its low and high edges.
#
# All 4 stages per direction live in this ONE group, not a separate
# "Option 3" group - PSS/E testing confirmed the compiled DLL
# always evaluates all 4 stages, for every facility, with no ICON/flag to
# disable stages 2-4 the way Option 2 has ICON(M+1) (see docs/developer/PERC1_MODEL.md's
# "Option 3 is always live" section). Presenting them in a separate,
# same-looking collapsible group as if they were an optional add-on mode
# would misrepresent that - there is no "off" state, so the group's own
# title says so directly rather than relying on someone finding that fact in
# a doc. Selecting a preset fills every stage in from that standard's own
# multi-tier table automatically; hand-edit here only when a facility's real
# curve differs from every preset.
#
# Each entry is (title, field_names, note?) for a flat group, or
# (title, [(sub_title, field_names), ...], note?) for a group with its own
# nested sub-menus - `note` (if present) renders as a plain-text line above
# that group's fields; see the field-group construction loop below.
PERC1_FIELD_GROUPS = [
    (
        "Voltage ride-through",
        [
            ("Undervoltage trip stages", ["VDPA", "DMA", "VDPA1", "DMA1", "VDPA2", "DMA2", "VDPA3", "DMA3"]),
            ("Undervoltage reconnect", ["VRPA", "TDRA", "RAMPA"]),
            ("Overvoltage trip stages", ["VDUA", "TDUA", "VDUA1", "TDUA1", "VDUA2", "TDUA2", "VDUA3", "TDUA3"]),
            ("Overvoltage reconnect", ["VRUPA", "TRUPA", "RAMPUA"]),
        ],
        (
            "4 stages per direction - all always active; the model has no way to disable "
            "stages 2-4, which repeat stage 1 unless a preset or an edit sets them. Each "
            "direction reconnects through its own settings."
        ),
    ),
    (
        "Frequency ride-through",
        [
            ("Frequency deadband", ["FUFTP1", "FOFTP1"]),
            ("Trip delays", ["TUFTP1", "TOFTP1"]),
            ("Under-frequency reconnect", ["FUFRN1", "TUFRN1", "RUFRN1"]),
            ("Over-frequency reconnect", ["FOFRN1", "TOFRN1", "ROFRN1"]),
        ],
        (
            "A deadband: the block rides through indefinitely between its low and high "
            "edges and trips once outside for the delay (the vendor model has one frequency "
            "trip point per direction). Presets with a published frequency table (PJM LCL, "
            "NERC PRC-029-1) set it from that table; otherwise it is the vendor-typical "
            "58.0-62.0 Hz with 100 s delays."
        ),
    ),
    ("Trip / reconnect fractions", ["FCEASE", "FRECON"]),
    ("Load voltage response", ["NPA", "NQA"]),
    ("Current limits", ["IPMAXA", "IPMINA", "IQMAXA", "IQMINA"]),
    ("Frequency droop", ["DROOPA"]),
    ("Measurement and converter", ["TRA"]),
]


# Physically-meaningful (min, max) bounds per CON - a blanket -1000..1000 range let
# an engineer enter values (e.g. a negative trip voltage, or a 900-second numerical
# filter constant) that make the simulated response meaningless. Bounds follow each
# CON's real-world role: pu voltages are fractions of nominal, fractions are 0-1,
# timers are non-negative with a generous but bounded ceiling, VDUA/high-voltage
# trip is an *overvoltage* threshold so its floor is 1.0 (nominal), not 0.
PERC1_FIELD_RANGES: dict[str, tuple[float, float]] = {
    "VDPA": (0.0, 1.0),      # Vcease - undervoltage trip threshold, pu
    "DMA": (0.0, 10.0),      # Tcease - trip delay, s
    "FCEASE": (0.0, 1.0),    # fraction that trips
    "VRPA": (0.0, 1.2),      # Vrecon - reconnect voltage threshold, pu
    "TDRA": (0.0, 3600.0),   # Trecon - reconnect delay, s (up to an hour for "manual")
    "RAMPA": (0.0, 3600.0),  # Tramp - reconnect ramp, s
    "FRECON": (0.0, 1.0),    # fraction that reconnects
    "TRA": (0.0, 10.0),      # Tt - numerical filter constant, s
    "VDUA": (1.0, 2.0),      # overvoltage trip threshold, pu (must exceed nominal)
    "TDUA": (0.0, 10.0),     # overvoltage trip delay, s
    "DROOPA": (0.0, 100.0),  # frequency droop gain
    "IPMAXA": (0.0, 3.0),    # active current ceiling, pu
    "IPMINA": (-1.0, 3.0),   # active current floor, pu
    "IQMAXA": (0.0, 3.0),    # reactive current ceiling, pu
    "IQMINA": (-3.0, 1.0),   # reactive current floor, pu (often negative - absorbing)
    # Option-3 stages 2-4 - same bounds as their stage-1 counterparts above
    # (VDPA/DMA, VDUA/TDUA).
    "VDPA1": (0.0, 1.0), "DMA1": (0.0, 10.0),
    "VDPA2": (0.0, 1.0), "DMA2": (0.0, 10.0),
    "VDPA3": (0.0, 1.0), "DMA3": (0.0, 10.0),
    "VDUA1": (1.0, 2.0), "TDUA1": (0.0, 10.0),
    "VDUA2": (1.0, 2.0), "TDUA2": (0.0, 10.0),
    "VDUA3": (1.0, 2.0), "TDUA3": (0.0, 10.0),
    # Frequency trip points: under-frequency below nominal, over-frequency above.
    "FUFTP1": (45.0, 60.0), "TUFTP1": (0.0, 3600.0),
    "FOFTP1": (60.0, 75.0), "TOFTP1": (0.0, 3600.0),
    "FUFRN1": (45.0, 60.0), "TUFRN1": (0.0, 3600.0), "RUFRN1": (0.0, 3600.0),
    "FOFRN1": (60.0, 75.0), "TOFRN1": (0.0, 3600.0), "ROFRN1": (0.0, 3600.0),
    # High-side voltage reconnect (overvoltage trips).
    "VRUPA": (0.9, 2.0), "TRUPA": (0.0, 3600.0), "RAMPUA": (0.0, 3600.0),
}




# --- the standard variant (PSS/E 36.7 PERCxx1U) ----------------------------------------------

STANDARD_FIELD_LABELS = {name: spec.label + (f" ({spec.unit})" if spec.unit else "") for name, spec in CON_SPECS.items()}
STANDARD_FIELD_TOOLTIPS = {name: f"{name}. {spec.note}".strip() for name, spec in CON_SPECS.items()}
STANDARD_FIELD_KINDS = dict.fromkeys(CON_SPECS, "float")
# The editor's bounds: the sheet's own limits where it states them, otherwise generous but finite.
STANDARD_FIELD_RANGES: dict[str, tuple[float, float]] = {
    "Ldfact": (0.01, 1.0), "QPratio": (-2.0, 2.0), "dbfl": (-0.1, 0.0), "dbfh": (0.0, 0.1), "Kdroop": (0.0, 100.0),
    "Kvp": (-10.0, 10.0), "Tvp": (0.0, 100.0), "Kvq": (-10.0, 10.0), "Tvq": (0.0, 100.0),
    "Tap": (0.0, 100.0), "Tbp": (0.0, 100.0), "Taq": (0.0, 100.0), "Tbq": (0.0, 100.0),
    "nP": (-2.0, 4.0), "nQ": (-2.0, 4.0),
    "Ipmax": (0.0, 3.0), "Ipmin": (-1.0, 3.0), "Iqmax": (0.0, 3.0), "Iqmin": (-3.0, 1.0),
    "fcease": (0.0, 1.0), "Vcease": (0.0, 1.2), "Tcease": (0.0, 3600.0), "Tdelay": (0.0, 10.0),
    "Vrecon": (0.0, 1.2), "Trecon": (0.0, 3600.0), "Tramp": (0.0, 3600.0), "frecon": (0.0, 5.0),
    "Tt": (0.0, 10.0), "Tv": (0.0, 10.0), "Tf": (0.0, 10.0),
}
STANDARD_FIELD_DECIMALS = {"dbfl": 5, "dbfh": 5}

STANDARD_FIELD_GROUPS = [
    (
        "Voltage ride-through",
        [
            ("Cease", ["Vcease", "Tcease", "fcease", "Tdelay"]),
            ("Reconnect", ["Vrecon", "Trecon", "Tramp", "frecon"]),
        ],
        (
            "One undervoltage cycle: the load ceases when the filtered voltage stays below Vcease for Tcease, and "
            "ramps back after the voltage has stayed above Vrecon for Trecon. There is no overvoltage, frequency or "
            "multi-stage trip in this model. Keep Tdelay at 0 (an edge-case behavior of PSS/E 36.7.1)."
        ),
    ),
    ("Load voltage response", ["Ldfact", "QPratio", "nP", "nQ"]),
    ("Current limits", ["Ipmax", "Ipmin", "Iqmax", "Iqmin"]),
    (
        "Frequency droop",
        ["Kdroop", "dbfl", "dbfh"],
        "Power follows frequency: dP = Kdroop x (df - deadband), in pu of the MVA base. 0 disables.",
    ),
    ("Power-path dynamics", ["Kvp", "Tvp", "Tap", "Tbp"]),
    ("Reactive-path dynamics", ["Kvq", "Tvq", "Taq", "Tbq"]),
    ("Measurement and converter", ["Tt", "Tv", "Tf"]),
]


# --- PERC2 standard (PSS/E 36.7 PERCxx2U) ------------------------------------------------------------

PERC2_FIELD_LABELS = {name: spec.label + (f" ({spec.unit})" if spec.unit and spec.unit != "flag" else "")
                      for name, spec in PERC2_CON_SPECS.items()}
PERC2_FIELD_TOOLTIPS = {name: f"{name}. {spec.note}".strip() for name, spec in PERC2_CON_SPECS.items()}
PERC2_FIELD_KINDS = {name: ("flag" if name in PERC2_FLAG_NAMES else "float") for name in PERC2_CON_SPECS}
_PERC2_TIME = (0.0, 3600.0)
PERC2_FIELD_RANGES: dict[str, tuple[float, float]] = {
    "Ldfact": (0.01, 2.0), "QPratio": (-2.0, 2.0), "Tt": (0.0, 10.0), "Tv": (0.0, 10.0), "Tf": (0.0, 10.0),
    "dbfl": (-0.1, 0.0), "dbfh": (0.0, 0.1), "Kdroop": (0.0, 100.0),
    "Kvp": (-10.0, 10.0), "Tvp": (0.0, 100.0), "Kvq": (-10.0, 10.0), "Tvq": (0.0, 100.0),
    "Tap": (0.0, 100.0), "Tbp": (0.0, 100.0), "Taq": (0.0, 100.0), "Tbq": (0.0, 100.0),
    "nP": (-2.0, 4.0), "nQ": (-2.0, 4.0),
    "Ipmax": (0.0, 3.0), "Ipmin": (-1.0, 3.0), "Iqmax": (0.0, 3.0), "Iqmin": (-3.0, 1.0), "Imax": (0.0, 5.0),
    "fcease": (0.0, 1.0), "VLcease": (0.0, 1.2), "VHcease": (0.0, 99.0), "Tcease": _PERC2_TIME, "Tdelay": (0.0, 10.0),
    "frecon": (0.0, 5.0), "VLrecon": (0.0, 1.2), "VHrecon": (0.0, 99.0), "Tramp": _PERC2_TIME, "Trecon": _PERC2_TIME,
    "TLrampL": _PERC2_TIME, "TLreconL": _PERC2_TIME, "TLrampH": _PERC2_TIME, "TLreconH": _PERC2_TIME,
    **{f"VLC{i}": (0.0, 1.2) for i in range(1, 5)}, **{f"TVLC{i}": _PERC2_TIME for i in range(1, 5)},
    **{f"VHC{i}": (0.0, 99.0) for i in range(1, 5)}, **{f"TVHC{i}": _PERC2_TIME for i in range(1, 5)},
    "FLC1": (45.0, 75.0), "TFLC1": _PERC2_TIME, "FHC1": (45.0, 75.0), "TFHC1": _PERC2_TIME,
    **{name: INTEGER_FIELD_RANGES["flag"] for name in PERC2_FLAG_NAMES},
}
PERC2_FIELD_DECIMALS = {"dbfl": 5, "dbfh": 5}

PERC2_FIELD_GROUPS = [
    ("Ride-through checks", list(PERC2_FLAG_NAMES),
     ("Six independent checks, each on (1) or off (0). The momentary and long voltage checks reconnect through "
      "their own settings; a frequency cease never reconnects.")),
    (
        "Voltage ride-through",
        [
            ("Momentary cease", ["VLcease", "VHcease", "Tcease", "Tdelay", "fcease"]),
            ("Reconnect", ["VLrecon", "VHrecon", "Trecon", "Tramp", "frecon"]),
        ],
        ("The load ceases (FracOn = 1 - fcease) when the filtered voltage stays below VLcease or above VHcease for "
         "Tcease, and ramps back over Tramp x Ldfact after staying inside VLrecon < V < VHrecon for Trecon. That "
         "window applies to every voltage cease; VHrecon is capped at VHcease even with the high check off."),
    ),
    (
        "Long low-voltage ride-through",
        [
            ("Points", ["VLC1", "TVLC1", "VLC2", "TVLC2", "VLC3", "TVLC3", "VLC4", "TVLC4"]),
            ("Reconnect after a long low-voltage cease", ["TLreconL", "TLrampL"]),
        ],
        ("A 4-point table: below VLCx for TVLCx. PSS/E 36.7.1 times point 3 with TVLC1, not TVLC3; the presets leave "
         "it off (VLC3 = 0). A point above VLrecon makes a sag between them cease, reconnect and cease again."),
    ),
    (
        "Long high-voltage ride-through",
        [
            ("Points", ["VHC1", "TVHC1", "VHC2", "TVHC2", "VHC3", "TVHC3", "VHC4", "TVHC4"]),
            ("Reconnect after a long high-voltage cease", ["TLreconH", "TLrampH"]),
        ],
        "Above VHCx for TVHCx. Point 3 waits TVHC1 in PSS/E 36.7.1; the presets leave it off (VHC3 = 99).",
    ),
    ("Frequency ride-through", ["FLC1", "TFLC1", "FHC1", "TFHC1"],
     ("Below FLC1 or above FHC1 for the time: the load ceases for good (no reconnect). Frequency is held at "
      "nominal while the bus voltage is below 0.7 pu.")),
    ("Load voltage response", ["Ldfact", "QPratio", "nP", "nQ"]),
    ("Current limits", ["Ipmax", "Ipmin", "Iqmax", "Iqmin", "Imax"],
     "Active current has priority: the reactive limits shrink to sqrt(Imax^2 - Ip^2)."),
    ("Frequency droop", ["Kdroop", "dbfl", "dbfh"],
     "Power follows frequency: dP = Kdroop x (df - deadband), in pu of the MVA base. 0 disables."),
    ("Power-path dynamics", ["Kvp", "Tvp", "Tap", "Tbp"]),
    ("Reactive-path dynamics", ["Kvq", "Tvq", "Taq", "Tbq"]),
    ("Measurement and converter", ["Tt", "Tv", "Tf"]),
]


def _perc2_notes(params: dict, preset) -> list[tuple[str, str]]:
    notes = [(issue.level, f"{issue.con}: {issue.message}") for issue in perc2_validate_cons(params)]
    if (peak := perc2_post_fault_peak_warning(params)) is not None:
        notes.append(("warning", f"Post-fault power peak: {peak}"))
    if preset is not None:
        notes += [("info", f"Not represented: {gap}") for gap in perc2_preset_gaps(preset)]
    return notes


# --- PERC2 DLL v2.3 (PERC2_v35/v36_v2p3.dll) -------------------------------------------------------
#
# The PERC1 DLL's 173 CONs with six appended, plus its two ICONs as 0/1 flags. The shared CONs keep the PERC1 DLL's
# labels, bounds and groups; the one behavior that differs is that v2.3 stretches the voltage reconnect ramps (RAMPA,
# RAMPUA) by LFM (load_models.perc2_dll.cons.RAMP_CONS, ramp_seconds), so their labels and tooltips say so.

PERC2_DLL_FIELD_LABELS = {name: (label.replace("(s)", "(s, x LFM)") if name in PERC2_DLL_RAMP_CONS else label)
                          for name, label, _tooltip in PERC2_DLL_DISPLAY_FIELDS}
PERC2_DLL_FIELD_TOOLTIPS = {
    name: tooltip + (f". In PSS/E this ramp lasts {name} x LFM (PERC2 DLL v2.3)" if name in PERC2_DLL_RAMP_CONS else "")
    for name, _label, tooltip in PERC2_DLL_DISPLAY_FIELDS
}
PERC2_DLL_FIELD_KINDS = {
    name: ("flag" if name in PERC2_DLL_FLAG_NAMES else _PERC1_FIELD_KIND.get(name, "float"))
    for name, _label, _tooltip in PERC2_DLL_DISPLAY_FIELDS
}
PERC2_DLL_FIELD_RANGES: dict[str, tuple[float, float]] = {
    **PERC1_FIELD_RANGES,
    "VLBLK": (0.0, 1.2), "VUBLK": (0.9, 99.0), "TBLK": (0.0, 3600.0), "TDELY": (0.0, 10.0),
    "VLRCMC": (0.0, 1.2), "VURCMC": (0.9, 99.0), "RAMPAMC": (0.0, 3600.0), "RAMPUAMC": (0.0, 3600.0),
    "TAQ": (0.0, 100.0), "TBQ": (0.0, 100.0), "LFM": (0.0, 2.0),
    **{name: INTEGER_FIELD_RANGES["flag"] for name in PERC2_DLL_FLAG_NAMES},
}

PERC2_DLL_FIELD_GROUPS = [
    *PERC1_FIELD_GROUPS,
    (
        "Momentary cessation",
        [
            ("Cessation", ["MCFLAG", "VLBLK", "VUBLK"]),
            ("Return", ["VLRCMC", "VURCMC", "TBLK", "TDELY", "RAMPAMC", "RAMPUAMC"]),
        ],
        ("MCFLAG (ICON(M+1)) = 1 turns it on: the block stops drawing current while the voltage is below VLBLK or "
         "above VUBLK, and comes back inside VLRCMC < V < VURCMC over RAMPAMC / RAMPUAMC (s, not scaled by LFM). Every preset leaves "
         "it off (MCFLAG = 0), and then these CONs are unused."),
    ),
    ("Reactive lead-lag", ["TAQ", "TBQ"],
     "TAQ = TBQ = 0 bypasses it (the vendor sample's values). TAQ without TBQ makes PSS/E return NaN."),
    (
        "System and load basis",
        ["FREQ50", "LFM"],
        ("FREQ50 (ICON(M)) = 1 is meant for a 50 Hz system, but both DLL builds ignore it and work at 60 Hz. LFM "
         "sets the MVA base (MW / LFM) and, in v2.3, the voltage reconnect ramps: RAMPA and RAMPUA last their CON x "
         "LFM in PSS/E (the frequency and momentary-cessation ramps do not)."),
    ),
]

# Shown in the editor and on the report page while MCFLAG = 1.
PERC2_DLL_MC_NOTE = ("Momentary cessation is on (MCFLAG = 1): the preview models it as measured in PSS/E "
                     "(see the PERC2 DLL model page).")


def _perc2_dll_notes(params: dict, preset) -> list[tuple[str, str]]:
    notes = [(issue.level, f"{issue.con}: {issue.message}") for issue in perc2_dll_validate_cons(params)]
    if flag_on(params, "MCFLAG"):
        notes.append(("info", PERC2_DLL_MC_NOTE))
    return notes


def _dll_default_params() -> dict:
    params = dict(PERC1_FIXED_DEFAULTS)
    params["TRA"] = 0.02
    return params


def _dll_preset_params(preset, block_key: str) -> dict:
    return dict(preset.vfd_bundle if block_key == "vfd" else preset.it_bundle)


def _dll_mode_updates(mode: str) -> dict:
    value = ZIP_EXPONENT_MAP.get(mode, 1)
    return {"NPA": value, "NQA": value}


def _standard_mode_updates(mode: str) -> dict:
    value = float(ZIP_EXPONENT_MAP.get(mode, 1))
    return {"nP": value, "nQ": value}


def _dll_notes(params: dict, preset) -> list[tuple[str, str]]:
    return []


def _standard_notes(params: dict, preset) -> list[tuple[str, str]]:
    """(level, text) lines for the editor and the report: what PSS/E will change, and what this model cannot hold."""
    notes = [(issue.level, f"{issue.con}: {issue.message}") for issue in validate_cons(params)]
    if (peak := post_fault_peak_warning(params)) is not None:
        notes.append(("warning", f"Post-fault power peak: {peak}"))
    if preset is not None:
        notes += [("info", f"Not represented: {gap}") for gap in preset_gaps(preset)]
    return notes


@dataclass(frozen=True)
class ModelUiSpec:
    model_id: str
    choice_label: str
    field_groups: list
    field_kinds: dict
    field_labels: dict
    field_tooltips: dict
    field_ranges: dict
    field_decimals: dict
    display_fields: tuple
    default_params: Callable[[], dict]
    preset_params: Callable[[object, str], dict]
    mode_updates: Callable[[str], dict]
    notes: Callable[[dict, object], list]
    # "dll" drives the original four-panel response figure (the PERC1 DLL and the PERC2 DLL v2.3); "standard" the
    # single-cycle model's own; "perc2" PERC2's.
    preview: str

    @property
    def model(self):
        return get_load_model(self.model_id)

    def field_names(self) -> list[str]:
        names: list[str] = []
        for group in self.field_groups:
            content = group[1]
            if content and isinstance(content[0], tuple):
                for _title, fields in content:
                    names += fields
            else:
                names += content
        return names


UI_SPECS: dict[str, ModelUiSpec] = {
    DLL_MODEL_ID: ModelUiSpec(
        model_id=DLL_MODEL_ID,
        choice_label="PERC1 DLL (PSS/E 34/35)",
        field_groups=PERC1_FIELD_GROUPS,
        field_kinds=_PERC1_FIELD_KIND,
        field_labels=_PERC1_FIELD_LABEL,
        field_tooltips=_PERC1_FIELD_TOOLTIP,
        field_ranges=PERC1_FIELD_RANGES,
        field_decimals={},
        display_fields=tuple(PERC1_DISPLAY_FIELDS),
        default_params=_dll_default_params,
        preset_params=_dll_preset_params,
        mode_updates=_dll_mode_updates,
        notes=_dll_notes,
        preview="dll",
    ),
    STANDARD_MODEL_ID: ModelUiSpec(
        model_id=STANDARD_MODEL_ID,
        choice_label="PERC1 Standard (PSS/E 36.7+)",
        field_groups=STANDARD_FIELD_GROUPS,
        field_kinds=STANDARD_FIELD_KINDS,
        field_labels=STANDARD_FIELD_LABELS,
        field_tooltips=STANDARD_FIELD_TOOLTIPS,
        field_ranges=STANDARD_FIELD_RANGES,
        field_decimals=STANDARD_FIELD_DECIMALS,
        display_fields=tuple((n, STANDARD_FIELD_LABELS[n], STANDARD_FIELD_TOOLTIPS[n]) for n in CON_SPECS),
        default_params=lambda: dict(DEFAULT_CONS),
        preset_params=lambda preset, block_key: get_load_model(STANDARD_MODEL_ID).cons_for_preset(
            preset, "vfd" if block_key == "vfd" else "it"),
        mode_updates=_standard_mode_updates,
        notes=_standard_notes,
        preview="standard",
    ),
    PERC2_MODEL_ID: ModelUiSpec(
        model_id=PERC2_MODEL_ID,
        choice_label="PERC2 Standard (PSS/E 36.7+)",
        field_groups=PERC2_FIELD_GROUPS,
        field_kinds=PERC2_FIELD_KINDS,
        field_labels=PERC2_FIELD_LABELS,
        field_tooltips=PERC2_FIELD_TOOLTIPS,
        field_ranges=PERC2_FIELD_RANGES,
        field_decimals=PERC2_FIELD_DECIMALS,
        display_fields=tuple((n, PERC2_FIELD_LABELS[n], PERC2_FIELD_TOOLTIPS[n]) for n in PERC2_CON_SPECS),
        default_params=lambda: dict(PERC2_DEFAULT_CONS),
        preset_params=lambda preset, block_key: get_load_model(PERC2_MODEL_ID).cons_for_preset(
            preset, "vfd" if block_key == "vfd" else "it"),
        mode_updates=_standard_mode_updates,
        notes=_perc2_notes,
        preview="perc2",
    ),
    PERC2_DLL_MODEL_ID: ModelUiSpec(
        model_id=PERC2_DLL_MODEL_ID,
        choice_label="PERC2 DLL v2.3 (PSS/E 34-36)",
        field_groups=PERC2_DLL_FIELD_GROUPS,
        field_kinds=PERC2_DLL_FIELD_KINDS,
        field_labels=PERC2_DLL_FIELD_LABELS,
        field_tooltips=PERC2_DLL_FIELD_TOOLTIPS,
        field_ranges=PERC2_DLL_FIELD_RANGES,
        field_decimals={},
        display_fields=tuple((n, PERC2_DLL_FIELD_LABELS[n], PERC2_DLL_FIELD_TOOLTIPS[n])
                             for n, _label, _tooltip in PERC2_DLL_DISPLAY_FIELDS),
        default_params=lambda: dict(get_load_model(PERC2_DLL_MODEL_ID).default_cons),
        preset_params=lambda preset, block_key: get_load_model(PERC2_DLL_MODEL_ID).cons_for_preset(
            preset, "vfd" if block_key == "vfd" else "it"),
        mode_updates=_dll_mode_updates,
        notes=_perc2_dll_notes,
        preview="dll",
    ),
}


def get_ui_spec(model_id: str) -> ModelUiSpec:
    try:
        return UI_SPECS[model_id]
    except KeyError:
        raise KeyError(f"no editor spec for load model {model_id!r}; have {sorted(UI_SPECS)}") from None
