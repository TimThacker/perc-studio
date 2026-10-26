"""PERC2 *standard* variant (PSS/E 36.7 PERCxx2U): ICON/CON layout, defaults, limits.

Source: Siemens, "PERCBL2U, PERCOW2U, PERCZN2U, PERCAR2U, PERCAL2U - Power
Electronic Load Component Model with Reconnect and Cease Logic and with Voltage
and Frequency Based Tripping" (PSS/E 36.7.0 data sheet, 13 pp.). Names are the
sheet's own; the record holds ICON M..M+5 (six flags), then CON J..J+56. This is
a different model from PERC1 (`perc1_dll`, `perc1_standard`): different CONs,
different order, more cease checks.

Every limit and default below was checked against PSS/E 36.7.1 itself; the
evidence is in the PSS/E validation library, which is not published (summarized in
docs/user/model_perc2_standard.md). Where the data sheet and PSS/E disagree, this module follows PSS/E and
says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..common import flag_on

ICON_NAMES = ("VLMflag", "VHMflag", "VLLflag", "VLHflag", "FLflag", "FHflag")

CON_ONLY_NAMES = (
    "Ldfact", "QPratio", "Tt", "Tv", "Tf", "dbfl", "dbfh", "Kdroop",
    "Kvp", "Tvp", "Kvq", "Tvq", "Tap", "Tbp", "Taq", "Tbq",
    "nP", "nQ", "Ipmax", "Ipmin", "Iqmax", "Iqmin", "Imax",
    "fcease", "VLcease", "VHcease", "Tcease", "Tdelay", "frecon", "VLrecon", "VHrecon", "Tramp", "Trecon",
    "TLrampL", "TLreconL", "VLC1", "TVLC1", "VLC2", "TVLC2", "VLC3", "TVLC3", "VLC4", "TVLC4",
    "TLrampH", "TLreconH", "VHC1", "TVHC1", "VHC2", "TVHC2", "VHC3", "TVHC3", "VHC4", "TVHC4",
    "FLC1", "TFLC1", "FHC1", "TFHC1",
)
assert len(CON_ONLY_NAMES) == 57 and len(set(CON_ONLY_NAMES)) == 57

# Every value of the record in .dyr order: the six flags (ICONs) come first. The app stores them in the same CON
# dict, as 0/1 integers.
CON_NAMES = ICON_NAMES + CON_ONLY_NAMES

# Point 3 of each long table is evaluated with point 1's TIME: Vtf < VLC3 for TVLC1 (and Vtf > VHC3 for TVHC1); TVLC3
# and TVHC3 are never used (PSS/E 36.7.1, validation finding 6). The app's presets use points 1, 2 and 4 only and
# switch point 3 off.
WORKING_LONG_POINTS = (1, 2, 4)
BROKEN_LONG_POINT = 3


def long_time_point(i: int) -> int:
    """The point whose time PSS/E 36.7.1 uses for long point `i`."""
    return 1 if i == BROKEN_LONG_POINT else i

# The app's starting point. The data sheet has no example values; these reproduce the PERC1 standard model's own
# defaults through the sheet's note-7 recipe (VLMflag only, VLcease = Vcease, Tramp = PERC1 Tramp / Ldfact), so a new
# PERC2 block behaves like a new PERC1-standard block. The other checks are filled with a generic ride-through table
# but switched off; presets switch on what they need.
DEFAULT_CONS = {
    "VLMflag": 1, "VHMflag": 0, "VLLflag": 0, "VLHflag": 0, "FLflag": 0, "FHflag": 0,
    "Ldfact": 0.8, "QPratio": 0.0, "Tt": 0.02, "Tv": 0.05, "Tf": 0.02, "dbfl": 0.0, "dbfh": 0.0, "Kdroop": 8.0,
    "Kvp": 0.0, "Tvp": 0.05, "Kvq": 0.0, "Tvq": 0.1, "Tap": 1.0, "Tbp": 1.0, "Taq": 1.0, "Tbq": 1.0,
    "nP": 0.0, "nQ": 0.0, "Ipmax": 1.0, "Ipmin": 0.0, "Iqmax": 0.7, "Iqmin": -0.7, "Imax": 1.5,
    "fcease": 0.9, "VLcease": 0.5, "VHcease": 1.2, "Tcease": 0.05, "Tdelay": 0.0, "frecon": 0.5,
    "VLrecon": 0.6, "VHrecon": 1.1, "Tramp": 1.25, "Trecon": 0.05,
    "TLrampL": 1.25, "TLreconL": 0.05,
    "VLC1": 0.9, "TVLC1": 2.0, "VLC2": 0.8, "TVLC2": 0.5, "VLC3": 0.0, "TVLC3": 0.0, "VLC4": 0.5, "TVLC4": 0.15,
    "TLrampH": 1.25, "TLreconH": 0.05,
    "VHC1": 1.1, "TVHC1": 1.0, "VHC2": 1.15, "TVHC2": 0.5, "VHC3": 99.0, "TVHC3": 0.0, "VHC4": 1.2, "TVHC4": 0.16,
    "FLC1": 58.0, "TFLC1": 100.0, "FHC1": 62.0, "TFHC1": 100.0,
}
assert tuple(DEFAULT_CONS) == CON_NAMES

TDELAY_NOTE = ("Tdelay adds to every cease path (momentary, long and frequency) in PSS/E 36.7.1; unlike PERC1 standard, "
               "a dip that ends while it runs does not return NaN (measured in PSS/E).")


@dataclass(frozen=True)
class ConSpec:
    """One CON or flag: what it is, its unit, and the range PSS/E 36.7.1 accepts. `lo`/`hi` are the stated limits
    (None = unbounded); `typical` is the span a UI should suggest."""

    name: str
    label: str
    unit: str
    group: str
    lo: float | None
    hi: float | None
    typical: tuple[float, float]
    note: str = ""


_G = {"flags": "Cease checks", "base": "Load basis", "droop": "Frequency droop", "p": "Active-power path",
      "q": "Reactive-power path", "lim": "Current limits", "mom": "Momentary cease and reconnect",
      "ll": "Long low-voltage cease", "lh": "Long high-voltage cease", "f": "Frequency cease",
      "filt": "Measurement and converter"}

_SPECS: dict[str, ConSpec] = {s.name: s for s in (
    ConSpec("VLMflag", "Momentary low-voltage cease", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks Vtf < VLcease for Tcease; any other value (0, 2, -1) is off."),
    ConSpec("VHMflag", "Momentary high-voltage cease", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks Vtf > VHcease for Tcease. Off still leaves VHcease capping VHrecon."),
    ConSpec("VLLflag", "Long low-voltage cease (4-point table)", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks Vtf < VLCx for TVLCx. PSS/E 36.7.1 times point 3 with TVLC1, not TVLC3."),
    ConSpec("VLHflag", "Long high-voltage cease (4-point table)", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks Vtf > VHCx for TVHCx. PSS/E 36.7.1 times point 3 with TVHC1, not TVHC3."),
    ConSpec("FLflag", "Low-frequency cease (no reconnect)", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks f < FLC1 for TFLC1. The load then does not come back."),
    ConSpec("FHflag", "High-frequency cease (no reconnect)", "flag", _G["flags"], 0, 1, (0, 1),
            "1 checks f > FHC1 for TFHC1. The load then does not come back."),
    ConSpec("Ldfact", "Load factor (sets the MVA base)", "pu", _G["base"], 0.0, 1.0, (0.5, 1.0),
            "MVA base = initial P / Ldfact; every pu CON is on that base. <= 0 -> PSS/E uses 0.8 (with a message). "
            "The data sheet says > 1 also falls back to 0.8; PSS/E 36.7.1 uses it as given, and the block then cannot "
            "draw its own power-flow load if Ldfact > Ipmax."),
    ConSpec("QPratio", "Q/P ratio (initial reactive power)", "pu", _G["base"], None, None, (-0.3, 0.5),
            "Qinit = QPratio x Pinit. The difference to the load's power-flow Q is absorbed as ExtraVars."),
    ConSpec("Tt", "Converter delay", "s", _G["filt"], 0.0, None, (0.01, 0.05),
            "PSS/E raises anything below 2 x time step to 2 x time step. The data sheet says it writes a message; "
            "36.7.1 does not."),
    ConSpec("Tv", "Voltage measurement time constant", "s", _G["filt"], 0.0, None, (0.0, 0.1),
            "Filters the voltage every voltage check sees. 0 or negative = no filter."),
    ConSpec("Tf", "Frequency measurement time constant", "s", _G["filt"], 0.0, None, (0.0, 0.5),
            "Filters the frequency for droop and the frequency cease. Its input is held at 0 deviation while the bus "
            "voltage is below 0.7 pu."),
    ConSpec("dbfl", "Droop deadband, lower edge", "pu freq", _G["droop"], None, 0.0, (-0.01, 0.0),
            "A frequency deviation (0.005 pu = 0.3 Hz), <= 0."),
    ConSpec("dbfh", "Droop deadband, upper edge", "pu freq", _G["droop"], 0.0, None, (0.0, 0.01), ">= 0."),
    ConSpec("Kdroop", "Droop gain", "pu P / pu f", _G["droop"], None, None, (0.0, 20.0),
            "dP = Kdroop x (df - deadband) in pu of the MVA base; P falls when f falls. 0 disables."),
    ConSpec("Kvp", "P-path washout gain", "pu*s", _G["p"], None, None, (0.0, 1.0),
            "Washout sK/(1+sT) on the bus voltage, added to Pinit. 0 disables."),
    ConSpec("Tvp", "P-path washout time constant", "s", _G["p"], 0.0, None, (0.02, 1.0), "Keep > 0 when Kvp != 0."),
    ConSpec("Kvq", "Q-path washout gain", "pu*s", _G["q"], None, None, (0.0, 1.0), "0 disables."),
    ConSpec("Tvq", "Q-path washout time constant", "s", _G["q"], 0.0, None, (0.02, 1.0), "Keep > 0 when Kvq != 0."),
    ConSpec("Tap", "P-path lead time constant", "s", _G["p"], 0.0, None, (0.0, 2.0),
            "Lead-lag (1+sTap)/(1+sTbp) on Pinit + droop + washout."),
    ConSpec("Tbp", "P-path lag time constant", "s", _G["p"], 0.0, None, (0.0, 2.0),
            "0 bypasses the whole P lead-lag (Tap is then ignored), as in PERC1 standard."),
    ConSpec("Taq", "Q-path lead time constant", "s", _G["q"], 0.0, None, (0.0, 2.0),
            "Lead-lag (1+sTaq)/(1+sTbq) on Qinit + washout."),
    ConSpec("Tbq", "Q-path lag time constant", "s", _G["q"], 0.0, None, (0.0, 2.0),
            "0 bypasses the whole Q lead-lag."),
    ConSpec("nP", "P voltage exponent", "", _G["p"], None, None, (0.0, 2.0),
            "P = P0 (Vtf/Vinit)^nP in steady state: 0 constant power, 1 current, 2 impedance."),
    ConSpec("nQ", "Q voltage exponent", "", _G["q"], None, None, (0.0, 2.0), "Same for Q."),
    ConSpec("Ipmax", "Maximum active current", "pu", _G["lim"], 0.0, None, (0.5, 1.5),
            "IpmaxUsed = min(Ipmax, Imax) (the block diagram; the sheet's note 16 says max, PSS/E uses min). Below "
            "Ldfact the block cannot draw its power-flow load at 1.0 pu."),
    ConSpec("Ipmin", "Minimum active current", "pu", _G["lim"], 0.0, None, (0.0, 0.0),
            "IpminUsed = max(Ipmin, -Imax). Keep >= 0 or the load backfeeds."),
    ConSpec("Iqmax", "Maximum reactive current", "pu", _G["lim"], 0.0, None, (0.3, 1.0),
            "IqmaxUsed = min(Iqmax, sqrt(Imax^2 - Ip^2)): active current has priority."),
    ConSpec("Iqmin", "Minimum reactive current", "pu", _G["lim"], None, 0.0, (-1.0, 0.0),
            "IqminUsed = max(Iqmin, -sqrt(Imax^2 - Ip^2))."),
    ConSpec("Imax", "Maximum total current", "pu", _G["lim"], 0.0, None, (1.0, 2.0),
            "Must be > 0: 0 zeroes the load; a negative value is used as its magnitude."),
    ConSpec("fcease", "Fraction that ceases", "", _G["mom"], 0.0, 1.0, (0.0, 1.0),
            "Outside [0,1] PSS/E clamps it (with a message). 0 turns every cease off."),
    ConSpec("VLcease", "Momentary cease, low voltage", "pu", _G["mom"], 0.0, None, (0.1, 0.9),
            "Strictly Vtf < VLcease for Tcease ceases (VLMflag). Above the initial voltage the load ceases at t = 0."),
    ConSpec("VHcease", "Momentary cease, high voltage", "pu", _G["mom"], 1.0, None, (1.05, 1.5),
            "Strictly Vtf > VHcease for Tcease ceases (VHMflag). Even with VHMflag off, VHrecon is capped at it: a "
            "VHcease below the post-event voltage means the load never reconnects."),
    ConSpec("Tcease", "Momentary cease delay", "s", _G["mom"], 0.0, None, (0.0, 1.0),
            "Recovering earlier cancels it; two short dips do not accumulate. Negative acts as 0."),
    ConSpec("Tdelay", "Extra delay before the load is reduced", "s", _G["mom"], 0.0, None, (0.0, 0.5),
            TDELAY_NOTE),
    ConSpec("frecon", "Fraction of fcease that reconnects", "", _G["mom"], 0.0, None, (0.0, 1.0),
            "Final FracOn = (1 - fcease) + frecon x fcease; > 1 returns above the initial load; negative acts as 0."),
    ConSpec("VLrecon", "Reconnect window, low edge", "pu", _G["mom"], 0.0, None, (0.5, 0.95),
            "Reconnection needs VLrecon < Vtf < VHrecon. Raised to VLcease if lower. A long-cease threshold above it "
            "lets the load reconnect while still in the sag and cease again (cycling)."),
    ConSpec("VHrecon", "Reconnect window, high edge", "pu", _G["mom"], 1.0, None, (1.02, 1.15),
            "Lowered to VHcease if higher (whatever VHMflag is)."),
    ConSpec("Tramp", "Reconnect ramp (momentary cease)", "s", _G["mom"], 0.0, None, (0.0, 60.0),
            "The ramp lasts Tramp x Ldfact seconds (TrampUsed). 0 or negative = instant."),
    ConSpec("Trecon", "Reconnect delay (momentary cease)", "s", _G["mom"], 0.0, None, (0.0, 60.0),
            "Time inside the reconnect window before the ramp starts. Negative acts as 0."),
    ConSpec("TLrampL", "Reconnect ramp after a long low-voltage cease", "s", _G["ll"], 0.0, None, (0.0, 60.0),
            "Used as TLrampL x Ldfact."),
    ConSpec("TLreconL", "Reconnect delay after a long low-voltage cease", "s", _G["ll"], 0.0, None, (0.0, 60.0),
            "0 or negative: the ramp starts the moment the load ceases if Vtf is inside the reconnect window."),
    *(ConSpec(f"VLC{i}", f"Long low-voltage point {i}, voltage", "pu", _G["ll"], 0.0, None, (0.1, 0.95),
              "PSS/E 36.7.1 ceases after TVLC1 (point 1's time) below this, not after TVLC3." if i == BROKEN_LONG_POINT
              else "Vtf < VLC for TVLC ceases (VLLflag).") for i in (1, 2, 3, 4)),
    *(ConSpec(f"TVLC{i}", f"Long low-voltage point {i}, time", "s", _G["ll"], 0.0, None, (0.0, 30.0),
              "Not used by PSS/E 36.7.1 (point 3 waits TVLC1)." if i == BROKEN_LONG_POINT else
              "0 or negative = as soon as Vtf is below the point." + (" Also times point 3." if i == 1 else ""))
      for i in (1, 2, 3, 4)),
    ConSpec("TLrampH", "Reconnect ramp after a long high-voltage cease", "s", _G["lh"], 0.0, None, (0.0, 60.0),
            "Used as TLrampH x Ldfact."),
    ConSpec("TLreconH", "Reconnect delay after a long high-voltage cease", "s", _G["lh"], 0.0, None, (0.0, 60.0), ""),
    *(ConSpec(f"VHC{i}", f"Long high-voltage point {i}, voltage", "pu", _G["lh"], 1.0, None, (1.05, 1.5),
              "PSS/E 36.7.1 ceases after TVHC1 (point 1's time) above this, not after TVHC3." if i == BROKEN_LONG_POINT
              else "Vtf > VHC for TVHC ceases (VLHflag).") for i in (1, 2, 3, 4)),
    *(ConSpec(f"TVHC{i}", f"Long high-voltage point {i}, time", "s", _G["lh"], 0.0, None, (0.0, 30.0),
              "Not used by PSS/E 36.7.1 (point 3 waits TVHC1)." if i == BROKEN_LONG_POINT else
              ("Also times point 3." if i == 1 else "")) for i in (1, 2, 3, 4)),
    ConSpec("FLC1", "Low-frequency cease threshold", "Hz", _G["f"], None, 60.0, (57.0, 59.5),
            "f < FLC1 for TFLC1 ceases for good (FLflag). At or above the initial frequency the load ceases at t = "
            "TFLC1 with no disturbance."),
    ConSpec("TFLC1", "Low-frequency cease time", "s", _G["f"], 0.0, None, (0.0, 600.0), ""),
    ConSpec("FHC1", "High-frequency cease threshold", "Hz", _G["f"], 60.0, None, (60.5, 63.0),
            "f > FHC1 for TFHC1 ceases for good (FHflag)."),
    ConSpec("TFHC1", "High-frequency cease time", "s", _G["f"], 0.0, None, (0.0, 600.0), ""),
)}
assert set(_SPECS) == set(CON_NAMES)
CON_SPECS: dict[str, ConSpec] = {n: _SPECS[n] for n in CON_NAMES}  # in record order

DISPLAY_FIELDS = tuple((n, s.label + (f" ({s.unit})" if s.unit and s.unit != "flag" else ""), n)
                       for n, s in CON_SPECS.items())

# Names PERC1 (standard) and this model share or map onto, for tooltips. The note-7 recipe: VLcease = Vcease,
# VLrecon = Vrecon, Tramp = PERC1 Tramp / Ldfact.
PERC1_STANDARD_ANALOGS = {"VLcease": "Vcease", "VLrecon": "Vrecon", "Tcease": "Tcease", "Tdelay": "Tdelay",
                          "Trecon": "Trecon", "Tramp": "Tramp / Ldfact", "fcease": "fcease", "frecon": "frecon"}

DEFAULT_TIME_STEP_S = 1.0 / 240.0
NOMINAL_HZ = 60.0
POST_FAULT_PEAK_WARN_PU = 1.10


def effective_ldfact(cons) -> float:
    return cons["Ldfact"] if cons["Ldfact"] > 0 else 0.8


def effective_limits(cons, ip=None):
    """(IpmaxUsed, IpminUsed, IqmaxUsed, IqminUsed) as PSS/E 36.7.1 computes them (the block diagram's min/max, with
    |Imax|); `ip` is the active-current order for the reactive limits (default: the initial one)."""
    imax = abs(cons["Imax"])
    ipmax_u = min(cons["Ipmax"], imax)
    ipmin_u = max(cons["Ipmin"], -imax)
    ipv = effective_ldfact(cons) if ip is None else ip
    room = math.sqrt(max(imax * imax - ipv * ipv, 0.0))
    return ipmax_u, ipmin_u, min(cons["Iqmax"], room), max(cons["Iqmin"], -room)


def post_fault_peak_pu(cons) -> float:
    """The most active power the block can draw right after a deep fault clears, in pu of its initial power (the same
    mechanism as PERC1 standard: a constant-power block is current-limited in the sag and the voltage returns before
    the current relaxes, P = V x IpmaxUsed / Ldfact). nP >= 1 has no spike."""
    if cons["nP"] >= 1.0:
        return 1.0
    return max(1.0, effective_limits(cons)[0] / effective_ldfact(cons))


def post_fault_peak_warning(cons) -> str | None:
    peak = post_fault_peak_pu(cons)
    if peak <= POST_FAULT_PEAK_WARN_PU:
        return None
    return (f"a constant-power block (nP {cons['nP']:g}) can draw up to {peak * 100:.0f}% of its power for about 0.1 s "
            f"when a fault clears (min(Ipmax, Imax) {effective_limits(cons)[0]:g} / Ldfact "
            f"{effective_ldfact(cons):g}). Lower Ipmax toward Ldfact or raise nP to 1 to reduce it.")


@dataclass(frozen=True)
class ConIssue:
    level: str  # "error" (PSS/E rejects it or the result is nonsense) | "warning" (silently changed, or a hazard)
    con: str
    message: str


def validate_cons(cons, time_step_s: float = DEFAULT_TIME_STEP_S, initial_voltage_pu: float = 1.0,
                  nominal_hz: float = NOMINAL_HZ) -> list[ConIssue]:
    """Everything PSS/E 36.7.1 would reject, silently change, or turn into a hazard. An empty list means the values
    mean in PSS/E exactly what they say."""
    missing = [n for n in CON_NAMES if n not in cons]
    if missing:
        return [ConIssue("error", missing[0], f"missing value(s): {', '.join(missing)}")]
    issues: list[ConIssue] = []
    c = {n: float(cons[n]) for n in CON_NAMES}
    for n, v in c.items():
        if not math.isfinite(v):
            issues.append(ConIssue("error", n, "must be a finite number"))
    if issues:
        return issues

    def err(con, msg):
        issues.append(ConIssue("error", con, msg))

    def warn(con, msg):
        issues.append(ConIssue("warning", con, msg))

    on = {n: flag_on(cons, n) for n in ICON_NAMES}
    for n in ICON_NAMES:
        if c[n] not in (0.0, 1.0):
            warn(n, f"{c[n]:g} is not 0 or 1; PSS/E treats anything but 1 as off")
    ld = effective_ldfact(c)
    if c["Ldfact"] <= 0:
        warn("Ldfact", "must be > 0; PSS/E will use 0.8")
    elif c["Ldfact"] > 1:
        warn("Ldfact", "the data sheet limits it to <= 1 (and says PSS/E then uses 0.8); 36.7.1 uses it as given")
    if c["Imax"] == 0:
        err("Imax", "0 makes every current limit 0: the block draws nothing")
    elif c["Imax"] < 0:
        warn("Imax", "negative; PSS/E uses its magnitude")
    ipmax_u, _ipmin_u, iqmax_u, _iqmin_u = effective_limits(c)
    if c["Ipmax"] < c["Ipmin"]:
        err("Ipmax", "Ipmax < Ipmin: the limiter returns Ipmax, so the block draws Ipmax (0 here means no load)")
    if c["Iqmax"] < c["Iqmin"]:
        err("Iqmax", "Iqmax < Iqmin: the limiter returns Iqmax")
    if ipmax_u * initial_voltage_pu < ld - 1e-9 and c["Imax"] != 0:
        warn("Ipmax", f"min(Ipmax, Imax) = {ipmax_u:g} is below Ldfact {ld:g}: the block cannot draw its power-flow "
                      f"load and starts at {ipmax_u / ld * 100:.0f}% of it (PSS/E gives no message)")
    if c["Ipmin"] < 0:
        warn("Ipmin", "< 0 lets the load export active power")
    if c["Imax"] > 0 and c["Iqmax"] > iqmax_u + 1e-9:
        warn("Iqmax", f"limited to {iqmax_u:.3g} by Imax at the initial current (active current has priority)")
    if not 0.0 <= c["fcease"] <= 1.0:
        warn("fcease", "outside [0, 1]; PSS/E clamps it (with a message)")
    if c["frecon"] < 0:
        warn("frecon", "negative; PSS/E treats it as 0")
    for n in ("Tcease", "Tdelay", "Trecon", "Tramp", "TLrampL", "TLreconL", "TLrampH", "TLreconH", "Tv", "Tf"):
        if c[n] < 0:
            warn(n, "negative; PSS/E treats it as 0 without a message")
    if c["Tt"] < 2 * time_step_s:
        warn("Tt", f"below 2 x time step ({2 * time_step_s:.5f} s); PSS/E raises it to that without a message")
    # the reconnect window
    vhrecon_used = min(c["VHrecon"], c["VHcease"])
    vlrecon_used = max(c["VLrecon"], c["VLcease"])
    if c["VLrecon"] < c["VLcease"]:
        warn("VLrecon", "below VLcease; PSS/E silently raises it to VLcease")
    if c["VHrecon"] > c["VHcease"]:
        warn("VHrecon", f"above VHcease; PSS/E silently lowers it to VHcease ({c['VHcease']:g})"
             + ("" if on["VHMflag"] else ", even though VHMflag is off"))
    if c["fcease"] > 0:
        if vhrecon_used <= initial_voltage_pu:
            err("VHcease" if c["VHcease"] < c["VHrecon"] else "VHrecon",
                f"the reconnect window's high edge is {vhrecon_used:g} pu, at or below the initial voltage: a load that "
                "ceases never reconnects (VHrecon is capped at VHcease whatever VHMflag is)")
        if vlrecon_used >= initial_voltage_pu:
            err("VLrecon", f"the reconnect window's low edge is {vlrecon_used:g} pu, at or above the initial voltage: "
                           "a load that ceases never reconnects")
        elif vlrecon_used > 0.95 * initial_voltage_pu:
            warn("VLrecon", "Vtf must be strictly above it, and recovers toward the post-fault voltage from below: a "
                            "post-fault voltage at or below VLrecon never reconnects")
        if on["VLMflag"] and c["VLcease"] >= initial_voltage_pu:
            err("VLcease", "at or above the initial voltage: the load ceases at t = 0")
        if on["VHMflag"] and c["VHcease"] <= initial_voltage_pu:
            err("VHcease", "at or below the initial voltage: the load ceases at t = 0")
        for i in (1, 2, 3, 4):
            if on["VLLflag"] and c[f"VLC{i}"] > 0:
                if i == BROKEN_LONG_POINT:
                    warn(f"VLC{i}", f"PSS/E 36.7.1 times point 3 with TVLC1 ({c['TVLC1']:g} s), not TVLC3 "
                                    f"({c['TVLC3']:g} s); use points 1, 2 and 4, or set VLC3 = 0")
                elif c[f"VLC{i}"] >= initial_voltage_pu:
                    err(f"VLC{i}", "at or above the initial voltage: the load ceases with no disturbance")
                elif c[f"VLC{i}"] > vlrecon_used:
                    warn(f"VLC{i}", f"above the reconnect window's low edge ({vlrecon_used:g} pu): a sag between them "
                                    "ceases the load, reconnects it inside the sag and ceases it again (cycling)")
            if on["VLHflag"] and c[f"VHC{i}"] < 90:
                if i == BROKEN_LONG_POINT:
                    warn(f"VHC{i}", f"PSS/E 36.7.1 times point 3 with TVHC1 ({c['TVHC1']:g} s), not TVHC3 "
                                    f"({c['TVHC3']:g} s); use points 1, 2 and 4, or set VHC3 = 99")
                elif c[f"VHC{i}"] <= initial_voltage_pu:
                    err(f"VHC{i}", "at or below the initial voltage: the load ceases with no disturbance")
                elif c[f"VHC{i}"] < vhrecon_used:
                    warn(f"VHC{i}", f"below the reconnect window's high edge ({vhrecon_used:g} pu): a swell between them "
                                    "ceases the load, reconnects it inside the swell and ceases it again (cycling)")
        if on["FLflag"] and c["FLC1"] >= nominal_hz:
            err("FLC1", "at or above nominal frequency: the load ceases for good after TFLC1 with no disturbance")
        if on["FHflag"] and c["FHC1"] <= nominal_hz:
            err("FHC1", "at or below nominal frequency: the load ceases for good after TFHC1 with no disturbance")
    if c["Kvp"] != 0 and c["Tvp"] <= 0:
        warn("Tvp", "Kvp is on but Tvp <= 0")
    if c["Kvq"] != 0 and c["Tvq"] <= 0:
        warn("Tvq", "Kvq is on but Tvq <= 0")
    if c["dbfl"] > 0:
        warn("dbfl", "the lower deadband edge should be <= 0")
    if c["dbfh"] < 0:
        warn("dbfh", "the upper deadband edge should be >= 0")
    return issues
