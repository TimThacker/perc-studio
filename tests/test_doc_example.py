"""The worked example in docs/developer/ADDING_A_LOAD_MODEL.md is the test-only step-trip model
(tests/fixtures/extra_models/step_trip/): the doc's code blocks must equal its files, and the model must follow the
same layout rules and behave the way the built-in models do (record scopes, `.dyr` round trip, simulation, presets)."""

import ast
import pathlib
import re

import pytest
import test_load_models as layout
from fixtures.step_trip_model import MODEL, PACKAGE_DIR

from load_models.base import RECORD_SCOPES
from presets.ridethrough import RIDE_THROUGH_PRESETS

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "developer" / "ADDING_A_LOAD_MODEL.md"
BLOCK_RE = re.compile(r"```python (step_trip/[\w.]+)\n(.*?)\n```", re.DOTALL)
FILES = ("cons.py", "dyr.py", "simulation.py", "presets.py", "__init__.py")


def test_doc_blocks_are_the_fixture_files():
    blocks = dict(BLOCK_RE.findall(DOC.read_text(encoding="utf8")))
    assert set(blocks) == {f"step_trip/{name}" for name in FILES}
    for name in FILES:
        assert blocks[f"step_trip/{name}"] == (PACKAGE_DIR / name).read_text(encoding="utf8").rstrip("\n"), (
            f"{name}: the doc block differs from tests/fixtures/extra_models/step_trip/{name}")


@pytest.mark.parametrize("name", FILES)
def test_example_files_follow_the_structure_rules(name):
    tree = ast.parse((PACKAGE_DIR / name).read_text(encoding="utf8"))
    assert ast.get_docstring(tree), name
    last = tree.body[-1]
    assert isinstance(last, ast.Assign) and last.targets[0].id == "__all__", name
    if name != "__init__.py":
        listed = sorted(el.value for el in last.value.elts)
        public = sorted(n for n in layout._top_level_names(tree) if not n.startswith("_") and n != "__all__")
        assert listed == public, name
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 2:
            assert node.module == "base", f"{name} imports {node.module}"


def test_example_cons_are_ordered():
    names = layout._top_level_names(ast.parse((PACKAGE_DIR / "cons.py").read_text(encoding="utf8")))
    assert names["CON_NAMES"] < names["DEFAULT_CONS"] < names["DISPLAY_FIELDS"]


def test_example_follows_the_package_layout():
    layout.test_builtin_model_follows_the_package_layout(MODEL)


@pytest.mark.parametrize("scope", list(RECORD_SCOPES))
def test_example_writes_and_parses_a_record_for_every_scope(scope, example_model):
    from load_models import find_model_for_dyr

    number = 0 if scope == "all" else 7
    text = MODEL.build_dyr_record(number, "1", MODEL.default_cons, scope)
    suffix = RECORD_SCOPES[scope].suffix
    assert f"{number} 'USRLOD' '1' 'STP{suffix}' 12 {RECORD_SCOPES[scope].it} 0 4 1 1 0 0.7000 0.1000 1.2000 0.5000 /" in text
    assert MODEL.parse_dyr_record(text) == {k: float(v) for k, v in MODEL.default_cons.items()}
    assert find_model_for_dyr(text) is MODEL


def test_example_trips_only_when_the_event_crosses_a_threshold_for_its_delay():
    assert MODEL.simulate(MODEL.default_cons, 0.5, 0.3)["trips"]
    assert not MODEL.simulate(MODEL.default_cons, 0.05, 0.3)["trips"]
    assert not MODEL.simulate(MODEL.default_cons, 0.5, 0.9)["trips"]


def test_example_encodes_every_preset():
    for preset in RIDE_THROUGH_PRESETS.values():
        assert set(MODEL.cons_for_preset(preset, "it")) == set(MODEL.con_names)
