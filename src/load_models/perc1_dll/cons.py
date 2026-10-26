"""PERC1 (DLL variant) CON layout, vendor defaults, and display metadata.

**PERC1 has (at least) two distinct PSS/E implementations, with different CON
layouts - this app must not conflate them:**

- **"DLL" variant** - available in PSS/E v34 and v35 (a compiled-DLL user
  model, developed by ISO New England / ISO-NE). This is the only variant
  this app currently supports, and every data structure below (unless
  otherwise named) describes it. Its full 173-CON layout, order, and
  vendor-typical defaults were verified 2026-09-17 directly against the
  vendor's own documentation
  ("Data_Center_Performance_Model_PERC1_PSSEV34_V35_documentation_Rev7.pdf")
  - every CON name and J-offset in that document's own data sheet matches
  this module's layout exactly. See
  `PERC1_FIXED_DEFAULTS`'s own note for the one real naming
  inconsistency found (`TRQ`/`TFRQ`) and the two values (`IPMAXA`,
  `CMTDELAY`) that turned out to have no vendor-specified default at all.
- **"Standard" variant** - available starting PSS/E v36.5, as PSS/E's own
  built-in standard model rather than a separately-loaded DLL. Part of a
  cross-vendor PERC1 harmonization effort (publicly introduced Nov 2025,
  behaving identically across PowerWorld/TSAT/PSLF/PSS/E). It lives in its
  own package, `load_models/perc1_standard/` (model id `perc1_standard`), with
  30 CONs measured in PSS/E 36.7.1. Do not assume it shares the DLL variant's
  CON names, defaults, or even its overall structure.

The vendor's own Rev7 documentation states the DLL variant (PSS/E v34/v35,
ISO/NE) adds five features versus PSS/E's standard model: (1) a high AND low
voltage ride-through no-trip zone, (2) high/low voltage reconnection with a
ramp rate, (3) a high AND low frequency ride-through no-trip zone, (4)
high/low frequency reconnection with a ramp rate, and (5) momentary
cessation. In this app's own terms: **the Standard variant has no
overvoltage (VDUA/TDUA-equivalent) cease/reconnect, no frequency
cease/reconnect, no Option-2 momentary cessation, and no Option-3 stepped
multi-level trip table** (confirmed in PSS/E 36.7.1) - only the single
undervoltage cease/reconnect this app calls "Option 1" carries over. Do not
backfill assumptions about one variant using data about the other - they are
different models that happen to share a name and that one common concept.
"""


# Full name -> value defaults for every CON except the 10 core cease/reconnect
# and ZIP CONs, which PERC1_DEFAULT_CONS below adds. The full 173-CON layout below (names, order, and
# every value here) was verified 2026-09-17 against the vendor's own DLL
# variant documentation ("Data_Center_Performance_Model_PERC1_PSSEV34_V35_
# documentation_Rev7.pdf") plus two independent example .dyr records it and
# an earlier vendor sample both contain - every CON name and position matches
# the vendor's own J..J+172 data sheet exactly. `TFRQ` (final CON) is named
# `TRQ` in that data sheet's own prose table but `TFRQ` in both its own
# worked .dyr examples' "@!" comment rows (the same inconsistency exists for
# `KWASHA`/`TWASHA`, called `KWASHP`/`TWASHP` in the prose table only) - this
# app follows the .dyr-comment spelling, since that's what the file format
# itself actually uses.
#
# Values for the B/C/D repeated channel blocks and the ZETA/WNA rows are all
# 0.0 because the model does not use them (single-channel "A" block only);
# `VDPA1..3`/`DMA1..3`, `VDUA1..3`/`TDUA1..3`, `VRUPA`/`TRUPA`/`RAMPUA`, and
# frequency-protection stage 1 carry values confirmed identical across both
# independent vendor examples, so they're a genuine vendor-typical default,
# not a guess. `IPMAXA` and `CMTDELAY` are different: the vendor
# documentation does not specify a default for either (both are legitimately
# facility-specific - current draw capability and communication-system
# latency respectively - and the two vendor examples use different values for
# both), so the values below are this app's own neutral baseline choice
# (`IPMAXA=1.0`: no special overcurrent capability assumed, matching
# `presets.ridethrough._bundle()`'s own unlabeled default; `CMTDELAY=0.0`: no
# extra communication lag assumed), not a vendor-mandated constant - do not
# "fix" these to match either vendor sample number, since neither is more
# authoritative than the other for these two fields.
PERC1_FIXED_DEFAULTS = {
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
    # this, every CON-dict-building step in this app (PERC1_DEFAULT_CONS
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
    PERC1_FIXED_DEFAULTS.update({
        f"FOFTP{_n}": 99.0, f"TOFTP{_n}": 999.0,
        f"FOFRN{_n}": 99.0, f"TOFRN{_n}": 999.0, f"ROFRN{_n}": 999.0,
        f"FUFTP{_n}": 99.0, f"TUFTP{_n}": 999.0,
        f"FUFRN{_n}": 99.0, f"TUFRN{_n}": 999.0, f"RUFRN{_n}": 999.0,
    })
for _suffix in ("B", "C", "D"):
    for _name in ("VDP", "DM", "TDR", "VRP", "RAMP", "DROOP", "KWASH", "TWASH", "TA", "TB",
                  "FR", "NP", "VNOM", "IPMAX", "IPMIN", "IQMAX", "IQMIN", "TR", "NQ", "DB", "VDU", "TDU"):
        PERC1_FIXED_DEFAULTS[f"{_name}{_suffix}"] = 0.0
    for _name in ("VRUP", "TRUP", "RAMPU"):
        PERC1_FIXED_DEFAULTS[f"{_name}{_suffix}"] = 0.0
for _name in ("ZETAA", "WNAA", "ZETAB", "WNAB", "ZETAC", "WNAC", "ZETAD", "WNAD"):
    PERC1_FIXED_DEFAULTS[_name] = 0.0
del _n, _suffix, _name


def _dll_channel_block(suffix):
    # The lead-lag CONs are named bare "TA"/"TB" for the primary ("A") channel
    # but "TAB"/"TBB", "TAC"/"TBC", "TAD"/"TBD" for the unused B/C/D channels
    # - an irregularity in the vendor's own naming, not a typo to normalize.
    lead_lag = ["TA", "TB"] if suffix == "A" else [f"TA{suffix}", f"TB{suffix}"]
    return (
        [f"{n}{suffix}" for n in ("VDP", "DM", "TDR", "VRP", "RAMP", "DROOP", "KWASH", "TWASH")]
        + lead_lag
        + [f"{n}{suffix}" for n in ("FR", "NP", "VNOM", "IPMAX", "IPMIN", "IQMAX", "IQMIN", "TR", "NQ", "DB", "VDU", "TDU")]
    )


def _dll_freq_block(suffix):
    return [f"{n}{suffix}" for n in (
        "FOFTP", "TOFTP", "FOFRN", "TOFRN", "ROFRN", "FUFTP", "TUFTP", "FUFRN", "TUFRN", "RUFRN",
    )]


# The exact CON(J) .. CON(J+172) ordering for the PSS/E PERC1 DLL variant UDM,
# verified directly against a vendor-supplied example .dyr record (2026-09-17)
# and grouped exactly as that example file groups them (each tuple is one
# "@!"-commented row group). This is the single source of truth both for
# validating PERC1_FIXED_DEFAULTS/PERC1_DEFAULT_CONS below and for
# export/dyr.py's .dyr record emission - a name appearing here but missing from
# a params dict is a bug, so the .dyr builder should fail loudly rather than
# silently drop a CON.
PERC1_DYR_LAYOUT = [
    _dll_channel_block("A"),
    _dll_channel_block("B"),
    _dll_channel_block("C"),
    _dll_channel_block("D"),
    ["ZETAA", "WNAA", "ZETAB", "WNAB", "ZETAC", "WNAC", "ZETAD", "WNAD"],
    ["VDPA1", "DMA1", "VDPA2", "DMA2", "VDPA3", "DMA3"],
    ["VDUA1", "TDUA1", "VDUA2", "TDUA2", "VDUA3", "TDUA3"],
    ["VRUPA", "TRUPA", "RAMPUA"],
    ["VRUPB", "TRUPB", "RAMPUB"],
    ["VRUPC", "TRUPC", "RAMPUC"],
    ["VRUPD", "TRUPD", "RAMPUD"],
    _dll_freq_block("1"),
    _dll_freq_block("2"),
    _dll_freq_block("3"),
    _dll_freq_block("4"),
    ["VLBLK", "VUBLK", "TBLK", "TDELY"],
    ["FCEASE", "FRECON"],
    ["KWASHQ", "TWASHQ"],
    ["TVM", "CMTDELAY", "LFM", "CMTDELAYC", "TFRQ"],
]
PERC1_CON_ORDER = [name for block in PERC1_DYR_LAYOUT for name in block]
assert len(PERC1_CON_ORDER) == 173, f"PERC1 DLL model requires exactly 173 CONs, got {len(PERC1_CON_ORDER)}"
assert len(set(PERC1_CON_ORDER)) == 173, "PERC1_CON_ORDER has a duplicate CON name"

# The subset of CONs worth surfacing in the UI/report - the core
# (undervoltage cease/reconnect + ZIP exponent) plus the most
# commonly hand-tuned secondary settings. Three items per row: the real CON
# mnemonic, a plain-English label (with units) meant to be the PRIMARY visible
# text, and a tooltip string (the CON mnemonic, plus its PSS/E-model alias
# like "Vcease" where one exists) meant to be shown on hover rather than
# inline - engineers who already know "VDPA" can still find it, but "trip
# voltage (pu)" is what should catch the eye first. This is the single source
# of truth for both the advanced editor and the HTML report (see ui/main_window.py,
# preview/perc1_dll.py). `VDUA`/`TDUA` are channel A's own real overvoltage cease
# threshold/delay (see PERC1_FIXED_DEFAULTS's comment) - genuinely part
# of the DLL variant, confirmed against the vendor sample.
PERC1_DISPLAY_FIELDS = [
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
]
PERC1_ZIP_FIELDS = {"NPA", "NQA"}

# The frequency trip/reconnect CONs the model actually uses - the vendor data
# sheet's J+120 to J+129. The "2"/"3"/"4"-suffixed sets (J+130 to J+159) are
# marked "NOT USED" and keep the vendor example's 99 Hz / 999 s values.
UNDERFREQUENCY_TRIP_CONS = ("FUFTP1", "TUFTP1")
OVERFREQUENCY_TRIP_CONS = ("FOFTP1", "TOFTP1")
UNDERFREQUENCY_RECONNECT_CONS = ("FUFRN1", "TUFRN1", "RUFRN1")
OVERFREQUENCY_RECONNECT_CONS = ("FOFRN1", "TOFRN1", "ROFRN1")

def voltage_stage_cons(undervoltage_stages, overvoltage_stages) -> dict:
    """Map exactly 4 (voltage_pu, duration_s) undervoltage stages and 4
    overvoltage stages onto the DLL variant's real Option-3 CON names -
    VDPA/DMA + VDPA1-3/DMA1-3 (undervoltage), VDUA/TDUA + VDUA1-3/TDUA1-3
    (overvoltage). Stage 1 in each list is the same point Option 1's own
    VDPA/DMA or VDUA/TDUA already represents - this function's whole job is
    making sure stages 2-4 agree with it instead of silently carrying
    PERC1_FIXED_DEFAULTS' vendor-sample values, which the compiled DLL
    evaluates unconditionally (see that dict's own comment, and
    docs/developer/PERC1_MODEL.md's "Option 3 is always live" section).

    Every caller that builds a full PERC1 CON dict - PERC1_DEFAULT_CONS below,
    presets/ridethrough.py's preset bundles - should call this rather than
    leaving VDPA1-3/DMA1-3/VDUA1-3/TDUA1-3 at their PERC1_FIXED_DEFAULTS
    values. Passing the same point 4 times (`[(vdpa, dma)] * 4`) is the
    correct, PSS/E-validated choice when there is no real multi-tier data to
    encode (a repeated stage fires at the exact same time as the tier it
    copies - it cannot introduce a different, earlier trip)."""
    if len(undervoltage_stages) != 4:
        raise ValueError(f"expected exactly 4 undervoltage stages, got {len(undervoltage_stages)}")
    if len(overvoltage_stages) != 4:
        raise ValueError(f"expected exactly 4 overvoltage stages, got {len(overvoltage_stages)}")
    cons = {}
    for suffix, (voltage, duration) in zip(("", "1", "2", "3"), undervoltage_stages):
        cons[f"VDPA{suffix}"] = voltage
        cons[f"DMA{suffix}"] = duration
    for suffix, (voltage, duration) in zip(("", "1", "2", "3"), overvoltage_stages):
        cons[f"VDUA{suffix}"] = voltage
        cons[f"TDUA{suffix}"] = duration
    return cons


# UPS/VFD front-end technology -> ZIP exponent (NPA/NQA): 0 = constant power,
# 1 = constant current, 2 = constant impedance. A tightly-regulated front end
# (double-conversion UPS, active front-end VFD) holds its power draw roughly
# constant through a voltage sag until it trips, so it is modeled as constant
# power; an unregulated/direct-online load's current draw is closer to fixed
# impedance, so its power draw falls off with the square of voltage.
ZIP_EXPONENT_MAP = {
    "Double conversion (online)": 0,
    "Eco-mode / line-interactive": 1,
    "Direct-online (no UPS buffering)": 2,
    "Active front-end (regenerative, near-unity PF)": 0,
    "Standard front-end (diode rectifier)": 2,
}

# The model's complete 173-CON default set: PERC1_FIXED_DEFAULTS plus the 10
# core CONs it leaves out - a double-conversion (constant power) block with a
# generic Standard-tier undervoltage trip (0.70 pu, 0.02 s), the full block
# tripping and a staged reconnect - with each stage-1 voltage point repeated
# into stages 2-4.
PERC1_DEFAULT_CONS = {
    **PERC1_FIXED_DEFAULTS,
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
PERC1_DEFAULT_CONS.update(voltage_stage_cons(
    [(PERC1_DEFAULT_CONS["VDPA"], PERC1_DEFAULT_CONS["DMA"])] * 4,
    [(PERC1_DEFAULT_CONS["VDUA"], PERC1_DEFAULT_CONS["TDUA"])] * 4,
))


def frequency_stage_cons(underfrequency_stage, overfrequency_stage, *,
                         reconnect_low_hz, reconnect_high_hz) -> dict:
    """Write one (frequency_hz, delay_s) under-frequency and one over-frequency
    trip point into FUFTP1/TUFTP1 and FOFTP1/TOFTP1 - the only frequency trip
    CONs the vendor model uses (J+120 to J+129; the stage-2-4 sets are "NOT
    USED"). Reconnect frequency is the continuous band's edge
    (`reconnect_low_hz`/`reconnect_high_hz`), so a tripped block reconnects once
    frequency is back inside the band it must ride through indefinitely;
    reconnect delay/ramp keep the vendor example's values, since no standard in
    this library publishes frequency reconnect timing."""
    (uf_hz, uf_delay), (of_hz, of_delay) = underfrequency_stage, overfrequency_stage
    return {
        "FUFTP1": uf_hz, "TUFTP1": uf_delay, "FUFRN1": reconnect_low_hz,
        "FOFTP1": of_hz, "TOFTP1": of_delay, "FOFRN1": reconnect_high_hz,
    }
