# `sweep`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > sweep

The batch entry point: generate, export, run, validate and report for every `(preset, scenario)` pair in a
[sweep spec](../formats.md#sweep-spec), in one call. Reach for this when doing a real validation campaign.

```bash
perc-studio sweep spec.json --runner mock --output-dir output/my_run
```

| Option | Meaning |
|---|---|
| `SPEC_FILE` | JSON or YAML spec |
| `--runner mock\|psse` | Overrides the spec's own `runner` |
| `--output-dir DIR` | Default `output/<sweep_id>-<UTC timestamp>/` |
| `--dry-run` | Check the spec and list the cases it would run; run nothing, write nothing |

Exit **0** if every case passed, **5** if any failed (`data.summary` has the full per-case breakdown either way),
**2** for a spec problem (unknown preset id, bad block, unreadable file), **4** if `psse` is requested without a
selection.

## Check before you run

```bash
$ perc-studio sweep spec.json --dry-run | jq '.data | {total_cases, runner, block}'
{ "total_cases": 4, "runner": "mock", "block": "it" }
```

`--dry-run` resolves the spec's presets and scenarios and returns every `{preset_id, scenario}` pair in `data.cases`.
A typo in a preset id fails here, in under a second, rather than after the first long PSS/E case.

## Reading the result

```bash
perc-studio sweep spec.json --output-dir out/run1 > sweep.json; echo "exit $?"
jq '.data.summary | {total_cases, passed_cases, failed_cases, all_passed}' sweep.json
```

Everything is also on disk in the [output tree](../formats.md#sweep-output-tree); open
`out/run1/reports/summary.html` for the table, or the per-scenario HTML for the plot. Re-print a finished run with
[`report sweep`](run_validate_report.md#report-sweep).

## Examples

The checked-in spec `tests/fixtures/sweep_example.json` sweeps two presets over a short sag and a short ride-through
probe:

```bash
perc-studio sweep tests/fixtures/sweep_example.json --output-dir output/demo
```

Generate the scenarios instead of writing them, and sweep a different model:

```bash
perc-studio scenario suite --preset-id spp_hill --out suite.json
jq -n --slurpfile s suite.json \
  '{sweep_id:"spp_suite", presets:["spp_hill"], scenarios:$s[0], runner:"mock", block:"it", model:"perc1_standard"}' > spec.json
perc-studio sweep spec.json --dry-run
perc-studio sweep spec.json --output-dir output/spp_suite
```

A YAML spec works the same way:

```yaml
sweep_id: yaml_example
presets: [ercot_nogrr282, pjm_lcl]
scenarios:
  - {id: sag_50, fault_start_s: 0.5, fault_duration_s: 1.0, fault_voltage_pu: 0.5}
runner: mock
block: it
```

A sweep covers the `it` or `vfd` block over presets. To vary individual CONs instead, loop `params generate --source
overrides` with `run` and `validate results` (see the [cookbook](../cookbook.md#sweep-one-con)).
