"""Ride-through presets for the PERC2 DLL v2.3.

v2.3 is the PERC1 DLL with six CONs appended, so a preset's PERC1 DLL bundle (`it_bundle` / `vfd_bundle`) carries over
CON for CON, with what PSS/E measured shaping two changes:

- v2.3 multiplies the voltage reconnect ramps (RAMPA, RAMPUA) by LFM; the PERC1 DLL does not. Those two are divided
  by LFM so a preset reconnects over the same seconds on both DLLs.
- VRPA is capped at RECONNECT_VOLTAGE_CEILING (0.95 pu). The reconnect window is strict on a filtered voltage that
  approaches the post-event voltage from below, so the five presets with VRPA = 1.0 would never reconnect after a
  recovery to 1.0 pu (the PERC1 DLL preset library's finding 1, measured again on v2.3: validation finding 3). The
  PERC2 standard presets use the same ceiling; `preset_gaps` reports the change.
- Momentary cessation stays off (ICON(M+1) = 0), as in every PERC1 DLL preset. The four new momentary-cessation CONs
  get the vendor sample's values, and TAQ = TBQ = 0 bypasses the new reactive lead-lag.
"""

from __future__ import annotations

from ..common import preset_bundle
from ..perc1_dll.cons import PERC1_CON_ORDER
from .cons import DEFAULT_CONS, RAMP_CONS, SAMPLE_EXTRA, effective_lfm

RECONNECT_VOLTAGE_CEILING = 0.95


def cons_for_preset(preset, block_name: str) -> dict:
    """Every ICON and CON, encoding `preset`'s ride-through for the `it` or `vfd` block."""
    b = preset_bundle(preset, block_name)
    cons = dict(DEFAULT_CONS)
    cons.update({"FREQ50": 0, "MCFLAG": 0})
    for n in PERC1_CON_ORDER:
        if n in b:
            cons[n] = b[n]
    cons.update(SAMPLE_EXTRA)
    lfm = effective_lfm(cons)
    for n in RAMP_CONS:
        cons[n] = round(float(cons[n]) / lfm, 6)
    cons["VRPA"] = min(float(cons["VRPA"]), RECONNECT_VOLTAGE_CEILING)
    return cons


def preset_gaps(preset) -> list[str]:
    """What the preset's PERC1 DLL bundle specifies that the v2.3 record carries differently."""
    gaps = []
    vrpa = float(preset.it_bundle["VRPA"])
    if vrpa > RECONNECT_VOLTAGE_CEILING:
        gaps.append(f"reconnect voltage VRPA {vrpa:g} pu lowered to {RECONNECT_VOLTAGE_CEILING:g} pu (the DLL needs the "
                    "filtered voltage strictly above it, so a recovery to 1.0 pu would never reconnect)")
    return gaps


def preset_cases(ids=("standard_itic", "ercot_nogrr282", "pjm_lcl")) -> dict[str, dict]:
    """A few presets' CONs for the PSS/E validation plan (`app_*` cases): one with VRPA below the ceiling, two capped."""
    from presets.ridethrough import RIDE_THROUGH_PRESETS

    return {f"preset_{i}_it": cons_for_preset(RIDE_THROUGH_PRESETS[i], "it") for i in ids}
