"""Repository documentation stays consistent with the repository.

`test_user_docs.py` guards the pages that ship. This module guards everything else: every relative link in a
tracked Markdown file must resolve, and every repo path a document names (`utils/scripts/generate_envelope_figures.py`,
`src/dev/cli/`, ...) must exist. `validation/` is listed so a leftover mention of the unpublished
validation library fails here. Moving or renaming a file without updating the documents fails here.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Generated output, not hand-written documentation.
GENERATED = re.compile(r"(^|/)(raw|results|worker_logs|work)/|(^|/)library[^/]*/(results|raw)/")
# Release notes describe the repository as it was when each entry was written.
HISTORICAL = {"CHANGELOG.md"}

TOP_LEVEL = ("src", "utils", "tests", "validation", "docs", "packaging", "assets")
NOT_PATHS: set[str] = set()  # repo-path look-alikes that are not paths, such as a git branch name
# A plan or note may name files that are not in the repository yet (or only on one machine); it says so once, in a
# comment such as `<!-- not-in-repo: utils/scripts/new_figure.py -->`, and the test skips those paths.
NOT_IN_REPO = re.compile(r"<!--\s*not-in-repo:\s*(.*?)\s*-->", re.DOTALL)
LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?\)")
PATH = re.compile(r"(?<![\w/.\-])((?:" + "|".join(TOP_LEVEL) + r")/[\w.\-/*<>{}]*[\w\-/*>}])")


def _tracked_markdown():
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return sorted(p for p in out.splitlines() if p and not GENERATED.search(p))


DOCS = _tracked_markdown() if (ROOT / ".git").exists() else []


def _prose(text):
    """The text with fenced code blocks kept (commands name paths) but link targets removed."""
    return LINK.sub("]()", text)


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_resolve(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    broken = []
    for target in LINK.findall(text):
        if re.match(r"[a-z][a-z0-9+.\-]*:", target):  # http:, https:, mailto:
            continue
        if not (ROOT / doc).parent.joinpath(target).resolve().exists():
            broken.append(target)
    assert not broken, f"{doc} links to missing files: {broken}"


@pytest.mark.parametrize("doc", [d for d in DOCS if d not in HISTORICAL])
def test_named_repo_paths_exist(doc):
    raw = (ROOT / doc).read_text(encoding="utf-8")
    declared = {p.strip().rstrip("/") for m in NOT_IN_REPO.findall(raw) for p in m.split(",") if p.strip()}
    text = _prose(NOT_IN_REPO.sub("", raw))
    missing = []
    for path in PATH.findall(text):
        if path in NOT_PATHS or any(mark in path for mark in ("*", "<", "...", "{")):
            continue
        if path.rstrip("/") in declared:
            continue
        # A sentence can end in a path, and a path can be a directory prefix such as `docs/user/`.
        if not (ROOT / path.rstrip("/")).exists():
            missing.append(path)
    assert not missing, f"{doc} names paths that do not exist: {sorted(set(missing))}"


def test_library_yaml_paths_exist():
    text = (ROOT / "docs" / "user" / "library.yaml").read_text(encoding="utf-8")
    missing = [p for p in re.findall(r"path:\s*([^\s},]+)", text) if not (ROOT / "docs" / "user" / p).resolve().exists()]
    assert not missing, f"docs/user/library.yaml lists missing pages: {missing}"
