# `scenario`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > scenario

Write [fault scenario](../formats.md#fault-scenario) JSON files instead of hand-typing them. The files feed
`run --scenario` and a sweep spec's `scenarios` list.

## `scenario make`

One scenario. Pass exactly one of `--voltage-pu` or `--frequency-hz`, plus `--duration-s`.

| Option | Default | Meaning |
|---|---|---|
| `--voltage-pu V` | | Voltage during the event; below 1.0 is a sag, above 1.0 a swell |
| `--frequency-hz F` | | Frequency during the event (voltage stays nominal) |
| `--duration-s S` | required | Event length |
| `--start-s S` | `0.5` | Event start (the mock runner ignores it) |
| `--id`, `--description` | id derived from the event | e.g. `sag_0.5pu_1s`, `swell_1.15pu_2s`, `freq_58.5hz_310s` |
| `--out FILE` | | Write the JSON here |

```bash
perc-studio scenario make --voltage-pu 0.5 --duration-s 1.0 --out sag.json
perc-studio scenario make --voltage-pu 1.15 --duration-s 2 --id swell_a --out swell.json
perc-studio scenario make --frequency-hz 58.5 --duration-s 310 --out under_freq.json

perc-studio run case.json --scenario sag.json
```

## `scenario suite`

Scenarios that probe a preset's own undervoltage envelope. For each *timed* tier (continuous tiers have no duration
to probe) it writes two scenarios 0.02 pu below the tier's voltage: a `short_` one held for half the tier's duration
and a `long_` one held for 1.5x it. The expected outcome is not encoded in the scenario - `validate results` derives
it from the preset - so a suite is a set of questions, not answers.

| Option | Default | Meaning |
|---|---|---|
| `--preset-id ID` | required | Preset to probe |
| `--max-duration-s S` | `30` | Drop probes longer than this |
| `--start-s S` | `0.5` | |
| `--out FILE` | | Write the scenarios as a JSON list |

```bash
$ perc-studio scenario suite --preset-id ercot_nogrr282 --out suite.json | jq -r '.data.scenarios[].id'
short_0.18pu_0.075s
long_0.18pu_0.225s
short_0.48pu_0.125s
long_0.48pu_0.375s
short_0.78pu_0.25s
long_0.78pu_0.75s
short_0.88pu_1s
long_0.88pu_3s
```

The list drops straight into a sweep spec - see the [cookbook](../cookbook.md#probe-a-preset-at-every-tier).
