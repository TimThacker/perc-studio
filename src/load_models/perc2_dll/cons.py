"""PERC2 DLL v2.3 (`PERC2_v34/v35/v36_v2p3.dll`): ICON/CON layout, defaults, display fields and checks.

Source: the vendor document "POWER ELECTRONIC LOAD MODEL (PERC2_V2P3.dll)" (ISO-NE, *Data Center Performance Model
(PERC1) - PSS/E v34/v35 documentation*) and its sample `.dyr` record. The record keeps the PERC1 DLL record's 173-CON layout (CON J..J+172) and appends
six CONs (J+173..J+178): a reactive-power lead-lag, and a reconnect band and two ramps for momentary cessation. The
two ICONs are kept in the CON dict as integers, in record order, like the PERC2 standard model's flags.

Every rule below was measured in PSS/E 35.6.4 (`PERC2_v35_v2p3.dll`) and 36.7.1 (`PERC2_v36_v2p3.dll`); the evidence
is in the PSS/E validation library, which is not published (summarized in docs/user/model_perc2_dll.md). Where the document and the DLL disagree,
this module follows the DLL and says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def flag_on(cons, name) -> bool:
    """PSS/E enables a check only for a flag of exactly 1 (sheet note 7, confirmed for 2 and -1)."""
    try:
        return round(float(cons[name])) == 1
    except (KeyError, TypeError, ValueError):
        return False


# ICON(M) = 0 for a 60 Hz system, 1 for 50 Hz; ICON(M+1) = 1 enables momentary cessation (Option 2).
ICON_NAMES = ("FREQ50", "MCFLAG")
V2P3_LAYOUT_EXTRA = [["TAQ", "TBQ"], ["RAMPAMC", "RAMPUAMC"], ["VLRCMC", "VURCMC"]]
EXTRA_CONS = tuple(n for row in V2P3_LAYOUT_EXTRA for n in row)

def _channel_block(suffix):
    # The lead-lag CONs are named bare "TA"/"TB" for the primary ("A") channel
    # but "TAB"/"TBB", "TAC"/"TBC", "TAD"/"TBD" for the unused B/C/D channels
    # - an irregularity in the vendor's own naming, not a typo to normalize.
    lead_lag = ["TA", "TB"] if suffix == "A" else [f"TA{suffix}", f"TB{suffix}"]
    return (
        [f"{n}{suffix}" for n in ("VDP", "DM", "TDR", "VRP", "RAMP", "DROOP", "KWASH", "TWASH")]
        + lead_lag
        + [f"{n}{suffix}" for n in ("FR", "NP", "VNOM", "IPMAX", "IPMIN", "IQMAX", "IQMIN", "TR", "NQ", "DB", "VDU", "TDU")]
    )


def _freq_block(suffix):
    return [f"{n}{suffix}" for n in (
        "FOFTP", "TOFTP", "FOFRN", "TOFRN", "ROFRN", "FUFTP", "TUFTP", "FUFRN", "TUFRN", "RUFRN",
    )]



# CON(J) .. CON(J+178) in record order, one list per "@!" row of the vendor sample: the 173 CONs of the
# `PERCBL` record layout (J..J+172), then the three v2.3 rows (J+173..J+178).
DYR_LAYOUT = [
    _channel_block("A"),
    _channel_block("B"),
    _channel_block("C"),
    _channel_block("D"),
    ["ZETAA", "WNAA", "ZETAB", "WNAB", "ZETAC", "WNAC", "ZETAD", "WNAD"],
    ["VDPA1", "DMA1", "VDPA2", "DMA2", "VDPA3", "DMA3"],
    ["VDUA1", "TDUA1", "VDUA2", "TDUA2", "VDUA3", "TDUA3"],
    ["VRUPA", "TRUPA", "RAMPUA"],
    ["VRUPB", "TRUPB", "RAMPUB"],
    ["VRUPC", "TRUPC", "RAMPUC"],
    ["VRUPD", "TRUPD", "RAMPUD"],
    _freq_block("1"),
    _freq_block("2"),
    _freq_block("3"),
    _freq_block("4"),
    ["VLBLK", "VUBLK", "TBLK", "TDELY"],
    ["FCEASE", "FRECON"],
    ["KWASHQ", "TWASHQ"],
    ["TVM", "CMTDELAY", "LFM", "CMTDELAYC", "TFRQ"],
    *V2P3_LAYOUT_EXTRA,
]
CON_ONLY_NAMES = tuple(name for row in DYR_LAYOUT for name in row)
assert len(CON_ONLY_NAMES) == 179 and len(set(CON_ONLY_NAMES)) == 179
CON_NAMES = ICON_NAMES + CON_ONLY_NAMES
ZIP_FIELDS = {"NPA", "NQA"}

# The vendor sample's values for the six new CONs.
SAMPLE_EXTRA = {"TAQ": 0.0, "TBQ": 0.0, "RAMPAMC": 1.0, "RAMPUAMC": 1.0, "VLRCMC": 0.9, "VURCMC": 1.09}

# LFM below this is replaced by 0.8 (the document, CON J+170).
LFM_FLOOR = 0.001
LFM_FALLBACK = 0.8


# The vendor-typical value of every CON of the 173-CON record except the ten core CONs `_vendor_defaults` adds.
# `IPMAXA` and `CMTDELAY` have no vendor-specified default; the values here are this app's neutral baseline.
FIXED_DEFAULTS = {
    # Active power loop support blocks (bypassed unless overridden).
    "DROOPA": 10.0,
    "KWASHA": 0.0,
    "TWASHA": 0.0,
    "TA": 0.0,
    "TB": 0.0,
    "FRA": 1.0,
    "VNOMA": 1.0,
    "IPMAXA": 1.0,
    "IPMINA": 0.0,
    "IQMAXA": 0.667,
    "IQMINA": -0.667,
    "DBA": 0.0,
    # High-voltage cease threshold/delay - channel A's own overvoltage
    # counterpart to VDPA/DMA, paired with the VRUPA/TRUPA/RAMPUA reconnect
    # block below (mirrors VRPA/TDRA/RAMPA on the undervoltage side). This is
    # a real CON pair in the DLL variant, confirmed against the vendor's own
    # documentation - not fabricated, and not the same thing as the newer
    # "Standard" variant's (absent) high-voltage logic - see module docstring.
    "VDUA": 1.1,
    "TDUA": 0.5,
    # Reactive power loop washout (bypassed).
    "KWASHQ": 0.0,
    "TWASHQ": 0.0,
    # Filters.
    "TVM": 0.02,
    "CMTDELAY": 0.0,
    "LFM": 0.8,
    "CMTDELAYC": 0.0,
    "TFRQ": 0.02,
    # Momentary cessation (Option 2) - not used since this app drives Option 1.
    "VLBLK": 0.5,
    "VUBLK": 1.1,
    "TBLK": 0.0167,
    "TDELY": 0.033,
    # Option 3 multi-step voltage trip/reconnect settings. RESOLVED 2026-09-24
    # (see docs/developer/PERC1_MODEL.md "Option 3 is always live"): direct
    # PSS/E v35.6.4
    # simulation against the real compiled PERC2_V35.dll confirmed the DLL
    # always evaluates this 4-stage table, for every facility, regardless of
    # whether it's meant to use "Option 1 only" - there is no flag that
    # disables stages 2-4 the way ICON(M+1) disables Option 2. Because of
    # this, every CON-dict-building step in this app (DEFAULT_CONS
    # below, presets/ridethrough.py's preset bundles) calls
    # `voltage_stage_cons()` to REPLACE the vendor-sample values below with
    # either the preset's own real multi-tier envelope or (for the
    # single-point defaults) that same single point repeated
    # into every stage - a repeated stage fires at the exact same time as the
    # tier it copies, so it cannot introduce a different, earlier trip
    # condition (validated directly in PSS/E, in the PSS/E validation library,
    # which is not published). The values below
    # remain the raw vendor-sample defaults (confirmed identical across two
    # independent vendor examples) - they are the correct *fallback* for any
    # future caller that forgets to call voltage_stage_cons(), but should
    # never be the values actually exported for a real facility.
    "VDPA1": 0.80, "DMA1": 0.50,
    "VDPA2": 0.5, "DMA2": 0.15,
    "VDPA3": 0.5, "DMA3": 0.15,
    "VDUA1": 1.2, "TDUA1": 0.0,
    "VDUA2": 1.2, "TDUA2": 0.0,
    "VDUA3": 1.2, "TDUA3": 0.0,
    "VRUPA": 1.05, "TRUPA": 5.0, "RAMPUA": 5.0,
    # Frequency trip/reconnect settings (standard 58-62 Hz band, block 1 only).
    "FOFTP1": 62.0, "TOFTP1": 100.01,
    "FOFRN1": 61.5, "TOFRN1": 100.0, "ROFRN1": 5.0,
    "FUFTP1": 58.0, "TUFTP1": 100.0,
    "FUFRN1": 58.5, "TUFRN1": 100.0, "RUFRN1": 5.0,
}
for _n in (2, 3, 4):
    FIXED_DEFAULTS.update({
        f"FOFTP{_n}": 99.0, f"TOFTP{_n}": 999.0,
        f"FOFRN{_n}": 99.0, f"TOFRN{_n}": 999.0, f"ROFRN{_n}": 999.0,
        f"FUFTP{_n}": 99.0, f"TUFTP{_n}": 999.0,
        f"FUFRN{_n}": 99.0, f"TUFRN{_n}": 999.0, f"RUFRN{_n}": 999.0,
    })
for _suffix in ("B", "C", "D"):
    for _name in ("VDP", "DM", "TDR", "VRP", "RAMP", "DROOP", "KWASH", "TWASH", "TA", "TB",
                  "FR", "NP", "VNOM", "IPMAX", "IPMIN", "IQMAX", "IQMIN", "TR", "NQ", "DB", "VDU", "TDU"):
        FIXED_DEFAULTS[f"{_name}{_suffix}"] = 0.0
    for _name in ("VRUP", "TRUP", "RAMPU"):
        FIXED_DEFAULTS[f"{_name}{_suffix}"] = 0.0
for _name in ("ZETAA", "WNAA", "ZETAB", "WNAB", "ZETAC", "WNAC", "ZETAD", "WNAD"):
    FIXED_DEFAULTS[_name] = 0.0
del _n, _suffix, _name


def _vendor_defaults() -> dict:
    """The 173-CON record's default set: a double-conversion (constant power) block with a generic Standard-tier
    undervoltage trip (0.70 pu, 0.02 s), the full block tripping and a staged reconnect. The compiled DLL evaluates
    all four voltage stages unconditionally, so the stage-1 point is repeated into stages 2-4 (a repeated stage
    fires at the same time as the one it copies)."""
    d = {
        **FIXED_DEFAULTS,
        "NPA": 0,
        "NQA": 0,
        "TRA": 0.02,
        "VDPA": 0.70,
        "DMA": 0.02,
        "FCEASE": 1.0,
        "VRPA": 0.9,
        "TDRA": 60.0,
        "RAMPA": 30.0,
        "FRECON": 1.0,
    }
    for suffix in ("1", "2", "3"):
        d[f"VDPA{suffix}"], d[f"DMA{suffix}"] = d["VDPA"], d["DMA"]
        d[f"VDUA{suffix}"], d[f"TDUA{suffix}"] = d["VDUA"], d["TDUA"]
    return d


def effective_lfm(cons) -> float:
    lfm = float(cons["LFM"])
    return lfm if lfm >= LFM_FLOOR else LFM_FALLBACK


def _build_defaults() -> dict:
    """The 173-CON record's defaults (so a new block behaves like a new PERC1 DLL block), the six new CONs from the vendor
    sample, momentary cessation off, 60 Hz. The DLL multiplies RAMPA and RAMPUA by LFM (validation finding 4); the
    PERC1 DLL does not, so those two are divided by LFM here to keep the same ramp in seconds."""
    p1 = _vendor_defaults()
    out = {"FREQ50": 0, "MCFLAG": 0}
    out.update({n: p1[n] for n in CON_ONLY_NAMES[:-len(EXTRA_CONS)]})
    out.update(SAMPLE_EXTRA)
    lfm = effective_lfm(out)
    for n in RAMP_CONS:
        out[n] = round(float(out[n]) / lfm, 6)
    return out


# The reconnect ramps the DLL multiplies by LFM (measured: validation finding 4). The frequency ramps (RUFRN1,
# ROFRN1) and the momentary-cessation ramps (RAMPAMC, RAMPUAMC) are used as given.
RAMP_CONS = ("RAMPA", "RAMPUA")
MC_RAMP_CONS = ("RAMPAMC", "RAMPUAMC")


@dataclass(frozen=True)
class ConIssue:
    level: str  # "error" (PSS/E rejects it or the result is nonsense) | "warning" (silently changed, or a hazard)
    con: str
    message: str


DEFAULT_TIME_STEP_S = 1.0 / 240.0


def ramp_seconds(cons, name) -> float:
    """How long a reconnect ramp lasts in PSS/E: RAMPA and RAMPUA times LFM, every other ramp as given (validation
    finding 4)."""
    v = max(float(cons[name]), 0.0)
    return v * effective_lfm(cons) if name in RAMP_CONS else v


DEFAULT_CONS = _build_defaults()
assert tuple(DEFAULT_CONS) == CON_NAMES

# The 173-CON record's display rows, plus the momentary-cessation and v2.3 rows.
DISPLAY_FIELDS = (
    ("MCFLAG", "Momentary cessation on (ICON(M+1))", "MCFLAG / ICON(M+1)"),
    ("VDPA", "Undervoltage stage 1 trip (pu)", "Vcease / VDPA"),
    ("DMA", "Undervoltage stage 1 delay (s)", "Tcease / DMA"),
    ("FCEASE", "Fraction that trips", "Fcease / FCEASE"),
    ("VRPA", "Undervoltage reconnect voltage (pu)", "Vrecon / VRPA"),
    ("TDRA", "Undervoltage reconnect delay (s)", "Trecon / TDRA"),
    ("RAMPA", "Undervoltage reconnect ramp (s)", "Tramp / RAMPA"),
    ("FRECON", "Fraction that reconnects", "Frecon / FRECON"),
    ("NPA", "Active ZIP exponent (0=P, 1=I, 2=Z)", "NPA"),
    ("NQA", "Reactive ZIP exponent (0=P, 1=I, 2=Z)", "NQA"),
    ("TRA", "Numerical filter (s)", "Tt / TRA"),
    ("VDUA", "Overvoltage stage 1 trip (pu)", "VDUA"),
    ("TDUA", "Overvoltage stage 1 delay (s)", "TDUA"),
    ("DROOPA", "Frequency droop", "DROOPA"),
    ("IPMAXA", "Active current limit (pu)", "IPMAXA"),
    ("IPMINA", "Active current floor (pu)", "IPMINA"),
    ("IQMAXA", "Reactive current limit (pu)", "IQMAXA"),
    ("IQMINA", "Reactive current floor (pu)", "IQMINA"),
    # Option-3 multi-stage ride-through curve (stages 2-4; stage 1 is
    # VDPA/DMA and VDUA/TDUA above). Exposed for direct editing since
    # PSS/E confirmed the compiled DLL always
    # evaluates all 4 stages - see voltage_stage_cons()'s docstring and
    # docs/developer/PERC1_MODEL.md's "Option 3 is always live" section. Every preset
    # in presets/ridethrough.py now populates these from its own real
    # multi-tier envelope rather than leaving them at the vendor-sample
    # defaults.
    *[
        row
        for n in (2, 3, 4)
        for row in (
            (f"VDPA{n - 1}", f"Undervoltage stage {n} trip (pu)", f"VDPA{n - 1}"),
            (f"DMA{n - 1}", f"Undervoltage stage {n} delay (s)", f"DMA{n - 1}"),
        )
    ],
    *[
        row
        for n in (2, 3, 4)
        for row in (
            (f"VDUA{n - 1}", f"Overvoltage stage {n} trip (pu)", f"VDUA{n - 1}"),
            (f"TDUA{n - 1}", f"Overvoltage stage {n} delay (s)", f"TDUA{n - 1}"),
        )
    ],
    # Overvoltage trips reconnect through their own high-side CONs, not
    # VRPA/TDRA/RAMPA (vendor documentation; see docs/developer/PERC1_MODEL.md's
    # "Which reconnect settings apply to which trip").
    ("VRUPA", "Overvoltage reconnect voltage (pu)", "VRUPA"),
    ("TRUPA", "Overvoltage reconnect delay (s)", "TRUPA"),
    ("RAMPUA", "Overvoltage reconnect ramp (s)", "RAMPUA"),
    # Frequency trip/reconnect: the vendor data sheet uses only CONs J+120 to
    # J+129 (the "1"-suffixed set) and marks every stage-2-4 frequency CON
    # (J+130 to J+159) "NOT USED" - one frequency stage per direction, unlike
    # voltage's four.
    ("FUFTP1", "Frequency deadband low (Hz)", "FUFTP1"),
    ("TUFTP1", "Trip delay below deadband (s)", "TUFTP1"),
    ("FUFRN1", "Under-frequency reconnect frequency (Hz)", "FUFRN1"),
    ("TUFRN1", "Under-frequency reconnect delay (s)", "TUFRN1"),
    ("RUFRN1", "Under-frequency reconnect ramp (s)", "RUFRN1"),
    ("FOFTP1", "Frequency deadband high (Hz)", "FOFTP1"),
    ("TOFTP1", "Trip delay above deadband (s)", "TOFTP1"),
    ("FOFRN1", "Over-frequency reconnect frequency (Hz)", "FOFRN1"),
    ("TOFRN1", "Over-frequency reconnect delay (s)", "TOFRN1"),
    ("ROFRN1", "Over-frequency reconnect ramp (s)", "ROFRN1"),
    ("VLBLK", "Momentary cessation below (pu)", "VLBLK"),
    ("VUBLK", "Momentary cessation above (pu)", "VUBLK"),
    ("TBLK", "Momentary cessation reconnect delay (s)", "TBLK"),
    ("TDELY", "Momentary cessation extra delay (s)", "TDELY"),
    ("VLRCMC", "Momentary cessation reconnect, low edge (pu)", "VLRCMC"),
    ("VURCMC", "Momentary cessation reconnect, high edge (pu)", "VURCMC"),
    ("RAMPAMC", "Momentary cessation ramp after a low-voltage cessation (s)", "RAMPAMC"),
    ("RAMPUAMC", "Momentary cessation ramp after a high-voltage cessation (s)", "RAMPUAMC"),
    ("TAQ", "Reactive lead-lag lead time constant (s)", "TAQ"),
    ("TBQ", "Reactive lead-lag lag time constant (s)", "TBQ"),
    ("LFM", "Load factor (MVA base = MW / LFM)", "LFM"),
    ("FREQ50", "50 Hz system (ICON(M))", "FREQ50 / ICON(M)"),
)


def validate_cons(cons, time_step_s: float = DEFAULT_TIME_STEP_S, initial_voltage_pu: float = 1.0,
                  psse_version: str | None = None) -> list[ConIssue]:
    """Everything the DLL would reject, silently change, or turn into a hazard. An empty list means the values mean in
    PSS/E exactly what they say. `psse_version` ("35.6"/"36.7") adds the version-specific DLL defects."""
    missing = [n for n in CON_NAMES if n not in cons]
    if missing:
        return [ConIssue("error", missing[0], f"missing value(s): {', '.join(missing[:5])}"
                                              + (" ..." if len(missing) > 5 else ""))]
    issues: list[ConIssue] = []
    c = {}
    for n in CON_NAMES:
        try:
            c[n] = float(cons[n])
        except (TypeError, ValueError):
            issues.append(ConIssue("error", n, "must be a number"))
            continue
        if not math.isfinite(c[n]):
            issues.append(ConIssue("error", n, "must be a finite number"))
    if issues:
        return issues

    def err(con, msg):
        issues.append(ConIssue("error", con, msg))

    def warn(con, msg):
        issues.append(ConIssue("warning", con, msg))

    v0 = initial_voltage_pu
    for n in ICON_NAMES:
        if c[n] not in (0.0, 1.0):
            warn(n, f"{c[n]:g} is not 0 or 1")
    if c["FREQ50"] != 0.0:
        warn("FREQ50", "the DLL ignores ICON(M): both builds measure frequency as 60 Hz x (1 + deviation), so in a "
                       "50 Hz case every frequency setting is compared with 60 Hz (measured in PSS/E)")
    lfm = effective_lfm(c)
    if c["LFM"] < LFM_FLOOR:
        warn("LFM", f"below {LFM_FLOOR:g}; the DLL uses {LFM_FALLBACK:g}")
    elif c["LFM"] > 1:
        warn("LFM", "above 1: the MVA base is smaller than the load's MW")
    if c["IPMAXA"] < lfm * v0 - 1e-9:
        warn("IPMAXA", f"IPMAXA {c['IPMAXA']:g} is below LFM {lfm:g}: the block cannot draw its power-flow load and "
                       f"settles at {c['IPMAXA'] / lfm * 100:.0f}% of it at t = 0 (PSS/E gives no message)")
    if c["IPMAXA"] < c["IPMINA"]:
        err("IPMAXA", "IPMAXA < IPMINA")
    if c["IQMAXA"] < c["IQMINA"]:
        err("IQMAXA", "IQMAXA < IQMINA")
    if c["FRA"] != 1.0:
        warn("FRA", "the document says FRA must be 1.0")
    if c["VNOMA"] != 1.0:
        warn("VNOMA", "the document says VNOMA must be 1.0")
    if c["FCEASE"] > 1.0:
        err("FCEASE", "above 1: the DLL does not clamp it; FracOn goes negative on a trip and the load exports power")
    elif c["FCEASE"] < 0.0:
        err("FCEASE", "negative: the DLL does not clamp it; a trip raises the load above its initial power")
    if c["FRECON"] > 1.0:
        warn("FRECON", "above 1: the load reconnects above its initial power (the DLL does not clamp it)")
    elif c["FRECON"] < 0.0:
        err("FRECON", "negative: the 'reconnect' ramps the load further down (the DLL does not clamp it)")
    if c["IPMAXA"] <= 0.0:
        err("IPMAXA", "0 or negative: the load draws nothing from t = 0")
    # lead-lags: (1 + sTA)/(1 + sTB) and (1 + sTAQ)/(1 + sTBQ)
    if c["TA"] != 0.0 and c["TB"] == 0.0:
        err("TA", "TA without TB: PSS/E returns NaN from the first time step (both builds); set both to 0 to bypass")
    if c["TAQ"] != 0.0 and c["TBQ"] == 0.0:
        err("TAQ", "TAQ without TBQ: PSS/E returns NaN from the first time step (both builds)")
    if psse_version == "36.7" and (c["TA"] != 0.0 or c["TB"] != 0.0):
        err("TB", "PERC2_v36_v2p3.dll returns NaN from the first time step whenever TA or TB is not 0 (the v35 build "
                  "does not); set both to 0 on PSS/E 36")
    elif c["TA"] != 0.0 or c["TB"] != 0.0:
        warn("TB", "the P lead-lag works on PERC2_v35_v2p3.dll but makes PSS/E 36.7 (v36 build) return NaN")
    if c["TRA"] < 2 * time_step_s:
        warn("TRA", f"below 2 x time step ({2 * time_step_s:.5f} s); a numerical filter this short can oscillate")

    fcease = c["FCEASE"]
    uv = [(f"VDPA{s}", f"DMA{s}") for s in ("", "1", "2", "3")]
    ov = [(f"VDUA{s}", f"TDUA{s}") for s in ("", "1", "2", "3")]
    uv_live = [(v, d) for v, d in uv if 0.0 < c[v] < v0]
    ov_live = [(v, d) for v, d in ov if c[v] > v0]
    if fcease > 0:
        for v, _d in uv:
            if c[v] >= v0:
                err(v, f"at or above the initial voltage ({v0:g} pu): the block trips with no disturbance")
        for v, _d in ov:
            if 0 < c[v] <= v0:
                err(v, f"at or below the initial voltage ({v0:g} pu): the block trips with no disturbance")
        # the reconnect window VRPA < V < VRUPA (strict, on the filtered voltage)
        if c["VRPA"] >= v0:
            err("VRPA", "at or above the initial voltage: a tripped block never reconnects")
        if c["VRUPA"] <= v0:
            err("VRUPA", "at or below the initial voltage: a tripped block never reconnects")
        high_uv = max((c[v] for v, _d in uv_live), default=None)
        if high_uv is not None and c["VRPA"] < high_uv:
            warn("VRPA", f"below an undervoltage stage ({high_uv:g} pu): a sag between them trips, reconnects inside "
                         "the sag and trips again (cycling)")
        low_ov = min((c[v] for v, _d in ov_live), default=None)
        if low_ov is not None and c["VRUPA"] > low_ov:
            warn("VRUPA", f"above an overvoltage stage ({low_ov:g} pu): a swell between them trips, reconnects inside "
                          "the swell and trips again (cycling)")
        nominal_hz = 50.0 if c["FREQ50"] == 1 else 60.0
        if c["FUFTP1"] >= nominal_hz:
            err("FUFTP1", "at or above nominal frequency: the block trips with no disturbance")
        if c["FOFTP1"] <= nominal_hz:
            err("FOFTP1", "at or below nominal frequency: the block trips with no disturbance")

    if flag_on(c, "MCFLAG") and fcease > 0:
        if c["VLBLK"] >= v0:
            err("VLBLK", "at or above the initial voltage: momentary cessation at t = 0")
        if c["VUBLK"] <= v0:
            err("VUBLK", "at or below the initial voltage: momentary cessation at t = 0")
        if c["VLRCMC"] >= v0:
            err("VLRCMC", "at or above the initial voltage: after a cessation the block never comes back")
        if c["VURCMC"] <= v0:
            err("VURCMC", "at or below the initial voltage: after a cessation the block never comes back")
        if c["VLRCMC"] >= c["VURCMC"]:
            err("VLRCMC", "VLRCMC >= VURCMC: the momentary-cessation reconnect band is empty")
        if c["VUBLK"] < 9:
            (err if psse_version == "36.7" else warn)(
                "VUBLK", "PERC2_v36_v2p3.dll stops PSS/E 36.7 (Fortran runtime error, exit code 66) when the ramp "
                         "after a high-voltage momentary cessation ends; the v35 build does not")
        if c["FRECON"] < 1.0:
            warn("FRECON", f"momentary cessation also uses FCEASE/FRECON: every cessation loses "
                           f"{fcease * (1 - c['FRECON']) * 100:.0f}% of the load for good")
        mc_stages = [v for v, _d in uv if 0.0 < c[v] <= c["VLBLK"]]
        if mc_stages:
            warn("VLBLK", f"an undervoltage stage at or below VLBLK ({', '.join(mc_stages)}): a sag that outlasts it "
                          "turns the cessation into a trip, which reconnects on TDRA/RAMPA instead of TBLK/RAMPAMC")
    for n in ("RAMPA", "RAMPUA", "RUFRN1", "ROFRN1", "RAMPAMC", "RAMPUAMC"):
        if c[n] < 0:
            err(n, "negative: the reconnect ramp runs the load below zero and never ends (the DLL does not clamp it)")
    for n in ("TDRA", "TRUPA", "TBLK", "TDELY", "CMTDELAY", "CMTDELAYC"):
        if c[n] < 0:
            warn(n, "negative; the DLL treats it as 0")
    return issues


__all__ = [
    "CON_NAMES",
    "CON_ONLY_NAMES",
    "DEFAULT_CONS",
    "DEFAULT_TIME_STEP_S",
    "DISPLAY_FIELDS",
    "DYR_LAYOUT",
    "EXTRA_CONS",
    "FIXED_DEFAULTS",
    "ICON_NAMES",
    "LFM_FALLBACK",
    "LFM_FLOOR",
    "MC_RAMP_CONS",
    "RAMP_CONS",
    "SAMPLE_EXTRA",
    "V2P3_LAYOUT_EXTRA",
    "ZIP_FIELDS",
    "ConIssue",
    "effective_lfm",
    "flag_on",
    "ramp_seconds",
    "validate_cons",
]
