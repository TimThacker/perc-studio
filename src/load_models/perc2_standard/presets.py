"""Ride-through presets for the PERC2 standard model.

PERC2 has the checks a preset needs: a 4-point long low-voltage table, a 4-point long high-voltage table, a momentary
check each way and a frequency cease each way. The CONs are taken from the preset's own PERC1 DLL bundle (`it_bundle` /
`vfd_bundle`), so all three PERC models assume the same facility physics, with what PSS/E 36.7.1 measured
shaping the mapping:

- Long-cease point 3 never ceases with its own time (it waits TVLC1/TVHC1), so it is switched off (VLC3 = 0,
  VHC3 = 99) and the bundle's distinct stages go on points 1, 2 and 4. A fourth distinct undervoltage stage goes on
  the momentary check, whose reconnect settings are then made identical to the long ones.
- The reconnect window is VLrecon < Vtf < VHrecon, compared strictly on a filtered voltage that approaches the
  post-event value from below. VLrecon is raised to the highest undervoltage cease threshold (a sag between them would
  cease, reconnect inside the sag and cease again: the cycling of validation finding 7) and capped at
  RECONNECT_VOLTAGE_CEILING; VHrecon is the bundle's VRUPA, lowered to the lowest overvoltage threshold for the same
  reason, and VHcease is never below it (PSS/E caps VHrecon at VHcease even with the momentary high check off).
- A frequency cease in PERC2 never reconnects; the bundle's frequency trip points are used as they are and
  `preset_gaps` says that the reconnect after them is lost.
"""

from __future__ import annotations

import math

from ..common import preset_bundle
from .cons import DEFAULT_CONS

HZ_NOMINAL = 60.0
RECONNECT_VOLTAGE_CEILING = 0.95
OFF_LOW, OFF_HIGH = 0.0, 99.0  # thresholds a filtered voltage never crosses


def _stages(bundle, pairs, *, high):
    """The bundle's distinct (voltage, time) stages, most lenient threshold first: for undervoltage the highest
    voltage, for overvoltage the lowest. A stage another stage dominates (same voltage, longer time) is dropped."""
    seen = {}
    for v_key, t_key in pairs:
        v, t = round(float(bundle[v_key]), 6), round(float(bundle[t_key]), 6)
        seen[v] = min(t, seen.get(v, math.inf))
    return sorted(seen.items(), key=lambda s: s[0], reverse=not high)


UV_PAIRS = (("VDPA", "DMA"), ("VDPA1", "DMA1"), ("VDPA2", "DMA2"), ("VDPA3", "DMA3"))
OV_PAIRS = (("VDUA", "TDUA"), ("VDUA1", "TDUA1"), ("VDUA2", "TDUA2"), ("VDUA3", "TDUA3"))


def _fill_points(cons, prefix, stages, off):
    """Points 1, 2 and 4 of a long table from up to 3 stages (padded with the last one); point 3 off."""
    padded = list(stages) + [stages[-1]] * (3 - len(stages))
    for i, (v, t) in zip((1, 2, 4), padded):
        cons[f"V{prefix}C{i}"], cons[f"TV{prefix}C{i}"] = v, t
    cons[f"V{prefix}C3"], cons[f"TV{prefix}C3"] = off, 0.0


def cons_for_preset(preset, block_name: str) -> dict:
    """Every flag and CON, encoding `preset`'s ride-through for the `it` or `vfd` block (see the module docstring)."""
    b = preset_bundle(preset, block_name)
    cons = dict(DEFAULT_CONS)
    ld = float(b["LFM"])
    uv = _stages(b, UV_PAIRS, high=False)
    ov = _stages(b, OV_PAIRS, high=True)

    trecon, tramp = float(b["TDRA"]), float(b["RAMPA"]) / ld  # TrampUsed = Tramp x Ldfact
    cons.update({
        "Ldfact": ld, "fcease": float(b["FCEASE"]), "frecon": float(b["FRECON"]),
        "nP": float(b["NPA"]), "nQ": float(b["NQA"]),
        "Ipmax": float(b["IPMAXA"]), "Ipmin": float(b["IPMINA"]), "Iqmax": float(b["IQMAXA"]), "Iqmin": float(b["IQMINA"]),
        "Tt": float(b["TRA"]), "Tv": float(b["TVM"]), "Tf": float(b["TFRQ"]),
        # The DLL's droop is dP/P0 = DROOPA x df_pu; this model's is dP/MVA = Kdroop x df_pu with MVA = P0 / Ldfact.
        "Kdroop": float(b["DROOPA"]) * ld,
        "dbfl": -float(b["DBA"]) / HZ_NOMINAL, "dbfh": float(b["DBA"]) / HZ_NOMINAL,
        "Tdelay": float(b.get("CMTDELAY", 0.0)),
        "Trecon": trecon, "Tramp": tramp, "TLreconL": trecon, "TLrampL": tramp,
        "TLreconH": float(b["TRUPA"]), "TLrampH": float(b["RAMPUA"]) / ld,
    })
    # Total current: never below what full active plus full reactive current needs, so Imax does not bind by itself.
    cons["Imax"] = round(math.sqrt(cons["Ipmax"] ** 2 + max(cons["Iqmax"], -cons["Iqmin"]) ** 2) + 0.005, 3)

    # undervoltage: long points 1, 2, 4 (+ the momentary check for a fourth stage)
    long_uv, momentary_uv = (uv[:3], uv[3]) if len(uv) > 3 else (uv, None)
    _fill_points(cons, "L", long_uv, OFF_LOW)
    cons["VLLflag"] = 1
    if momentary_uv is not None:
        cons["VLMflag"], cons["VLcease"], cons["Tcease"] = 1, momentary_uv[0], momentary_uv[1]
    else:
        cons["VLMflag"], cons["VLcease"], cons["Tcease"] = 0, uv[-1][0], uv[-1][1]
    # overvoltage: long points 1, 2, 4 (+ the momentary check for a fourth stage, which no bundle has)
    long_ov, momentary_ov = (ov[:3], ov[3]) if len(ov) > 3 else (ov, None)
    _fill_points(cons, "H", long_ov, OFF_HIGH)
    cons["VLHflag"] = 1

    # the reconnect window
    highest_uv = max(v for v, _t in uv)
    lowest_ov = min(v for v, _t in ov)
    cons["VLrecon"] = max(min(float(b["VRPA"]), RECONNECT_VOLTAGE_CEILING), highest_uv, cons["VLcease"])
    cons["VHrecon"] = min(float(b["VRUPA"]), lowest_ov)
    if momentary_ov is not None:
        cons["VHMflag"], cons["VHcease"] = 1, momentary_ov[0]
    else:
        cons["VHMflag"], cons["VHcease"] = 0, max(cons["VHrecon"], max(v for v, _t in ov))

    # frequency: the bundle's trip points (a preset's own table where it has one); the cease is permanent in PERC2
    cons.update({"FLflag": 1, "FLC1": float(b["FUFTP1"]), "TFLC1": float(b["TUFTP1"]),
                 "FHflag": 1, "FHC1": float(b["FOFTP1"]), "TFHC1": float(b["TOFTP1"])})
    if cons["fcease"] <= 0:
        for flag in ("VLMflag", "VHMflag", "VLLflag", "VLHflag", "FLflag", "FHflag"):
            cons[flag] = 0
    return cons


def preset_gaps(preset) -> list[str]:
    """What the preset (or its PERC1 DLL bundle) specifies that PERC2 cannot represent as it is."""
    gaps = []
    b = preset.it_bundle
    uv = _stages(b, UV_PAIRS, high=False)
    if len(uv) > 4:
        gaps.append(f"{len(uv)} undervoltage stages reduced to 4")
    gaps.append("a frequency cease never reconnects in PERC2 (the PERC1 DLL bundle reconnects after "
                f"{float(b['TUFRN1']):g} s / {float(b['TOFRN1']):g} s); the trip points themselves are kept")
    if float(b["VRPA"]) > RECONNECT_VOLTAGE_CEILING:
        gaps.append(f"reconnect voltage {float(b['VRPA']):g} pu lowered to {RECONNECT_VOLTAGE_CEILING:g} pu (PERC2 needs "
                    "the filtered voltage strictly above it, so a 1.0 pu recovery would never reconnect)")
    return gaps
