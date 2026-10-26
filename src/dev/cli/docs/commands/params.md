# `params`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > params

Create, validate, inspect and compare `LoadCase` parameterizations ([format](../formats.md#loadcase)).

## `params generate`

Builds a `LoadCase` one of three ways, chosen by `--source`:

| `--source` | What it does | Required |
|---|---|---|
| `preset` | Encodes a ride-through preset into the `it`/`vfd` blocks with `--model`'s `cons_for_preset` hook. The entry point for generating many cases. | `--preset-id` |
| `defaults` | One block (`--block`, default `it`) at `--model`'s own default CONs. For a model with no preset support yet. | `--model` |
| `overrides` | Loads an existing case and layers `BLOCK.CON=VALUE` values onto it. The primitive for varying one CON. | `--base-case`, `--override` (repeatable) |

`--model MODEL_ID` (default `perc1_dll`) picks the load model for `preset` and `defaults`; see
[models](models.md).

Facility and load-composition options (used with `preset` and `defaults`; the other sources take facility data from
their own input) all have defaults, so `--source preset --preset-id <id>` alone is a complete invocation:

| Option | Default |
|---|---|
| `--facility-name` | `Example Data Center` |
| `--bus-number`, `--bus-name` | `100001`, `DC_POI` |
| `--use-case`, `--use-case-pct` | `AI Training`, `100` |
| `--total-mw`, `--power-factor` | `300.0`, `0.99` |
| `--pct-it`, `--pct-vfd`, `--pct-motor`, `--pct-other` | `70`, `20`, `5`, `5` (must total 100) |
| `--include-vfd/--no-include-vfd`, `--include-motor/--no-include-motor` | both included |
| `--motor-facility-type`, `--motor-has-lighting` | mixed motors, no lighting (these derive the CLOD block) |
| `--case-id` | `case-<12 hex>` |
| `--out FILE` | also write the case JSON here (it is always in `data.case`) |

```bash
# a preset, defaults for everything else
perc-studio params generate --source preset --preset-id ercot_nogrr282 --out case.json

# a 500 MW campus with no cooling VFD block, on a different bus
perc-studio params generate --source preset --preset-id pjm_lcl --total-mw 500 \
    --pct-it 80 --pct-vfd 0 --pct-motor 10 --pct-other 10 --no-include-vfd \
    --bus-number 7001 --bus-name CAMPUS_A --out campus.json

# the same preset encoded by another model
perc-studio params generate --source preset --preset-id ercot_nogrr282 --model perc2_standard --out std.json

# a model's own defaults in the vfd block
perc-studio params generate --source defaults --model perc1_dll --block vfd --out defaults.json

# vary specific CONs on an existing case (several --override allowed; a typo is a usage error)
perc-studio params generate --source overrides --base-case case.json \
    --override it.VDPA=0.55 --override it.DMA=1.5 --out tighter.json
```

`--override` is `BLOCK.CON=VALUE` where `BLOCK` is `it`, `vfd` or `motor`; integer-looking values stay integers
(NPA/NQA are integer selectors), everything else is a float.

## `params validate`

`params validate CASE` is a schema-level check only - nothing runs: every block's CONs exactly match its model's CON
list, the load split sums to 100%, `schema_version` is recognized. Exit **0** with `data.valid: true`, or **3** with
the problems in `errors`. For behavior, see [validate results](run_validate_report.md#validate-results).

```bash
perc-studio params validate case.json && echo schema ok
```

## `params show`

`params show CASE` returns the full case in `data.case`. Options:

- `--block it|vfd|motor`: return only that block (`data.block`, with its `cons`); a block the case lacks exits 2.
- `--human`: also print a short summary before the JSON envelope.

```bash
$ perc-studio params show case.json --human
case_id: case-12b3e1dcffd0
facility: Example Data Center (bus 100001/DC_POI)
total_mw: 300.0  load split valid: True
it_block: model=perc1_dll source=preset preset_id=ercot_nogrr282
vfd_block: model=perc1_dll source=preset preset_id=ercot_nogrr282
motor_block: model=clod source=archetype preset_id=None
{"ok": true, "command": "params show", ...}

$ perc-studio params show case.json --block it | jq '.data.block.cons.VDPA'
0.9
```

## `params diff`

`params diff CASE_A CASE_B` shows which CONs differ, block by block. It always exits 0; `data.identical` and
`data.changed_cons` give the verdict, and `data.blocks` lists each differing block with `{CON: {"a": ..., "b": ...}}`.
A block present in only one case, or on different models, is reported as such instead of being compared. `--block`
restricts the comparison to one block.

```bash
$ perc-studio params diff ercot.json spp.json --pretty
{
  "ok": true, "command": "params diff",
  "data": {
    "case_a": "case-8ff73182f545", "case_b": "case-adf14196eaa2",
    "identical": false, "changed_cons": 16,
    "blocks": [{"block": "it", "model_id": "perc1_dll",
                "changed": {"DMA2": {"a": 0.25, "b": 0.15}, "IPMAXA": {"a": 1.25, "b": 1.0}, "...": "..."}}]
  }, ...
}
```

Typical uses: confirm an override changed only the CON you meant (`changed` has one key), see how two presets differ,
or compare a vendor `.dyr` ([`dyr to-case`](dyr.md#dyr-to-case-file---record-n)) with a generated case.
