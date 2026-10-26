# `run`, `validate`, `report`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > run / validate / report

The single-case half of the loop: simulate one block against one fault, judge the response against the preset's
envelope, render it. The batch version of all three is [`sweep`](sweep.md).

## `run`

Runs one block's `.dyr` record against a fault scenario through a [runner](../runners.md) and produces a
[`SimulationResult`](../formats.md#simulationresult).

```bash
perc-studio run case.json --fault-duration-s 2.0 --fault-voltage-pu 0.75 --block it --runner mock --out result.json
```

The scenario comes from one of three places:

| Source | Options |
|---|---|
| A voltage event | `--fault-duration-s S --fault-voltage-pu V` (`V` > 1.0 is a swell) |
| A frequency event | `--fault-duration-s S --fault-frequency-hz F` |
| A scenario file | `--scenario FILE` (see [`scenario`](scenario.md)) |

`--fault-start-s` (default 0.5) and `--scenario-id` (default `adhoc_<value>_<duration>s`) refine the ad-hoc forms.

| Option | Meaning |
|---|---|
| `--block it\|vfd\|motor` | Which block to run (default `it`). The mock needs a model with a parser and simulator, so a CLOD `motor` block exits 2. |
| `--runner mock\|psse` | `mock` (default) is always available; `psse` needs a [PSS/E selection](../runners.md#selecting-psse) and exits 4 without one. |
| `--raw-case PATH` | A `.raw` power-flow case, recorded for provenance (the mock never reads it; the PSS/E runner does). |
| `--out FILE` | Write the result JSON here. It is always in `data.result`. |

A frequency event gives the result a `frequency_hz` series and a `trip_type` of `underfrequency`/`overfrequency`;
`validate results` then checks it against the preset's frequency table (only `pjm_lcl` and `nerc_prc029` publish one;
others exit 2).

The result's `metadata.scenario` carries the scenario that produced it, so `validate results` and `report case` need
no second copy.

```bash
# a sag that crosses stage 1, a swell, and an underfrequency event
perc-studio run case.json --fault-duration-s 2.0 --fault-voltage-pu 0.75 --out sag.json
perc-studio run case.json --fault-duration-s 0.5 --fault-voltage-pu 1.25 --out swell.json
perc-studio run case.json --fault-duration-s 310 --fault-frequency-hz 58.5 --out freq.json

# did it trip, and when
perc-studio run case.json --fault-duration-s 2.0 --fault-voltage-pu 0.75 | jq '.data.result | {tripped, trip_time_s, trip_type}'
```

## `validate results`

Behavioral validation: compares one or more results with what the preset's envelope says should have happened.

```bash
perc-studio validate results --case case.json --result sag.json --result swell.json --preset-id ercot_nogrr282
```

- `--result` is repeatable; each result carries its own scenario.
- `--preset-id` defaults to the block's own `preset_id` (a `--source preset` case). It is required for a
  defaults or overrides case, which has no envelope of its own.
- `--block it|vfd` selects the block (default `it`).

Each entry of `data.report.points` has `scenario_id`, `expected_trip`, `expected_reason` (a sentence explaining the
envelope tier that applies), `actual_trip`, `actual_trip_time_s`, `passed` and `notes`. Overvoltage and frequency
events on a model that cannot respond to them come back as "Not modelled", not as failures.

Exit **0** if every scenario matched, **5** if any did not. Exit 5 is a finding, not a tool failure: `ok` is true and
`data.report` is fully populated.

```bash
perc-studio validate results --case case.json --result sag.json > verdict.json
echo "exit $?"
jq -r '.data.report.points[] | "\(.scenario_id)\texpected_trip=\(.expected_trip)\tactual=\(.actual_trip)\t\(if .passed then "PASS" else "FAIL" end)"' verdict.json
```

For schema-only checks with no run, see [`params validate`](params.md#params-validate).

## `report case`

One test point as a self-contained HTML page: the response-versus-envelope plot, a pass/fail banner, the reasoning
behind the expected outcome and the block's CON table.

```bash
perc-studio report case --case case.json --result sag.json --block it --preset-id ercot_nogrr282 --out report.html
```

`--preset-id` defaults to the block's own preset, as for `validate results`. Output: `data.out` and `data.passed`.

## `report sweep`

Re-prints a finished sweep's `reports/summary.json` as `data.summary`. It does not regenerate anything - `sweep`
already writes both `summary.json` and `summary.html`.

```bash
perc-studio report sweep --output-dir output/my_run | jq '.data.summary | {total_cases, passed_cases, failed_cases}'
```
