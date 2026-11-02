"""Ride-through presets for the step-trip model: each preset collapses to its most demanding point per direction."""

from __future__ import annotations


def cons_for_preset(preset, block_name: str) -> dict:
    from presets.ridethrough import (  # lazy: presets import load_models
        collapsed_overvoltage_point,
        collapsed_point,
    )

    under = collapsed_point(preset.envelope)
    over = collapsed_overvoltage_point(preset.overvoltage_envelope)
    return {"VUV": under.voltage_pu, "TUV": under.min_duration_s, "VOV": over.voltage_pu,
            "TOV": over.min_duration_s if over.min_duration_s is not None else 2.0}


def preset_gaps(preset) -> list[str]:
    """What the preset asks for that this model cannot encode: its other envelope points and any reconnect."""
    return ["only the most demanding point per direction is kept; the model never reconnects"]


__all__ = [
    "cons_for_preset",
    "preset_gaps",
]
