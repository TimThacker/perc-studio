"""The user documentation library (docs/user/) ships with the production
build on its own. Every link and image in it must resolve inside docs/user/
(or be a web link), and it must not point users at development material."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = ROOT / "docs" / "user"
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
PAGES = sorted(USER_DOCS.rglob("*.md"))


def _slug(text: str) -> str:
    kept = "".join(ch for ch in text.strip().lower() if ch.isalnum() or ch in " -_")
    return kept.replace(" ", "-")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(USER_DOCS).as_posix())
def test_links_stay_inside_the_user_library(page):
    text = page.read_text(encoding="utf-8")
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, fragment = target.partition("#")
        resolved = (page.parent / path).resolve() if path else page
        assert resolved.is_file(), f"{page.name}: broken link {target}"
        assert USER_DOCS.resolve() in resolved.parents, f"{page.name}: links outside docs/user: {target}"
        if fragment and resolved.suffix == ".md":
            slugs = {_slug(h) for h in HEADING.findall(resolved.read_text(encoding="utf-8"))}
            assert fragment in slugs, f"{page.name}: no heading for #{fragment} in {resolved.name}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(USER_DOCS).as_posix())
def test_no_development_references(page):
    text = page.read_text(encoding="utf-8")
    for needle in ("psse_validation", "validation/perc", "validation/black_box", "src/", ".py"):
        assert needle not in text, f"{page.name} mentions {needle}"


def test_library_lists_every_page_that_exists():
    library = yaml.safe_load((USER_DOCS / "library.yaml").read_text(encoding="utf-8"))
    listed = {(USER_DOCS / p["path"]).resolve() for g in library["groups"] if not g.get("source_only")
              for p in g["pages"] if "path" in p}
    for path in listed:
        assert path.is_file(), path
    top_level = {p.resolve() for p in USER_DOCS.glob("*.md")}
    assert top_level <= listed, top_level - listed
