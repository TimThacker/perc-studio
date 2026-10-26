"""PERC2 DLL v2.3 (`PERC2_v34/v35/v36_v2p3.dll`): ICON/CON layout, defaults, display fields and checks.

Source: the vendor document "POWER ELECTRONIC LOAD MODEL (PERC2_V2P3.dll)" (ISO-NE, *Data Center Performance Model
(PERC1) - PSS/E v34/v35 documentation*) and its sample `.dyr` record. The record is the PERC1 DLL's (`perc1_dll`, CON J..J+172 unchanged) with six CONs
appended (J+173..J+178): a reactive-power lead-lag, and a reconnect band and two ramps for momentary cessation. The
two ICONs are kept in the CON dict as integers, in record order, like the PERC2 standard model's flags.

Every rule below was measured in PSS/E 35.6.4 (`PERC2_v35_v2p3.dll`) and 36.7.1 (`PERC2_v36_v2p3.dll`); the evidence
is in the PSS/E validation library, which is not published (summarized in docs/user/model_perc2_dll.md). Where the document and the DLL disagree,
this module follows the DLL and says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..common import flag_on
from ..perc1_dll.cons import (
    PERC1_CON_ORDER,
    PERC1_DEFAULT_CONS,
    PERC1_DISPLAY_FIELDS,
    PERC1_DYR_LAYOUT,
)

# ICON(M) = 0 for a 60 Hz system, 1 for 50 Hz; ICON(M+1) = 1 enables momentary cessation (Option 2).
ICON_NAMES = ("FREQ50", "MCFLAG")
V2P3_LAYOUT_EXTRA = [["TAQ", "TBQ"], ["RAMPAMC", "RAMPUAMC"], ["VLRCMC", "VURCMC"]]
EXTRA_CONS = tuple(n for row in V2P3_LAYOUT_EXTRA for n in row)
DYR_LAYOUT = [*PERC1_DYR_LAYOUT, *V2P3_LAYOUT_EXTRA]
CON_ONLY_NAMES = tuple(PERC1_CON_ORDER) + EXTRA_CONS
assert len(CON_ONLY_NAMES) == 179 and len(set(CON_ONLY_NAMES)) == 179
CON_NAMES = ICON_NAMES + CON_ONLY_NAMES
ZIP_FIELDS = {"NPA", "NQA"}

# The vendor sample's values for the six new CONs.
SAMPLE_EXTRA = {"TAQ": 0.0, "TBQ": 0.0, "RAMPAMC": 1.0, "RAMPUAMC": 1.0, "VLRCMC": 0.9, "VURCMC": 1.09}

# LFM below this is replaced by 0.8 (the document, CON J+170).
LFM_FLOOR = 0.001
LFM_FALLBACK = 0.8


def _perc1_defaults() -> dict:
    return dict(PERC1_DEFAULT_CONS)


def effective_lfm(cons) -> float:
    lfm = float(cons["LFM"])
    return lfm if lfm >= LFM_FLOOR else LFM_FALLBACK


def _build_defaults() -> dict:
    """The PERC1 DLL's defaults (so a new block behaves like a new PERC1 DLL block), the six new CONs from the vendor
    sample, momentary cessation off, 60 Hz. The DLL multiplies RAMPA and RAMPUA by LFM (validation finding 4); the
    PERC1 DLL does not, so those two are divided by LFM here to keep the same ramp in seconds."""
    p1 = _perc1_defaults()
    out = {"FREQ50": 0, "MCFLAG": 0}
    out.update({n: p1[n] for n in PERC1_CON_ORDER})
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

# The PERC1 DLL's display rows, plus the momentary-cessation and v2.3 rows.
DISPLAY_FIELDS = (
    ("MCFLAG", "Momentary cessation on (ICON(M+1))", "MCFLAG / ICON(M+1)"),
    *PERC1_DISPLAY_FIELDS,
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
