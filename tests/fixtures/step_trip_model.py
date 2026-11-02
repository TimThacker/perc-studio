"""The test-only step-trip model, importable as `load_models.step_trip`.

Its package lives in tests/fixtures/extra_models/step_trip/, laid out like a built-in model (the same files, names and
`..base` imports), so adding that folder to `load_models.__path__` is all it takes to import it the way the app imports
a built-in one. It is never in the app's registry: tests register it with the `example_model` fixture
(tests/conftest.py). docs/developer/ADDING_A_LOAD_MODEL.md shows these files as its worked example.
"""

import importlib
import pathlib

import load_models

EXTRA_MODELS_DIR = pathlib.Path(__file__).parent / "extra_models"
PACKAGE_DIR = EXTRA_MODELS_DIR / "step_trip"

if str(EXTRA_MODELS_DIR) not in load_models.__path__:
    load_models.__path__.append(str(EXTRA_MODELS_DIR))

MODEL = importlib.import_module("load_models.step_trip").MODEL
