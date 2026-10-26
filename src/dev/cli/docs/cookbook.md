# Cookbook

[perc-studio](../README.md) > Cookbook

Worked examples, one per task. Commands are shown for a POSIX shell (`jq` for JSON); on PowerShell, the same commands
work and `ConvertFrom-Json` replaces `jq`. Every example uses only commands documented in the
[command pages](../README.md#command-map).

- [Find out what is available](#find-out-what-is-available)
- [Generate and inspect cases](#generate-and-inspect-cases)
- [Sweep one CON](#sweep-one-con)
- [Probe a preset at every tier](#probe-a-preset-at-every-tier)
- [Judge an existing `.dyr`](#judge-an-existing-dyr)
- [Compare presets and models](#compare-presets-and-models)
- [Produce the files you hand over](#produce-the-files-you-hand-over)
- [Run a campaign](#run-a-campaign)
- [Black-box validate a model](#black-box-validate-a-model)
- [Use it from CI](#use-it-from-ci)

## Find out what is available

```bash
perc-studio info --pretty                                      # version, models, presets, PSS/E environment
perc-studio models list | jq -r '.data.models[] | "\(.id)\t\(.con_count) CONs"'
perc-studio presets list | jq -r '.data.presets[] | "\(.id)\t\(.status)"'
perc-studio presets show nerc_prc029 | jq '.data.frequency_ride_through'
perc-studio models show perc1_dll | jq '.data.default_cons | {VDPA, DMA, VDUA, TDUA}'
```

## Generate and inspect cases

```bash
# the ERCOT NOGRR282 tier table, encoded as PERC1 DLL CONs
perc-studio params generate --source preset --preset-id ercot_nogrr282 --out ercot.json
perc-studio params validate ercot.json
perc-studio params show ercot.json --human

# only the IT block's CONs
perc-studio params show ercot.json --block it | jq '.data.block.cons | {VDPA, DMA, VDPA1, DMA1}'

# a 1 GW site on a different bus, no motor block
perc-studio params generate --source preset --preset-id spp_hill --total-mw 1000 --bus-number 9001 \
    --bus-name HYPERSCALE --no-include-motor --pct-motor 0 --pct-other 10 --pct-it 70 --pct-vfd 20 --out site.json
```

## Sweep one CON

`sweep` varies the preset; to vary a single CON, loop `overrides` and judge each run against the preset the case came
from:

```bash
perc-studio params generate --source preset --preset-id ercot_nogrr282 --out base.json
for v in 0.60 0.70 0.80 0.90; do
  perc-studio params generate --source overrides --base-case base.json --override it.VDPA=$v --out case_$v.json > /dev/null
  perc-studio run case_$v.json --fault-duration-s 3.0 --fault-voltage-pu 0.75 --out result_$v.json > /dev/null
  perc-studio validate results --case case_$v.json --result result_$v.json > verdict_$v.json
  code=$?
  echo "VDPA=$v exit=$code tripped=$(jq .data.report.points[0].actual_trip verdict_$v.json)"
done
```

Confirm each variant differs from the base only where you meant it to:

```bash
perc-studio params diff base.json case_0.60.json | jq '.data.blocks[0].changed'
# { "VDPA": { "a": 0.9, "b": 0.6 } }
```

## Probe a preset at every tier

`scenario suite` writes a short and a long event under each timed tier of the preset's undervoltage envelope; the sweep
runs them and `validate` works out which should trip.

```bash
perc-studio scenario suite --preset-id ercot_nogrr282 --out suite.json
jq -n --slurpfile s suite.json \
  '{sweep_id:"ercot_tiers", presets:["ercot_nogrr282"], scenarios:$s[0], runner:"mock", block:"it"}' > tiers.json
perc-studio sweep tiers.json --dry-run | jq '.data.total_cases'        # 8
perc-studio sweep tiers.json --output-dir output/ercot_tiers
echo "exit $?"                                                       # 0 all agree, 5 some disagree
jq '{total_cases, passed_cases, failed_cases}' output/ercot_tiers/reports/summary.json
```

The same spec with the PSS/E runner (`--runner psse`, after [selecting PSS/E](runners.md#selecting-psse)) tests the
real DLL instead of the mock.

## Judge an existing `.dyr`

You were handed a vendor file. List it, load a record, and test it against a preset.

```bash
perc-studio dyr list vendor.dyr | jq -r '.data.records[] | "\(.record)\t\(.label)"'
perc-studio dyr show vendor.dyr --record 0 | jq -r '.warnings[]'          # out-of-range CONs, placeholders
perc-studio dyr to-case vendor.dyr --record 0 --out vendor.json

perc-studio run vendor.json --fault-duration-s 1.0 --fault-voltage-pu 0.5 --out vendor_result.json
perc-studio validate results --case vendor.json --result vendor_result.json --preset-id pjm_lcl
perc-studio report case --case vendor.json --result vendor_result.json --preset-id pjm_lcl --out vendor_report.html
```

How far is it from what a preset would write?

```bash
perc-studio params generate --source preset --preset-id pjm_lcl --out pjm.json
perc-studio params diff vendor.json pjm.json --block it | jq '.data.changed_cons'
```

## Compare presets and models

```bash
# three presets side by side, one fault
for p in ercot_nogrr282 spp_hill pjm_lcl; do
  perc-studio params generate --source preset --preset-id $p --out $p.json > /dev/null
  perc-studio run $p.json --fault-duration-s 0.6 --fault-voltage-pu 0.75 --out $p.result.json > /dev/null
  echo "$p tripped=$(jq .tripped $p.result.json)"
done

# the same preset on every model that can encode one and be mock-run
for m in perc1_dll perc2_dll perc1_standard perc2_standard; do
  perc-studio params generate --source preset --preset-id ercot_nogrr282 --model $m --out $m.json > /dev/null
  perc-studio run $m.json --fault-duration-s 3.0 --fault-voltage-pu 0.5 --out $m.result.json > /dev/null
  echo "$m tripped=$(jq .tripped $m.result.json) at $(jq .trip_time_s $m.result.json) s"
done
```

## Produce the files you hand over

```bash
perc-studio export facility ercot.json --out facility.dyr       # header comments, MW per block - what the app writes
perc-studio export report ercot.json --out ercot_report.html    # parameters and expected-response plots
perc-studio export dyr ercot.json --block it --scope owner --subsystem-number 12 --load-id DC --out it_owner12.dyr
```

Round-trip check - the exported file reads back to the same CONs:

```bash
perc-studio export dyr ercot.json --block it --out it.dyr
perc-studio dyr to-case it.dyr --out it_back.json
perc-studio params diff ercot.json it_back.json --block it | jq '.data.identical'     # true
```

## Run a campaign

```bash
perc-studio sweep tests/fixtures/sweep_example.json --dry-run | jq '.data.total_cases'
perc-studio sweep tests/fixtures/sweep_example.json --output-dir output/campaign
echo "exit $?"
perc-studio report sweep --output-dir output/campaign | jq '.data.summary | {passed_cases, failed_cases}'
```

## Black-box validate a model

```bash
perc-studio info | jq .data.psse_environment                         # what the environment already names
perc-studio psse check --psse-version 35.6
perc-studio dll inspect model.dll --psse-root "C:/Program Files/PTI/PSSE35/35.6" --model PERCBL
perc-studio blackbox --psse-version 35.6 --dyr model.dyr --list
perc-studio blackbox --psse-version 35.6 --dyr model.dyr --dll model.dll --load 1 --level quick \
    --preset ercot_nogrr282 --out output/bbv
echo "exit $?"                                                     # 5 if the validation stopped early

perc-studio results show output/bbv | jq '.data | {overall, compared}'
perc-studio results cases output/bbv/bundle.zip | jq -r '.data.cases[] | "\(.key)\t\(.label)\t\(.verdict)"' | head
perc-studio results plot output/bbv/bundle.zip --case <key> --case <key> --channel V --channel P --out compare.html
```

## Use it from CI

```bash
#!/usr/bin/env bash
set -u
perc-studio sweep specs/regression.json --output-dir out/regression > out/sweep.json
code=$?
jq '.data.summary | {total_cases, failed_cases}' out/sweep.json
case $code in
  0) ;;                                             # every case behaved as its preset requires
  5) echo "validation mismatch - see out/regression/reports/summary.html"; exit 1 ;;
  *) jq -r '.errors[]' out/sweep.json; exit "$code" ;;
esac
```

See the [output contract](output_contract.md) for the exit codes and the Click-level errors that are not JSON.
