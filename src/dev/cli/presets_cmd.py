"""`perc-studio presets list|show` - browse the ride-through presets (the ERCOT/SPP/PJM/MISO/NERC tables and the
generic profiles) that `params generate --source preset` and `sweep` encode into CONs."""

from __future__ import annotations

import click

from load_models import get_load_model
from presets.ridethrough import (
    PRESET_CATEGORY_ORDER,
    RIDE_THROUGH_PRESETS,
    RideThroughPreset,
)

from ._output import UsageError, cli_result, pretty_option


def _steps(envelope) -> list[dict]:
    return [{"voltage_pu": s.voltage_pu, "min_duration_s": s.min_duration_s} for s in envelope]


def _frequency(table) -> dict | None:
    if table is None:
        return None
    return {
        "continuous_low_hz": table.continuous_low_hz,
        "continuous_high_hz": table.continuous_high_hz,
        "underfrequency": [{"limit_hz": b.limit_hz, "min_duration_s": b.min_duration_s} for b in table.underfrequency],
        "overfrequency": [{"limit_hz": b.limit_hz, "min_duration_s": b.min_duration_s} for b in table.overfrequency],
        "source": table.source,
    }


def _summary(preset: RideThroughPreset) -> dict:
    return {
        "id": preset.id,
        "label": preset.label,
        "category": preset.category,
        "status": preset.status,
        "short_source": preset.short_source,
        "has_frequency_table": preset.frequency_ride_through is not None,
    }


def _preset(preset_id: str) -> RideThroughPreset:
    try:
        return RIDE_THROUGH_PRESETS[preset_id]
    except KeyError:
        raise UsageError(f"unknown preset id {preset_id!r}; valid ids: {sorted(RIDE_THROUGH_PRESETS)}") from None


@click.group("presets")
def presets_group():
    """Browse the ride-through presets (see docs/user/presets/)."""


@presets_group.command("list")
@click.option("--category", type=click.Choice(PRESET_CATEGORY_ORDER), default=None,
              help="Only presets in this category.")
@click.option("--with-frequency", is_flag=True, default=False,
              help="Only presets that publish a frequency ride-through table.")
@pretty_option
def list_presets(category, with_frequency, pretty):
    """Every preset id `params generate --preset-id` accepts."""
    with cli_result("presets list", pretty) as result:
        presets = [
            p for p in RIDE_THROUGH_PRESETS.values()
            if (category is None or p.category == category)
            and (not with_frequency or p.frequency_ride_through is not None)
        ]
        result["data"] = {"presets": [_summary(p) for p in presets]}


@presets_group.command("show")
@click.argument("preset_id")
@click.option("--model", "model_id", default=None, metavar="MODEL_ID",
              help="Also include the CONs this load model encodes the preset as (see `models list`).")
@click.option("--block", type=click.Choice(["it", "vfd"]), default="it",
              help="Which block's CON bundle --model returns.")
@pretty_option
def show_preset(preset_id, model_id, block, pretty):
    """One preset's envelope tables, citation, and optionally its CON bundle."""
    with cli_result("presets show", pretty) as result:
        preset = _preset(preset_id)
        data = {
            **_summary(preset),
            "citation": preset.citation,
            "overcurrent_pu": preset.overcurrent_pu,
            "recovery": preset.recovery,
            "undervoltage_envelope": _steps(preset.envelope),
            "overvoltage_envelope": _steps(preset.overvoltage_envelope),
            "frequency_ride_through": _frequency(preset.frequency_ride_through),
        }
        if model_id:
            try:
                model = get_load_model(model_id)
            except KeyError as exc:
                raise UsageError(exc.args[0]) from exc
            if not model.supports_presets:
                raise UsageError(f"load model {model_id!r} has no cons_for_preset hook, so it cannot encode a preset")
            data["model_id"] = model_id
            data["block"] = block
            data["cons"] = dict(model.cons_for_preset(preset, block))
        result["data"] = data
