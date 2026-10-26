"""Locate bundled data files (branding, the documentation library) both from
a source checkout and from the frozen PyInstaller build.

From source, the root is the repository root (two levels above this file: `src/app/`). In the
frozen build, PyInstaller unpacks data files under `sys._MEIPASS`, and
`packaging/perc_studio.spec` lays them out with the same relative paths.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)
