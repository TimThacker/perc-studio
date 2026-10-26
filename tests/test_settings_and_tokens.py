"""User settings (a small JSON file under LOCALAPPDATA) and the design tokens."""

import re
from pathlib import Path

import pytest

from app import settings
from app import tokens as t


@pytest.fixture
def appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_settings_round_trip(appdata):
    assert settings.load() == {}
    settings.set_value(settings.LAST_DYR_DIR, "C:/models")
    settings.set_run_root(appdata / "runs")
    assert settings.get(settings.LAST_DYR_DIR) == "C:/models"
    assert settings.run_root() == appdata / "runs"
    assert settings.settings_path() == appdata / "perc-studio" / "settings.json"


def test_the_default_run_root_is_under_localappdata(appdata):
    assert settings.run_root() == appdata / "perc-studio" / "blackbox"


def test_settings_from_before_1_2_0_move_to_the_new_folder(appdata):
    old = appdata / "perc1-param-app"
    (old / "blackbox").mkdir(parents=True)
    (old / "settings.json").write_text('{"last_dyr_dir": "C:/models"}', encoding="utf-8")
    assert settings.get(settings.LAST_DYR_DIR) == "C:/models"
    assert settings.settings_path() == appdata / "perc-studio" / "settings.json"
    assert (appdata / "perc-studio" / "blackbox").is_dir() and not old.exists()


def test_a_corrupt_file_counts_as_empty(appdata):
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert settings.load() == {}
    assert settings.run_root() == settings.default_run_root()
    settings.set_value(settings.LAST_TAB, "post")  # and it can be written again
    assert settings.get(settings.LAST_TAB) == "post"


def test_the_overlay_and_baselines_are_never_stored(appdata):
    for key in ("tolerance.overlay", "edit.baseline"):
        with pytest.raises(ValueError):
            settings.set_value(key, "ercot_nogrr282")
    assert not settings.settings_path().exists()


def test_every_colour_token_parses():
    colors = t.colors()
    assert len(colors) > 30
    for name, value in colors.items():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), name
        t.hex_to_rgb(value)


def test_sizes_are_positive():
    for name in ("RADIUS_CARD", "RADIUS_CONTROL", "GUTTER", "FIELD_GAP", "SECTION_GAP", "APP_BAR_HEIGHT",
                 "CONTROL_HEIGHT", "CONTROL_HEIGHT_SMALL", "LEFT_PANEL_MIN"):
        assert getattr(t, name) > 0
    assert t.LEFT_PANEL_MIN < t.LEFT_PANEL_MAX


@pytest.mark.parametrize(("fg", "bg", "minimum"), [
    (t.TEXT, t.SURFACE, 4.5), (t.TEXT_MUTED, t.SURFACE, 4.5), (t.TEXT_MUTED, t.GROUND, 4.5),
    (t.BRAND_TEXT, t.SURFACE, 4.5), (t.BRAND_DARK, t.BRAND_TINT, 4.5), (t.EDITED_TEXT, t.EDITED_TINT, 4.5),
    (t.TRIP_TEXT, t.TRIP_TINT, 4.5), (t.WARNING_TEXT, t.WARNING_BG, 4.5), ("#FFFFFF", t.BRAND, 4.5),
    ("#FFFFFF", t.TRIP, 4.5), (t.PARTNER_BLUE, t.SURFACE, 4.5), (t.TRIP, t.TRIP_BANNER, 4.5),
    (t.TEXT, t.STATE_CEASED, 4.5), (t.TEXT, t.STATE_RECONNECTING, 4.5), (t.TEXT, t.STATE_ONLINE, 4.5),
])
def test_text_colour_pairs_meet_wcag_contrast(fg, bg, minimum):
    assert t.contrast_ratio(fg, bg) >= minimum


def test_no_stray_hex_colours_in_the_new_ui_modules():
    """The redesign's modules take every colour from tokens."""
    src = Path(__file__).resolve().parents[1] / "src"
    for name in ("ui/shell.py", "ui/components.py", "ui/block.py", "preview/page.py", "ui/theme.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert not re.findall(r"#[0-9A-Fa-f]{6}\b", text), name
