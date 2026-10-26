"""Small user settings kept between sessions, as JSON in
`%LOCALAPPDATA%\\perc-studio\\settings.json` (the home folder where LOCALAPPDATA is not set).
The selected PSS/E install is kept separately, in Roaming `%APPDATA%` (`blackbox.psse_install.settings_path`).

Qt-free. Only plain values are stored: the black-box run folder, the last folder a .dyr was
opened from, the window size and the last tab. A tolerance-curve overlay and the edit
baselines are deliberately never stored: each run and each session starts without them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RUN_ROOT = "blackbox.run_root"
LAST_DYR_DIR = "last_dyr_dir"
WINDOW_SIZE = "window.size"
LAST_TAB = "window.last_tab"
KNOWN_KEYS = (RUN_ROOT, LAST_DYR_DIR, WINDOW_SIZE, LAST_TAB)
NEVER_STORED = ("tolerance.overlay", "edit.baseline")
APP_FOLDER = "perc-studio"
OLD_APP_FOLDER = "perc1-param-app"  # the folder name before 1.2.0


def app_folder(base: Path) -> Path:
    """`base`/perc-studio. An install upgraded from before 1.2.0 has `base`/perc1-param-app instead; it is moved
    to the new name the first time, so its settings (and black-box runs) carry over. If the move fails (another
    copy of the app holds a file open), the old folder is used as it is."""
    new, old = base / APP_FOLDER, base / OLD_APP_FOLDER
    if not new.exists() and old.is_dir():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


def app_dir() -> Path:
    return app_folder(Path(os.environ.get("LOCALAPPDATA") or str(Path.home())))


def settings_path() -> Path:
    return app_dir() / "settings.json"


def default_run_root() -> Path:
    return app_dir() / "blackbox"


def load() -> dict:
    """Every stored setting; an unreadable or corrupt file counts as empty."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default=None):
    return load().get(key, default)


def set_value(key: str, value) -> None:
    if key in NEVER_STORED or key.startswith(NEVER_STORED):
        raise ValueError(f"{key!r} is never stored")
    data = load()
    data[key] = value
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass  # settings are a convenience; failing to save one never stops the app


def run_root() -> Path:
    """Where black-box runs go: the chosen folder, else the default under LOCALAPPDATA."""
    chosen = get(RUN_ROOT)
    return Path(chosen) if chosen else default_run_root()


def set_run_root(path) -> None:
    set_value(RUN_ROOT, str(path))
