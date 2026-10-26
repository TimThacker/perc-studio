import sys
from pathlib import Path

from app import resources


def test_resource_root_is_the_repository_from_source():
    assert (resources.resource_root() / "docs" / "user" / "library.yaml").is_file()
    assert (resources.resource_path("assets", "branding", "app_icon.ico")).is_file()


def test_resource_root_is_the_bundle_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.resource_root() == Path(tmp_path)
    assert resources.resource_path("docs", "user") == Path(tmp_path) / "docs" / "user"
