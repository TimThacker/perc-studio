"""Registry of the PSS/E dynamic load models this app can store, export, run,
and validate.

Each model lives in its own subpackage and exposes a `MODEL` (a
`base.LoadModel`). To add one, create `load_models/<id>/`, build its
`MODEL`, and add it to `_BUILTIN_MODELS` below - see
docs/developer/ADDING_A_LOAD_MODEL.md. The contract tests in
tests/test_load_models.py then run against it automatically.
"""

from __future__ import annotations

import re

from . import clod, perc1_dll, perc1_standard, perc2_dll, perc2_standard
from .base import LoadModel

_BUILTIN_MODELS = (perc1_dll.MODEL, clod.MODEL, perc1_standard.MODEL, perc2_standard.MODEL, perc2_dll.MODEL)

LOAD_MODELS: dict[str, LoadModel] = {model.id: model for model in _BUILTIN_MODELS}

# The model each facility block uses unless a case says otherwise.
DEFAULT_BLOCK_MODELS = {"it": "perc1_dll", "vfd": "perc1_dll", "motor": "clod"}


def register_load_model(model: LoadModel) -> None:
    """Add a model at runtime (e.g. from a test or plugin). Built-in models
    should be listed in `_BUILTIN_MODELS` instead."""
    if model.id in LOAD_MODELS:
        raise ValueError(f"load model {model.id!r} is already registered")
    LOAD_MODELS[model.id] = model


def get_load_model(model_id: str) -> LoadModel:
    try:
        return LOAD_MODELS[model_id]
    except KeyError:
        raise KeyError(f"unknown load model {model_id!r}; registered models: {sorted(LOAD_MODELS)}") from None


def find_model_for_dyr(dyr_text: str) -> LoadModel:
    """The registered model whose quoted `dyr_model_name` appears in
    `dyr_text` (and, for models that share a name, whose `matches_dyr` says
    the record is its own). Raises ValueError if none or more than one model
    matches - the mock runner needs exactly one record type to know how to
    parse it."""
    matches = [
        model for model in LOAD_MODELS.values()
        if any(re.search(rf"'{re.escape(name)}'", dyr_text)
               for name in (model.dyr_model_name, *model.dyr_model_aliases))
        and (model.matches_dyr is None or model.matches_dyr(dyr_text))
    ]
    if len(matches) != 1:
        found = [m.id for m in matches] or "none"
        raise ValueError(f"expected exactly one registered load model's record in the .dyr text, found {found}")
    return matches[0]


__all__ = [
    "DEFAULT_BLOCK_MODELS",
    "LOAD_MODELS",
    "LoadModel",
    "find_model_for_dyr",
    "get_load_model",
    "register_load_model",
]
