"""`perc-studio models list|show` - inspect the registered load models and which
stages of the generate -> run -> validate loop each one supports."""

from __future__ import annotations

import click

from load_models import LOAD_MODELS, get_load_model

from ._output import UsageError, cli_result, pretty_option


def _summary(model) -> dict:
    return {
        "id": model.id,
        "label": model.label,
        "description": model.description,
        "dyr_model_name": model.dyr_model_name,
        "con_count": len(model.con_names),
        "capabilities": model.capabilities(),
    }


@click.group("models")
def models_group():
    """Inspect the registered load models (see docs/developer/ADDING_A_LOAD_MODEL.md)."""


@models_group.command("list")
@pretty_option
def list_models(pretty):
    with cli_result("models list", pretty) as result:
        result["data"] = {"models": [_summary(model) for model in LOAD_MODELS.values()]}


@models_group.command("show")
@click.argument("model_id")
@pretty_option
def show_model(model_id, pretty):
    """Full CON list and defaults for one model."""
    with cli_result("models show", pretty) as result:
        try:
            model = get_load_model(model_id)
        except KeyError as exc:
            raise UsageError(exc.args[0]) from exc
        result["data"] = {
            **_summary(model),
            "con_names": list(model.con_names),
            "default_cons": dict(model.default_cons),
            "display_fields": [{"con": name, "label": label} for name, label, *_ in model.display_fields],
        }
