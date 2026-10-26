"""Ride-through envelope geometry: a preset's step table as plot segments and points, and the bound at a
duration. Pure functions, shared by the charts, the black-box scoring and the validation checks."""

from __future__ import annotations

# Panel 3 ("Trip threshold vs. ride-through envelope") plots only the selected
# preset's own two-sided tolerance region - not ITIC/CBEMA (a 1970s equipment
# power-quality curve, not a bulk-power-system reliability standard; see
# docs/user/presets/README.md).
# ENVELOPE_TMIN/TMAX are just a generic time-axis anchor for building segment
# geometry (the actual plotted range is auto-scaled per preset - see
# `build_perc1_response_figure`'s panel3_xmax); TMAX is deliberately generous
# since points beyond the visible range are simply never drawn.
ENVELOPE_TMIN, ENVELOPE_TMAX = 0.001, 1000.0


# --- Ride-through envelope geometry (one preset's undervoltage floor + overvoltage
# ceiling - panel 3 draws only these, auto-scaled) ---
#
# A ride-through envelope (a RideThroughPreset's `envelope` or `overvoltage_envelope`,
# see presets/ridethrough.py) describes a step shape: as duration increases, the
# tolerance required of the facility gets stricter (undervoltage floor rises toward
# nominal; overvoltage ceiling falls toward nominal). These helpers convert the
# dataclass's step-table representation into (t0, t1, voltage) segments / plot points.


def envelope_segments_from_steps(steps, t_min=ENVELOPE_TMIN, t_max=ENVELOPE_TMAX):
    """Undervoltage side: convert a list of RideThroughStep objects (ascending
    voltage_pu, each exposing .voltage_pu/.min_duration_s) into (t0, t1, voltage)
    segments - voltage v is the required floor for [t0, t1)."""
    finite = [s for s in steps if s.min_duration_s is not None]
    segments = []
    t_prev, v_prev = t_min, 0.0
    for step in finite:
        segments.append((t_prev, step.min_duration_s, v_prev))
        t_prev, v_prev = step.min_duration_s, step.voltage_pu
    segments.append((t_prev, t_max, v_prev))
    return segments


def overvoltage_segments_from_steps(steps, t_min=ENVELOPE_TMIN, t_max=ENVELOPE_TMAX):
    """Overvoltage side: the mirror image of envelope_segments_from_steps. `steps` uses
    the same RideThroughStep convention and ascending voltage_pu order, but read as
    'up to voltage_pu must be tolerated for at least min_duration_s' - the short-
    duration tiers get the HIGHEST ceiling, stepping DOWN as duration grows, settling
    on the continuous-operation ceiling (the step with min_duration_s=None) forever.
    If `steps` has no continuous (None) entry, the lowest listed voltage is used as
    that forever-ceiling instead."""
    finite = sorted((s for s in steps if s.min_duration_s is not None), key=lambda s: -s.voltage_pu)
    none_steps = [s for s in steps if s.min_duration_s is None]
    if none_steps:
        continuous_ceiling = min(s.voltage_pu for s in none_steps)
    elif steps:
        continuous_ceiling = min(s.voltage_pu for s in steps)
    else:
        continuous_ceiling = 1.10
    segments = []
    t_prev = t_min
    for step in finite:
        segments.append((t_prev, step.min_duration_s, step.voltage_pu))
        t_prev = step.min_duration_s
    segments.append((t_prev, t_max, continuous_ceiling))
    return segments


def segments_to_points(segments):
    """(t0, t1, v) segments -> a doubled-corner point list so the curve renders with
    plain linear interpolation (a flat step, not a diagonal ramp, between corners)."""
    points = []
    for t0, t1, v in segments:
        points.append((t0, v))
        points.append((t1, v))
    return points


def envelope_bound(segments, t):
    """The envelope's required voltage bound at duration t (a floor for undervoltage
    segments, a ceiling for overvoltage segments - same walk-forward logic either way,
    since both are (t0, t1, v) triples ordered by increasing t0)."""
    result = segments[0][2]
    for t0, t1, v in segments:
        if t0 <= t:
            result = v
        else:
            break
    return result
