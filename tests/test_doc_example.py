"""The worked example in docs/developer/ADDING_A_LOAD_MODEL.md is real code: write its blocks to a package, import it,
and run the same layout and behaviour checks the built-in models get, so the example cannot drift from the rules."""

import ast
import importlib
import pathlib
import re
import sys

import pytest
import test_load_models as layout

import load_models
from presets.ridethrough import RIDE_THROUGH_PRESETS

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "developer" / "ADDING_A_LOAD_MODEL.md"
BLOCK_RE = re.compile(r"```python (step_trip/[\w.]+)\n(.*?)\n```", re.DOTALL)


@pytest.fixture(scope="module")
def sources():
    blocks = {name: code for name, code in BLOCK_RE.findall(DOC.read_text(encoding="utf8"))}
    assert set(blocks) == {f"step_trip/{n}.py" for n in ("cons", "dyr", "simulation", "presets", "__init__")}
    return blocks


@pytest.fixture(scope="module")
def model(sources, tmp_path_factory):
    root = tmp_path_factory.mktemp("doc_example")
    package = root / "step_trip"
    package.mkdir()
    for name, code in sources.items():
        (root / name).write_text(code + "\n", encoding="utf8")
    load_models.__path__.append(str(root))
    try:
        yield importlib.import_module("load_models.step_trip").MODEL
    finally:
        load_models.__path__.remove(str(root))
        for key in [k for k in sys.modules if k.startswith("load_models.step_trip")]:
            del sys.modules[key]


def test_example_files_follow_the_structure_rules(sources):
    for name, code in sources.items():
        tree = ast.parse(code)
        assert ast.get_docstring(tree), name
        last = tree.body[-1]
        assert isinstance(last, ast.Assign) and last.targets[0].id == "__all__", name
        if name != "step_trip/__init__.py":
            listed = sorted(el.value for el in last.value.elts)
            public = sorted(n for n in layout._top_level_names(tree) if not n.startswith("_") and n != "__all__")
            assert listed == public, name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 2:
                assert node.module == "base", f"{name} imports {node.module}"


def test_example_cons_are_ordered(sources):
    names = layout._top_level_names(ast.parse(sources["step_trip/cons.py"]))
    assert names["CON_NAMES"] < names["DEFAULT_CONS"] < names["DISPLAY_FIELDS"]


def test_example_follows_the_package_layout(model):
    layout.test_builtin_model_follows_the_package_layout(model)


def test_example_round_trips_and_trips(model):
    text = model.build_dyr_record(7, "1", model.default_cons)
    assert "'USRLOD' '1' 'STPBL' 12 1 0 4 1 1 0" in text
    assert model.parse_dyr_record(text) == {k: float(v) for k, v in model.default_cons.items()}
    assert model.simulate(model.default_cons, 0.5, 0.3)["trips"]
    assert not model.simulate(model.default_cons, 0.05, 0.9)["trips"]


def test_example_encodes_every_preset(model):
    for preset in RIDE_THROUGH_PRESETS.values():
        assert set(model.cons_for_preset(preset, "it")) == set(model.con_names)
