# `export`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > export

Write a case out as PSS/E text or as the desktop app's report. All three use the same code as the app, so the output
is what the GUI would produce for the same values.

| Command | Output | Use it for |
|---|---|---|
| [`export dyr`](#export-dyr) | The bare `.dyr` record(s) | Feeding PSS/E or `run`; scripting |
| [`export facility`](#export-facility) | The full facility `.dyr` with header comments | The file you would hand over |
| [`export report`](#export-report) | HTML report | Reviewing the parameterization |

## `export dyr`

```bash
perc-studio export dyr case.json --block it --out it.dyr
perc-studio export dyr case.json --block all --out all.dyr
```

| Option | Meaning |
|---|---|
| `--block it\|vfd\|motor\|all` | Which block (default `it`); `all` writes each block present, separated by comment lines |
| `--scope bus\|owner\|zone\|area\|all` | Record format: `bus` (`PERCBL`, IT=1, default), `owner` (`PERCOW`, IT=2), `zone` (`PERCZN`, IT=3), `area` (`PERCAR`, IT=4), `all` (`PERCAL`, IT=5). CLOD records follow the same scope. |
| `--subsystem-number N` | The owner/zone/area number written in the record's first field (required for those scopes) |
| `--load-id ID` | PSS/E load id for every record, 1-2 characters. Default `1` (it), `2` (vfd), `3` (motor) |
| `--out FILE` | Also write the text here |

The text is always in `data.dyr_text`, so `--out` is optional when you only pipe it onward. See
[PERC1_MODEL.md](../../../../../docs/developer/PERC1_MODEL.md#the-exported-dyr-record) for the record layout.

```bash
# an owner-scoped record for owner 12, load id "DC"
perc-studio export dyr case.json --block it --scope owner --subsystem-number 12 --load-id DC

# an area record without writing a file
perc-studio export dyr case.json --scope area --subsystem-number 3 | jq -r '.data.dyr_text'
```

A load id longer than two characters (PSS/E's `character*2` field) or an owner/zone/area scope without a number
exits 2.

## `export facility`

The complete file the desktop app's Export button writes: header comments (facility, POI bus, total MW, confidence
per block, VERIFY notes), a comment per block with its MW, the records, and any on-site-generation note.

```bash
perc-studio export facility case.json --out facility.dyr
```

A case the desktop UI cannot edit (a block on a model the UI does not offer for that block) exits 2 with the reason.
`export dyr` has no such limit.

## `export report`

The app's HTML report for a case: facility and load split, every block's parameters, the expected response plots
against the preset's envelope, and which standards the block meets.

```bash
perc-studio export report case.json --out case_report.html
```

This is the *parameterization* report. To report a *run* (a simulated response and its verdict), use
[`report case`](run_validate_report.md#report-case).
