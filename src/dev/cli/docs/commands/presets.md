# `presets`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > presets

The ride-through presets: generic profiles and grid-operator tables. Each carries an undervoltage envelope, an
overvoltage envelope and, for some, a frequency table. `params generate --source preset`, `sweep` and
`validate results` all take a preset id. Human-readable descriptions are in
[docs/user/presets/](../../../../../docs/user/presets/README.md).

## `presets list`

```bash
$ perc-studio presets list
$ perc-studio presets list --category "Grid operator standard"
$ perc-studio presets list --with-frequency
```

`--category` is `Generic` or `Grid operator standard`; `--with-frequency` keeps only presets that publish a frequency
ride-through table (`pjm_lcl`, `nerc_prc029`). Each entry has `id`, `label`, `category`, `status`
(`Adopted (PUCT-approved)`, `Proposed`, `Draft`, ...), `short_source` and `has_frequency_table`.

```bash
perc-studio presets list | jq -r '.data.presets[] | "\(.id)\t\(.status)"'
```

## `presets show PRESET_ID`

The full record: `citation`, `undervoltage_envelope` and `overvoltage_envelope` (lists of
`{voltage_pu, min_duration_s}`; `null` duration means continuous), `overcurrent_pu`, `recovery` and
`frequency_ride_through` (or `null`).

```bash
perc-studio presets show ercot_nogrr282 --pretty
perc-studio presets show pjm_lcl | jq '.data.frequency_ride_through.underfrequency'
```

`--model MODEL_ID` (with `--block it|vfd`) adds `data.cons`: the exact CON bundle that model encodes the preset as,
the same values `params generate` would write.

```bash
perc-studio presets show spp_hill --model perc1_dll --block vfd | jq '.data.cons | {VDPA, DMA, VDUA, TDUA}'
```

An unknown preset or model exits 2; a model without a `cons_for_preset` hook (`clod`) also exits 2.
