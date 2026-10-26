# `dyr`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > dyr

Read an existing PSS/E `.dyr` file - the CLI side of the app's Import .dyr. It recognizes PERC1 DLL, PERC2 DLL v2.3
(179-CON header, both write `PERCBL`), PERC1 standard, PERC2 standard and CLOD records, in any mix and any scope
(`PERCBL`/`OW`/`ZN`/`AR`/`AL`). CLOD records are listed but cannot be inspected.

An import never rejects a value for being out of range - inspecting a questionable model is the point. Out-of-range
CONs, placeholder first fields (`IBUS`) and other notes come back in the envelope's `warnings`.

## `dyr list FILE`

```bash
$ perc-studio dyr list model.dyr --pretty
```

`data.records` numbers each record (`record`) in file order with `model_id`, `scope`, `number`, `load_id`,
`inspectable`, `error` and a readable `label`. Use the number as `--record` below.

## `dyr show FILE [--record N]`

One record's `cons` (and `extras`: for the standard models the component, description and load fraction). `--record`
may be omitted when the file holds exactly one record; otherwise it is a usage error that lists the choices.

```bash
perc-studio dyr show model.dyr --record 0 | jq '.data.cons | {VDPA, DMA}'
perc-studio dyr show model.dyr --record 0 | jq -r '.warnings[]'
```

## `dyr to-case FILE [--record N]`

Builds a `LoadCase` with the record's CONs in one block, so everything else in the CLI applies to a model you were
handed as a file: schema-check it, export it again, run it, validate it against a preset, diff it against a
generated case.

| Option | Default | Meaning |
|---|---|---|
| `--block it\|vfd\|motor` | `it` | Block the record fills |
| `--facility-name`, `--bus-name`, `--total-mw` | `Imported .dyr`, `DC_POI`, `300` | Facility data (a `.dyr` has none) |
| `--bus-number` | the record's own bus | |
| `--case-id`, `--out FILE` | generated | |

The block's `source` is `defaults` and every imported CON is listed in its `overrides`. A `.dyr` carries no facility
split, so the case's load composition is 100% IT whichever block you fill.

```bash
perc-studio dyr to-case vendor.dyr --record 0 --out vendor_case.json
perc-studio validate results --case vendor_case.json --result r.json --preset-id ercot_nogrr282
perc-studio params diff vendor_case.json preset_case.json --block it
```

Round trip check - export a case, import it, and confirm nothing changed:

```bash
perc-studio export dyr case.json --block it --out it.dyr
perc-studio dyr to-case it.dyr --out reimported.json
perc-studio params diff case.json reimported.json --block it | jq '.data.identical'   # true
```
