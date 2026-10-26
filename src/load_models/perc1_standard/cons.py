"""PERC1 *standard* variant (PSS/E 36.7 PERCxx1U): CON layout, defaults, limits.

Source: PSS/E 36.7.1 ModelLibrary.pdf, section 13.6, "PERCBL1U, PERCOW1U,
PERCZN1U, PERCAR1U, PERCAL1U - Power Electronic Load Component Model with
Reconnect and Cease Logic" (printed pages 600-609). Names below are the data
sheet's own; order is J..J+29. This is a different model from the DLL
variant in `perc1_dll` - different CONs, different record type, built into
PSS/E (no DLL).

Every limit and default below was checked against PSS/E 36.7.1 itself; the
evidence is in the PSS/E validation library, which is not published (summarized in
docs/user/model_perc1_standard.md). Where the data sheet and PSS/E disagree, this
module follows PSS/E and says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

CON_NAMES = (
    "Ldfact", "QPratio", "dbfl", "dbfh", "Kdroop",
    "Kvp", "Tvp", "Kvq", "Tvq",
    "Tap", "Tbp", "Taq", "Tbq",
    "nP", "nQ",
    "Ipmax", "Ipmin", "Iqmax", "Iqmin",
    "fcease", "Vcease", "Tcease", "Tdelay", "Vrecon", "Trecon", "Tramp", "frecon",
    "Tt", "Tv", "Tf",
)
assert len(CON_NAMES) == 30 and len(set(CON_NAMES)) == 30

# The data sheet's "Value" column ("for example purposes only"). Its QPratio
# value is blank (0.0 here). NOT a recommendation: with Tdelay > 0 it can kill
# a PSS/E 36.7.1 run (see TDELAY_HAZARD below).
SHEET_EXAMPLE_CONS = {
    "Ldfact": 0.8, "QPratio": 0.0, "dbfl": 0.0, "dbfh": 0.0, "Kdroop": 10.0,
    "Kvp": 0.2, "Tvp": 0.05, "Kvq": 0.5, "Tvq": 0.1,
    "Tap": 1.0, "Tbp": 1.0, "Taq": 1.0, "Tbq": 1.0,
    "nP": 2.0, "nQ": 1.0,
    "Ipmax": 1.0, "Ipmin": 0.0, "Iqmax": 0.7, "Iqmin": -0.7,
    "fcease": 0.9, "Vcease": 0.5, "Tcease": 0.05, "Tdelay": 0.05, "Vrecon": 0.6, "Trecon": 0.05,
    "Tramp": 1.0, "frecon": 0.5,
    "Tt": 0.02, "Tv": 0.05, "Tf": 0.02,
}

# The app's starting point: the data sheet's example, changed in four places.
#  Tdelay 0     - any dip that ends while Tdelay is running makes PSS/E 36.7.1 return NaN forever (measured in PSS/E).
#  Kvp/Kvq 0    - washouts off, like the DLL variant's KWASH defaults; the sheet's 0.2/0.5 add a transient the
#                 sheet gives no basis for. Tvp/Tvq stay nonzero so turning them on needs one edit.
#  Kdroop 8     - the DLL variant's default droop (DROOPA 10) expressed on this model's MVA base (x Ldfact 0.8).
#  nP/nQ 0      - constant-power electronics, the double-conversion default of the DLL variant.
DEFAULT_CONS = {
    **SHEET_EXAMPLE_CONS,
    "Tdelay": 0.0, "Kvp": 0.0, "Kvq": 0.0, "Kdroop": 8.0, "nP": 0.0, "nQ": 0.0,
}

TDELAY_HAZARD = (
    "A voltage dip that ends while the Tdelay timer is running (after Tcease expires, before Tcease + Tdelay) makes "
    "PSS/E 36.7.1 return NaN for the whole network from then on. Only Tdelay = 0 is safe for every dip length."
)


@dataclass(frozen=True)
class ConSpec:
    """One CON: what it is, its unit, and the range PSS/E 36.7.1 accepts.
    `lo`/`hi` are the sheet's stated limits (None = unbounded); `typical` is
    the span a UI should suggest, narrower than the limits."""

    name: str
    label: str
    unit: str
    group: str
    lo: float | None
    hi: float | None
    typical: tuple[float, float]
    note: str = ""


_G = {"base": "Load basis", "droop": "Frequency droop", "p": "Active-power path", "q": "Reactive-power path",
      "lim": "Current limits", "cease": "Cease and reconnect", "filt": "Measurement and converter"}

CON_SPECS: dict[str, ConSpec] = {s.name: s for s in (
    ConSpec("Ldfact", "Load factor (sets the MVA base)", "pu", _G["base"], 0.0, 1.0, (0.5, 1.0),
            "MVA base = initial P / Ldfact; every pu CON below is on that base. <= 0 -> PSS/E uses 0.8. The data sheet says "
            "> 1 also falls back to 0.8; PSS/E 36.7.1 actually accepts it."),
    ConSpec("QPratio", "Q/P ratio (initial reactive power)", "pu", _G["base"], None, None, (-0.3, 0.5),
            "Qinit = QPratio * Pinit. The difference to the load's power-flow Q is absorbed as ExtraVars."),
    ConSpec("dbfl", "Droop deadband, lower edge", "pu freq", _G["droop"], None, 0.0, (-0.01, 0.0),
            "Must be <= 0 (a deviation, 0.005 pu = 0.3 Hz). PSS/E's own warning text says '>= 0' but a positive value is "
            "what it rejects."),
    ConSpec("dbfh", "Droop deadband, upper edge", "pu freq", _G["droop"], 0.0, None, (0.0, 0.01), "Must be >= 0."),
    ConSpec("Kdroop", "Droop gain", "pu P / pu f", _G["droop"], None, None, (0.0, 20.0),
            "dP = Kdroop * (df - deadband) in pu of the MVA base; P falls when f falls. 0 disables. Not limited by PSS/E."),
    ConSpec("Kvp", "P-path washout gain", "pu*s", _G["p"], None, None, (0.0, 1.0),
            "Washout sK/(1+sT) on the unfiltered bus voltage, added to Pinit. 0 disables."),
    ConSpec("Tvp", "P-path washout time constant", "s", _G["p"], 0.0, None, (0.02, 1.0), "Keep > 0 when Kvp != 0."),
    ConSpec("Kvq", "Q-path washout gain", "pu*s", _G["q"], None, None, (0.0, 1.0), "0 disables."),
    ConSpec("Tvq", "Q-path washout time constant", "s", _G["q"], 0.0, None, (0.02, 1.0),
            "Keep > 0 when Kvq != 0 (Tvq = 0 makes the washout output 0)."),
    ConSpec("Tap", "P-path lead time constant", "s", _G["p"], 0.0, None, (0.0, 2.0), "Lead-lag (1+sTap)/(1+sTbp)."),
    ConSpec("Tbp", "P-path lag time constant", "s", _G["p"], 0.0, None, (0.0, 2.0),
            "<= 0 bypasses the whole lead-lag (Tap is then ignored)."),
    ConSpec("Taq", "Q-path lead time constant", "s", _G["q"], 0.0, None, (0.0, 2.0), ""),
    ConSpec("Tbq", "Q-path lag time constant", "s", _G["q"], 0.0, None, (0.0, 2.0), ""),
    ConSpec("nP", "P voltage exponent", "", _G["p"], None, None, (0.0, 2.0),
            "P = P0 * (V/V0)^nP in steady state: 0 constant power, 1 current, 2 impedance. Any real number works."),
    ConSpec("nQ", "Q voltage exponent", "", _G["q"], None, None, (0.0, 2.0), "Same for Q."),
    ConSpec("Ipmax", "Maximum active current", "pu", _G["lim"], 0.0, None, (0.5, 1.5),
            "Limiter is min(max(I, Imin), Imax): Imax wins if the two cross. Caps P at V*Ipmax*MVA base (a constant-power "
            "load below ~0.8 pu voltage is current-limited), so when a fault clears a constant-power load briefly draws "
            "Ipmax/Ldfact times its power (155% at 1.25 / 0.8) before the current relaxes."),
    ConSpec("Ipmin", "Minimum active current", "pu", _G["lim"], 0.0, None, (0.0, 0.0), "Keep >= 0 or the load backfeeds."),
    ConSpec("Iqmax", "Maximum reactive current", "pu", _G["lim"], 0.0, None, (0.3, 1.0), "Must be >= Iqmin."),
    ConSpec("Iqmin", "Minimum reactive current", "pu", _G["lim"], None, 0.0, (-1.0, 0.0), ""),
    ConSpec("fcease", "Fraction that ceases", "", _G["cease"], 0.0, 1.0, (0.0, 1.0),
            "Outside [0,1] PSS/E clamps it (with a message). 0 turns the whole cease logic off (FracOn = 1)."),
    ConSpec("Vcease", "Cease voltage (filtered)", "pu", _G["cease"], 0.0, None, (0.1, 0.95),
            "Strictly Vtf < Vcease starts Tcease. Vtf is the Tv-filtered voltage, so a dip 'to' exactly Vcease is "
            "undefined; leave margin."),
    ConSpec("Tcease", "Time below Vcease before ceasing starts", "s", _G["cease"], 0.0, None, (0.0, 1.0),
            "Negative values behave as 0 (silently). Recovering before it expires cancels the cease."),
    ConSpec("Tdelay", "Extra delay before the load is reduced", "s", _G["cease"], 0.0, None, (0.0, 0.0),
            "Keep 0: " + TDELAY_HAZARD),
    ConSpec("Vrecon", "Reconnect voltage (filtered)", "pu", _G["cease"], 0.0, None, (0.5, 1.0),
            "Must be >= Vcease (lower is silently raised). Strictly Vtf > Vrecon starts Trecon, and Vtf approaches the "
            "post-fault voltage from below: Vrecon >= that voltage never reconnects. Keep it at or below ~0.95."),
    ConSpec("Trecon", "Time above Vrecon before the ramp starts", "s", _G["cease"], 0.0, None, (0.0, 60.0), "Negative -> 0."),
    ConSpec("Tramp", "Reconnect ramp time", "s", _G["cease"], 0.0, None, (0.0, 60.0),
            "Linear in simulated time (not per psspy.run call). 0 or negative = instant."),
    ConSpec("frecon", "Fraction of fcease that reconnects", "", _G["cease"], 0.0, None, (0.0, 1.0),
            "Final FracOn = (1 - fcease) + frecon*fcease; > 1 returns above the initial load. Negative -> 0."),
    ConSpec("Tt", "Converter delay", "s", _G["filt"], 0.0, None, (0.01, 0.05),
            "PSS/E raises anything below 2 x time step (0.00833 s at 1/4 cycle) to 2 x time step, silently."),
    ConSpec("Tv", "Voltage measurement time constant", "s", _G["filt"], 0.0, None, (0.0, 0.1),
            "Filters the voltage the cease/reconnect thresholds see. Negative behaves as 0."),
    ConSpec("Tf", "Frequency measurement time constant", "s", _G["filt"], 0.0, None, (0.0, 0.5), "Negative behaves as 0."),
)}
assert tuple(CON_SPECS) == CON_NAMES

# Report/editor rows: (con, label, tooltip).
DISPLAY_FIELDS = tuple((n, s.label + (f" ({s.unit})" if s.unit else ""), n) for n, s in CON_SPECS.items())

# Names the DLL variant and this model share, for readers moving between them (tooltips only; the two models
# differ - see docs/developer/PERC1_MODEL.md).
DLL_ANALOGS = {"Vcease": "VDPA", "Tcease": "DMA", "fcease": "FCEASE", "Vrecon": "VRPA", "Trecon": "TDRA", "Tramp": "RAMPA",
               "frecon": "FRECON", "nP": "NPA", "nQ": "NQA", "Tt": "TRA", "Ipmax": "IPMAXA", "Ipmin": "IPMINA",
               "Iqmax": "IQMAXA", "Iqmin": "IQMINA", "Tv": "TVM", "Tf": "TFRQ", "Ldfact": "LFM", "Kdroop": "DROOPA"}

# PSS/E's own time step at the quarter-cycle default, for the Tt floor.
DEFAULT_TIME_STEP_S = 1.0 / 240.0


# A post-fault peak above this (pu of the block's initial power) is worth a warning.
POST_FAULT_PEAK_WARN_PU = 1.10


def post_fault_peak_pu(cons) -> float:
    """The most active power a block can draw, in pu of its initial power, right after a deep fault clears. A constant-power
    block (nP < 1) asks for a large current in the sag, the limiter holds it at Ipmax, and the voltage returns before the
    current has relaxed: P = V x Ipmax / Ldfact (measured in PSS/E 36.7.1). Blocks
    with nP >= 1 have no spike. This is an upper bound for 0 < nP < 1."""
    ldfact = cons["Ldfact"] if cons["Ldfact"] > 0 else 0.8
    if cons["nP"] >= 1.0:
        return 1.0
    return max(1.0, cons["Ipmax"] / ldfact)


def post_fault_peak_warning(cons) -> str | None:
    peak = post_fault_peak_pu(cons)
    if peak <= POST_FAULT_PEAK_WARN_PU:
        return None
    ldfact = cons["Ldfact"] if cons["Ldfact"] > 0 else 0.8
    return (f"a constant-power block (nP {cons['nP']:g}) can draw up to {peak * 100:.0f}% of its power for about 0.1 s when a "
            f"fault clears (Ipmax {cons['Ipmax']:g} / Ldfact {ldfact:g}). Lower Ipmax toward Ldfact or raise nP to 1 to reduce it.")


@dataclass(frozen=True)
class ConIssue:
    level: str  # "error" (PSS/E rejects it or the result is nonsense) | "warning" (silently changed, or a known hazard)
    con: str
    message: str


def validate_cons(cons, time_step_s: float = DEFAULT_TIME_STEP_S) -> list[ConIssue]:
    """Everything PSS/E 36.7.1 would reject, silently change, or choke on. An
    empty list means the CONs mean in PSS/E exactly what they say."""
    issues: list[ConIssue] = []
    missing = [n for n in CON_NAMES if n not in cons]
    if missing:
        return [ConIssue("error", missing[0], f"missing CON(s): {', '.join(missing)}")]
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

    if c["Ldfact"] <= 0:
        warn("Ldfact", "must be > 0; PSS/E will use 0.8")
    elif c["Ldfact"] > 1:
        warn("Ldfact", "the data sheet limits it to <= 1 (and says PSS/E then uses 0.8); 36.7.1 accepts it as given")
    if c["dbfl"] > 0:
        err("dbfl", "must be <= 0; PSS/E rejects a positive lower deadband edge")
    if c["dbfh"] < 0:
        err("dbfh", "must be >= 0; PSS/E rejects a negative upper deadband edge")
    if c["Ipmax"] < c["Ipmin"]:
        err("Ipmax", "Ipmax < Ipmin: the limiter returns Ipmax, i.e. the load draws Ipmax regardless")
    if c["Iqmax"] < c["Iqmin"]:
        err("Iqmax", "Iqmax < Iqmin: the limiter returns Iqmax")
    if c["Ipmax"] <= 0:
        warn("Ipmax", "<= 0 gives zero or negative active power")
    if c["Ipmin"] < 0:
        warn("Ipmin", "< 0 lets the load export active power")
    if not 0.0 <= c["fcease"] <= 1.0:
        warn("fcease", "outside [0, 1]; PSS/E clamps it")
    if c["Vcease"] <= 0:
        warn("Vcease", "<= 0 never ceases (and a 0 pu voltage makes the model return NaN)")
    if c["Vrecon"] >= 1.0:
        warn("Vrecon", "at or above 1.0 pu: the filtered voltage must be strictly above it, so a load that recovers to "
                       "1.0 pu or less never reconnects")
    if c["Vrecon"] < c["Vcease"]:
        warn("Vrecon", "below Vcease; PSS/E silently raises it to Vcease")
    for n in ("Tcease", "Tdelay", "Trecon", "Tramp", "frecon", "Tv", "Tf"):
        if c[n] < 0:
            warn(n, "negative; PSS/E treats it as 0 without a message")
    if c["Tdelay"] > 0:
        warn("Tdelay", TDELAY_HAZARD)
    if c["Tt"] < 2 * time_step_s:
        warn("Tt", f"below 2 x time step ({2 * time_step_s:.5f} s); PSS/E raises it to that")
    if c["Kvp"] != 0 and c["Tvp"] <= 0:
        warn("Tvp", "Kvp is on but Tvp <= 0")
    if c["Kvq"] != 0 and c["Tvq"] <= 0:
        warn("Tvq", "Kvq is on but Tvq <= 0")
    if c["Tbp"] <= 0 and c["Tap"] > 0:
        warn("Tap", "Tbp <= 0 bypasses the P lead-lag, so Tap has no effect")
    if c["Tbq"] <= 0 and c["Taq"] > 0:
        warn("Taq", "Tbq <= 0 bypasses the Q lead-lag, so Taq has no effect")
    return issues
