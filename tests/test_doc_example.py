"""The worked example in docs/developer/ADDING_A_LOAD_MODEL.md is real code: write its blocks to a package, import it,
and run the package-layout rules and a `.dyr` round trip on it, so the example cannot drift from the rules."""

import ast
import importlib
import pathlib
import re
import sys

import pytest
import test_load_models as layout

import load_models
from load_models.base import RECORD_SCOPES

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "developer" / "ADDING_A_LOAD_MODEL.md"
BLOCK_RE = re.compile(r"```python (step_trip/[\w.]+)\n(.*?)\n```", re.DOTALL)
FILES = ("cons.py", "dyr.py", "simulation.py", "presets.py", "__init__.py")


@pytest.fixture(scope="module")
def sources():
    blocks = dict(BLOCK_RE.findall(DOC.read_text(encoding="utf8")))
    assert set(blocks) == {f"step_trip/{name}" for name in FILES}
    return blocks


@pytest.fixture(scope="module")
def model(sources, tmp_path_factory):
    root = tmp_path_factory.mktemp("doc_example")
    (root / "step_trip").mkdir()
    for name, code in sources.items():
        (root / name).write_text(code + "\n", encoding="utf8")
    load_models.__path__.append(str(root))
    try:
        yield importlib.import_module("load_models.step_trip").MODEL
    finally:
        load_models.__path__.remove(str(root))
        for key in [k for k in sys.modules if k.startswith("load_models.step_trip")]:
            del sys.modules[key]


@pytest.mark.parametrize("name", FILES)
def test_example_files_follow_the_structure_rules(sources, name):
    tree = ast.parse(sources[f"step_trip/{name}"])
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


def test_example_follows_the_package_layout_and_round_trips(model):
    layout.test_builtin_model_follows_the_package_layout(model)
    for scope in RECORD_SCOPES:
        text = model.build_dyr_record(0 if scope == "all" else 7, "1", model.default_cons, scope)
        assert model.parse_dyr_record(text) == {k: float(v) for k, v in model.default_cons.items()}
    assert model.simulate(model.default_cons, 0.5, 0.3)["trips"]
