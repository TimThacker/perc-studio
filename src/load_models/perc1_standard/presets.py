"""Ride-through presets for the PERC1 standard model.

The standard model has ONE undervoltage cease/reconnect cycle and nothing
else: no overvoltage trip, no frequency trip, no multi-stage table, no
momentary cessation (data sheet notes 13-14; confirmed in PSS/E 36.7.1 - a
1.2 pu swell and 57/63 Hz excursions change nothing). A preset's envelope is
therefore reduced to the same single point the DLL variant's Option 1 uses,
and `preset_gaps` says what that leaves out so callers can show it.
"""

from __future__ import annotations

from ..common import preset_bundle
from .cons import DEFAULT_CONS

HZ_NOMINAL = 60.0
# Vtf must be strictly above Vrecon, and a recovering filtered voltage approaches its final value from below: with
# Vrecon = 1.0 and a post-fault voltage of 1.0 pu the ramp never starts (measured in PSS/E 36.7.1).
RECONNECT_VOLTAGE_CEILING = 0.95


def cons_for_preset(preset, block_name: str) -> dict:
    """CONs that give `preset` the single-point undervoltage behavior it asks for.

    Cease: Vcease/Tcease are the envelope's shallowest mandatory point
    (`collapsed_point`, the same rule as the DLL variant's VDPA/DMA).
    Reconnect, exponents, current limits and droop come from the preset's own
    resolved recovery values (read from its `it_bundle`/`vfd_bundle`, where the
    app keeps them) so both variants assume the same facility physics. Tdelay
    is always 0 (PSS/E 36.7.1 hazard, see cons.TDELAY_HAZARD), and Vrecon is
    capped at RECONNECT_VOLTAGE_CEILING (a preset's 1.00 pu would strand the
    load at a post-fault voltage of 1.0 pu)."""
    bundle = preset_bundle(preset, block_name, "PERC1 ")
    from presets.ridethrough import (
        collapsed_point,  # lazy: ridethrough_presets imports load_models at import time
    )

    point = collapsed_point(preset.envelope)
    cons = dict(DEFAULT_CONS)
    ldfact = float(bundle["LFM"])
    cons.update({
        "Ldfact": ldfact,
        "Vcease": point.voltage_pu,
        "Tcease": point.min_duration_s if point.min_duration_s is not None else 0.0,
        "Tdelay": 0.0,
        "fcease": float(bundle["FCEASE"]),
        "Vrecon": max(min(float(bundle["VRPA"]), RECONNECT_VOLTAGE_CEILING), point.voltage_pu),
        "Trecon": float(bundle["TDRA"]),
        "Tramp": float(bundle["RAMPA"]),
        "frecon": float(bundle["FRECON"]),
        "nP": float(bundle["NPA"]),
        "nQ": float(bundle["NQA"]),
        "Ipmax": float(bundle["IPMAXA"]),
        "Ipmin": float(bundle["IPMINA"]),
        "Iqmax": float(bundle["IQMAXA"]),
        "Iqmin": float(bundle["IQMINA"]),
        "Tt": float(bundle["TRA"]),
        "Tv": float(bundle["TVM"]),
        "Tf": float(bundle["TFRQ"]),
        # The DLL's droop is dP/P0 = DROOPA * df_pu; this model's is dP/MVA = Kdroop * df_pu with MVA = P0/Ldfact.
        "Kdroop": float(bundle["DROOPA"]) * ldfact,
        "dbfl": -float(bundle["DBA"]) / HZ_NOMINAL,
        "dbfh": float(bundle["DBA"]) / HZ_NOMINAL,
    })
    if point.min_duration_s is None:
        cons["fcease"] = 0.0  # a continuous-operation point never ceases
    return cons


def preset_gaps(preset) -> list[str]:
    """What the preset specifies that the standard model cannot represent."""
    gaps = []
    stages = [s for s in preset.envelope if s.min_duration_s is not None]
    if len(stages) > 1:
        gaps.append(f"{len(stages)}-step undervoltage envelope reduced to its single shallowest mandatory step "
                    "(the model has one cease/reconnect cycle, no multi-stage table)")
    if any(s.min_duration_s is not None for s in preset.overvoltage_envelope):
        gaps.append("overvoltage ride-through is not modelled (no overvoltage cease)")
    if preset.frequency_ride_through is not None:
        gaps.append("frequency ride-through is not modelled (no frequency cease; only droop responds to frequency)")
    return gaps
