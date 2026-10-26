# Background: Option 3

[perc-studio](../README.md) > Background

An open engineering question used to be: does the compiled PERC1 DLL always evaluate Option 3's four-stage trip table, even for a facility this app
only ever drives via Option 1? **That question is resolved (2026-09-24): yes, it does**, confirmed by direct PSS/E
v35.6.4 simulation against the real compiled `PERC2_V35.dll`. Write-up:
[PERC1_MODEL.md](../../../../docs/developer/PERC1_MODEL.md#option-3-is-always-live). The raw evidence is in the
PSS/E validation library, which is not published.

That validation ran through a standalone `psspy` script. The app's own runner (`get_runner("psse")`, see
[Runners](runners.md)) now runs the same fixtures on real PSS/E once a selection exists. The two purpose-built `.dyr`
fixtures are checked in as a permanent regression:
[`ercot_nogrr282_vendor_default_stages.dyr`](../../../../tests/fixtures/multistage_trip/ercot_nogrr282_vendor_default_stages.dyr)
and
[`ercot_nogrr282_full_curve_stages.dyr`](../../../../tests/fixtures/multistage_trip/ercot_nogrr282_full_curve_stages.dyr).
`src/dev/validation/checks.py` still operationalizes the question:

- `MULTISTAGE_UNDERVOLTAGE_PROBE`/`MULTISTAGE_OVERVOLTAGE_PROBE` are the two discriminating scenarios.
- `evaluate_multistage_probe(current_results, full_curve_results)` reproduces the decision logic, given the two
  fixtures' results against both probes.
- `tests/test_multistage_trip_regression.py::test_multistage_stages_are_confirmed_live` asserts the confirmed outcome
  (`stages_live is True`). It is skipped unless a PSS/E install is selected (`PERC_STUDIO_PSSE_VERSION`, and
  `PERC_STUDIO_PSSE_DLLS` for the DLL).

## Why the sweep example passes now

`tests/fixtures/sweep_example.json` sweeps `ercot_nogrr282` and `spp_hill` against a 0.6 s / 0.75 pu sag and a
0.6 s / 0.85 pu ride-through probe. It exits 0 (`passed_cases: 4, failed_cases: 0`): 0.85 pu is above the required
floor at 0.6 s so nothing trips, and 0.75 pu is below the 0.80 pu / 0.50 s tier both standards publish, which the
mock's stage-2 dwell timer (`VDPA1=0.80`, `DMA1=0.50`, populated from that same tier) completes inside the 0.6 s
window.

Before 2026-09-24 this sweep exited 5: the exported `.dyr` only drove stage 1 (`VDPA=0.90 pu`, `DMA=2.00 s`, which
had not reached its dwell by 0.6 s) and the mock only evaluated that one stage, so the mock and the envelope
disagreed. That was a real finding about a real gap, and is how the multi-stage behavior was found.
