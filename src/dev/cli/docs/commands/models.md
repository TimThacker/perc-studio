# `models`

[perc-studio](../../README.md) > [Commands](../../README.md#command-map) > models

Inspect the registered load models. Adding one is covered by
[ADDING_A_LOAD_MODEL.md](../../../../../docs/developer/ADDING_A_LOAD_MODEL.md); once registered it appears here and
works with every other command.

## `models list`

```bash
$ perc-studio models list --pretty
```

`data.models` has one entry per model: `id`, `label`, `description`, `dyr_model_name`, `con_count` and
`capabilities`:

| Capability | Meaning |
|---|---|
| `dyr_export` | It can write a `.dyr` record (always true) |
| `dyr_parse` | It can read its own record back (needed by the mock runner, `dyr`) |
| `mock_run` | `run --runner mock` can simulate it |
| `frequency_mock_run` | ...including frequency events |
| `ride_through_presets` | `params generate --source preset` and `sweep` can build it from a preset |
| `custom_result_figure` | Reports use the model's own response plot instead of the generic voltage/power plot |
| `record_scopes` | The `--scope` values `export dyr` accepts for it |

Pick the models that can be swept:

```bash
perc-studio models list | jq -r '.data.models[] | select(.capabilities.ride_through_presets) | .id'
```

## `models show MODEL_ID`

The model's full CON list in `.dyr` order, its defaults and the labelled fields reports show.

```bash
perc-studio models show clod --pretty
perc-studio models show perc1_dll | jq '.data.default_cons.VDPA'
perc-studio models show perc2_standard | jq '.data.con_count'
```

An unknown id exits 2 and lists the registered ids.
