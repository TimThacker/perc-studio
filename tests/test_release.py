"""What the release build ships: the doc library without the contributor docs, the version (see build_info.py)."""

import pytest

from app import build_info
from app import launcher as gui_launcher


@pytest.fixture
def no_contributor_docs(monkeypatch):
    """The release build bundles docs/user/ and docs/black_box/, not docs/developer/ or the READMEs."""
    from pathlib import Path

    real_is_file = Path.is_file
    docs = Path(__file__).resolve().parents[1] / "docs"
    shipped = (docs / "user", docs / "black_box")

    def is_file(self):
        resolved = self.resolve()
        if not any(root in resolved.parents for root in shipped):
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)


def test_version_is_semver():
    assert build_info.__version__.count(".") == 2


def test_launcher_offers_both_workflows():
    assert gui_launcher._modes() == ["screening", "post-commissioning"]
    assert gui_launcher.build_parser().parse_args(["--mode", "post-commissioning"]).mode == "post-commissioning"


def test_release_doc_library_has_no_developer_group(no_contributor_docs):
    ui = pytest.importorskip("ui.main_window")
    groups = [title for title, _entries in ui.DocumentationPanel._contents()]
    assert "Developers" not in groups
    assert groups[0] == "Using the app"


def test_release_doc_library_lists_only_shipped_pages(no_contributor_docs):
    """Without the contributor docs, every page listed is under docs/user/ or docs/black_box/
    (the documentation the build bundles) or generated in-app, and the black-box guide is listed."""
    from pathlib import Path

    ui = pytest.importorskip("ui.main_window")
    docs = Path(ui.USER_DOCS_DIR).resolve().parent
    groups = dict(ui.DocumentationPanel._contents())
    assert "Black-box validation" in groups
    for entries in groups.values():
        for title, url in entries:
            if url.scheme() == "app":
                continue
            path = Path(url.toLocalFile()).resolve()
            assert path.parent in (docs / "user", docs / "black_box") or docs / "user" in path.parents, title


def test_about_page_shows_version_and_license():
    ui = pytest.importorskip("ui.main_window")
    html = ui._about_html()
    assert build_info.__version__ in html
    assert "MIT License" in html
    assert "not found" not in html
