"""Helpers the PERC models share, so each one has a single copy: the preset's CON bundle for a block, a PSS/E flag
test, and the time grid and decimation of the analytic simulators (PSS/E's quarter-cycle step, downsampled for plots)."""

from __future__ import annotations

DT = 1.0 / 240.0  # PSS/E's quarter-cycle time step
OUTPUT_DT = 0.01
MAX_POINTS = 4000


def decimate(rows):
    """Keep about one row per OUTPUT_DT (and at most MAX_POINTS rows), always keeping the last."""
    stride = max(1, round(OUTPUT_DT / DT), int(len(rows) / MAX_POINTS) + 1)
    out = rows[::stride]
    if out[-1][0] != rows[-1][0]:
        out.append(rows[-1])
    return out


def flag_on(cons, name) -> bool:
    """PSS/E enables a check only for a flag of exactly 1 (sheet note 7, confirmed for 2 and -1)."""
    try:
        return round(float(cons[name])) == 1
    except (KeyError, TypeError, ValueError):
        return False


def preset_bundle(preset, block_name, cons_label=""):
    """The preset's CON values for the "it" or "vfd" block (`cons_label` names the model in the error message)."""
    if block_name == "it":
        return preset.it_bundle
    if block_name == "vfd":
        return preset.vfd_bundle
    raise ValueError(f"ride-through presets define {cons_label}CONs for blocks 'it' and 'vfd', not {block_name!r}")
