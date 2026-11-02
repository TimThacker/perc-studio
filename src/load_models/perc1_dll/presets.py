"""Ride-through presets for the PERC1 DLL.

A preset's `it_bundle` / `vfd_bundle` (presets/ridethrough.py) is already a complete PERC1 DLL CON set, so this
model carries it over unchanged and loses nothing.
"""

from __future__ import annotations


def cons_for_preset(preset, block_name: str) -> dict:
    """Every CON, encoding `preset`'s ride-through for the `it` or `vfd` block."""
    if block_name == "it":
        return dict(preset.it_bundle)
    if block_name == "vfd":
        return dict(preset.vfd_bundle)
    raise ValueError(f"ride-through presets define PERC1 CONs for blocks 'it' and 'vfd', not {block_name!r}")


def preset_gaps(preset) -> list[str]:
    """What the preset specifies that this model cannot encode: nothing, since the bundles are PERC1 DLL CONs."""
    return []
