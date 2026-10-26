"""`perc-studio scenario make|suite` - write the FaultScenario JSON files `run --scenario` and sweep specs consume,
without hand-writing them. `suite` derives a boundary-probing set from a preset's own envelope."""

from __future__ import annotations

import json
import os

import click

from presets.ridethrough import RIDE_THROUGH_PRESETS
from psse.runner import FaultScenario

from ._output import UsageError, cli_result, pretty_option

# A suite probes each envelope tier just below its voltage: held for half the tier's duration and for 1.5x it. The
# expected outcome is not encoded here - `validate results` works it out from the preset. Continuous tiers have no
# duration to probe.
SHORT_FRACTION = 0.5
LONG_FRACTION = 1.5
VOLTAGE_MARGIN_PU = 0.02


def _write(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


@click.group("scenario")
def scenario_group():
    """Build fault scenarios (voltage or frequency events) as JSON files."""


@scenario_group.command("make")
@click.option("--id", "scenario_id", default=None, help="Scenario id (default: derived from the event).")
@click.option("--voltage-pu", type=float, default=None, help="Voltage during the event (<1 sag, >1 swell).")
@click.option("--frequency-hz", type=float, default=None, help="Frequency during the event (instead of voltage).")
@click.option("--duration-s", type=float, required=True, help="Event duration.")
@click.option("--start-s", type=float, default=0.5, help="Event start time.")
@click.option("--description", default="")
@click.option("--out", type=click.Path(dir_okay=False), default=None, help="Write the scenario JSON here.")
@pretty_option
def make_scenario(scenario_id, voltage_pu, frequency_hz, duration_s, start_s, description, out, pretty):
    """One scenario; pass --voltage-pu or --frequency-hz."""
    with cli_result("scenario make", pretty) as result:
        if (voltage_pu is None) == (frequency_hz is None):
            raise UsageError("pass exactly one of --voltage-pu or --frequency-hz")
        if duration_s <= 0:
            raise UsageError("--duration-s must be positive")
        if frequency_hz is not None:
            default_id = f"freq_{frequency_hz:g}hz_{duration_s:g}s"
            scenario = FaultScenario(scenario_id or default_id, start_s, duration_s, description=description,
                                     fault_frequency_hz=frequency_hz)
        else:
            default_id = f"sag_{voltage_pu:g}pu_{duration_s:g}s" if voltage_pu < 1 else f"swell_{voltage_pu:g}pu_{duration_s:g}s"
            scenario = FaultScenario(scenario_id or default_id, start_s, duration_s, voltage_pu,
                                     description=description)
        if out:
            _write(out, scenario.to_dict())
        result["data"] = {"scenario": scenario.to_dict(), "out": out}


@scenario_group.command("suite")
@click.option("--preset-id", required=True, help="Preset whose undervoltage envelope the scenarios probe.")
@click.option("--start-s", type=float, default=0.5)
@click.option("--max-duration-s", type=float, default=30.0, help="Skip probes longer than this.")
@click.option("--out", type=click.Path(dir_okay=False), default=None,
              help="Write the scenarios as a JSON list (paste it into a sweep spec's \"scenarios\").")
@pretty_option
def suite(preset_id, start_s, max_duration_s, out, pretty):
    """Scenarios just below each timed tier of the preset's envelope: one shorter than the tier's duration, one longer."""
    with cli_result("scenario suite", pretty) as result:
        try:
            preset = RIDE_THROUGH_PRESETS[preset_id]
        except KeyError:
            raise UsageError(f"unknown preset id {preset_id!r}; valid ids: {sorted(RIDE_THROUGH_PRESETS)}") from None
        scenarios = []
        for step in preset.envelope:
            if step.min_duration_s is None or step.voltage_pu <= VOLTAGE_MARGIN_PU:
                continue
            voltage = round(step.voltage_pu - VOLTAGE_MARGIN_PU, 4)
            for label, fraction in (("short", SHORT_FRACTION), ("long", LONG_FRACTION)):
                duration = round(step.min_duration_s * fraction, 4)
                if duration > max_duration_s:
                    continue
                scenarios.append(FaultScenario(
                    f"{label}_{voltage:g}pu_{duration:g}s", start_s, duration, voltage,
                    description=f"{preset_id}: {voltage:g} pu for {duration:g} s, "
                    f"{'shorter' if label == 'short' else 'longer'} than the {step.min_duration_s:g} s tier requires",
                ).to_dict())
        if not scenarios:
            raise UsageError(f"preset {preset_id!r} has no timed undervoltage tier within --max-duration-s")
        if out:
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            _write(out, scenarios)
        result["data"] = {"preset_id": preset_id, "scenarios": scenarios, "out": out}
