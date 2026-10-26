# Walkthrough

[perc-studio](../README.md) > Walkthrough

One case from generation to a plotted verdict, then the same thing in bulk.

```bash
# 1. Generate a case from a preset
perc-studio params generate --source preset --preset-id ercot_nogrr282 --out case.json

# 2. Look at what it holds, and prove it is schema-valid
perc-studio params show case.json --human
perc-studio params validate case.json

# 3. Export its IT block to a real .dyr file
perc-studio export dyr case.json --block it --out it.dyr

# 4. Run it through the mock runner against a sag that reaches stage 1's own dwell
#    (VDPA=0.90 pu / DMA=2.00 s for this preset)
perc-studio run case.json --fault-duration-s 2.0 --fault-voltage-pu 0.75 --runner mock --out result.json
# -> data.result.tripped: true

# 5. Validate that against ERCOT NOGRR282's own envelope
perc-studio validate results --case case.json --result result.json --preset-id ercot_nogrr282
# -> exit 0, data.report.all_passed: true (the mock's stage-based simulation and the envelope agree
#    that a 2.0 s / 0.75 pu sag should trip)

# 6. Render the plotted report
perc-studio report case --case case.json --result result.json --preset-id ercot_nogrr282 --out report.html
```

Step 5's `expected_reason` states which envelope tier applied:

```
Undervoltage: ERCOT (NOGRR282)'s envelope requires riding through down to 0.80 pu for a 1.00s event.
The scenario sags to 0.50 pu, which is below that floor, so a trip is permitted.
```

## Make the scenario a file

The same run with a reusable scenario, and a second, frequency event:

```bash
perc-studio scenario make --voltage-pu 0.75 --duration-s 2.0 --id sag_75 --out sag_75.json
perc-studio run case.json --scenario sag_75.json --out result_sag.json
perc-studio scenario make --frequency-hz 58.5 --duration-s 310 --out freq.json
perc-studio params generate --source preset --preset-id pjm_lcl --out pjm.json
perc-studio run pjm.json --scenario freq.json --out result_freq.json
perc-studio validate results --case pjm.json --result result_freq.json
```

## The same thing in bulk

`tests/fixtures/sweep_example.json` sweeps `ercot_nogrr282` and `spp_hill` against a 0.6 s / 0.75 pu sag and a
0.6 s / 0.85 pu ride-through probe:

```bash
perc-studio sweep tests/fixtures/sweep_example.json --dry-run          # 4 cases, nothing run
perc-studio sweep tests/fixtures/sweep_example.json --output-dir output/demo
```

This exits **0** (`passed_cases: 4, failed_cases: 0`). The 0.85 pu probe rides through at both presets; the 0.75 pu sag
trips at both, because it is below the 0.80 pu / 0.50 s tier they publish and the mock's stage-2 timer completes
inside 0.6 s. Why that used to exit 5 is in [Background](background.md). Open `output/demo/reports/summary.html` for
the table; the layout of the rest is in the [output tree](formats.md#sweep-output-tree).

## Where next

- Another model: add `--model perc2_standard` to `params generate` ([models](commands/models.md)).
- A file you were given: [`dyr to-case`](commands/dyr.md).
- Real PSS/E instead of the mock: [Runners](runners.md#selecting-psse).
- More recipes: the [cookbook](cookbook.md).
