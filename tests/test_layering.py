"""The src/ packages import in one direction only (see "Package layering" in docs/developer/ARCHITECTURE.md).

Module-level imports are held to the table below. Imports inside a function are the documented lazy exceptions (a
cycle broken on purpose, or the black-box and CLI features reaching each other); they are not checked, but nothing in the
desktop app may import `dev` at all, because the installer does not bundle it.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# package -> the packages it may import at module level (a package may always import itself)
ALLOWED = {
    "app": set(),
    "load_models": set(),
    "presets": {"load_models"},
    "editor": {"load_models"},
    "preview": {"app", "editor", "load_models", "presets"},
    "export": {"app", "editor", "load_models", "preview"},
    "psse": {"load_models"},
    "blackbox": {"app", "presets", "psse"},
    "ui": {"app", "blackbox", "editor", "export", "load_models", "presets", "preview"},
    "dev": {"app", "export", "load_models", "presets", "psse"},
}


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0], node.col_offset
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.col_offset


def test_packages_import_downward_only():
    problems = []
    for package, allowed in ALLOWED.items():
        for path in sorted((SRC / package).rglob("*.py")):
            for target, col in _imports(path):
                if col == 0 and target in ALLOWED and target != package and target not in allowed:
                    problems.append(f"{path.relative_to(SRC).as_posix()} imports {target}")
    assert not problems, "imports against the layering:\n  " + "\n  ".join(problems)


def test_nothing_imports_dev_but_dev():
    """The one exception is the `perc-studio <command>` dispatch in app/launcher.py, inside a function, so the
    desktop app never loads the CLI."""
    problems = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("dev/"):
            continue
        for target, col in _imports(path):
            if target == "dev" and not (rel == "app/launcher.py" and col > 0):
                problems.append(rel)
    assert not problems, f"desktop-app code imports dev: {problems}"


def test_every_package_is_in_the_table():
    packages = {p.name for p in SRC.iterdir() if (p / "__init__.py").exists()}
    assert packages == set(ALLOWED), f"src/ packages and the layering table differ: {packages ^ set(ALLOWED)}"
