import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev.validation.case_model import (
    FacilityInfo,
    LoadComposition,
    case_from_model_defaults,
    case_from_preset,
)
from psse.runner import MockPsseRunner


@pytest.fixture(autouse=True)
def no_modal_message_boxes(monkeypatch):
    """A modal QMessageBox would wait forever for a click in an offscreen test: questions are answered Yes and
    warnings are dismissed. Tests that care about the answer patch `MainWindow._confirm` themselves."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:  # pragma: no cover - Qt is a hard dependency
        return
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))


@pytest.fixture(autouse=True)
def delete_windows_after_each_test():
    """Closed windows are only hidden; their web views keep running. Deleting them after each test keeps one
    long test session from slowing down window by window."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture
def example_model(monkeypatch):
    """Registers tests/fixtures/example_load_model.py's non-PERC1 model for
    one test only, so the built-in registry stays untouched."""
    from fixtures.example_load_model import MODEL

    import load_models

    monkeypatch.setitem(load_models.LOAD_MODELS, MODEL.id, MODEL)
    return MODEL


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def tmp_output_dir(tmp_path):
    return str(tmp_path / "output")


@pytest.fixture
def mock_runner():
    return MockPsseRunner()


def _sample_facility():
    return FacilityInfo(
        name="Test Data Center", bus_number=101, bus_name="BUS_101",
        use_case="AI Training", use_case_pct=100, total_mw=300.0, power_factor=0.99,
    )


def _sample_load_composition():
    return LoadComposition(pct_it=70.0, pct_cooling_vfd=20.0, pct_cooling_motor=5.0, pct_other=5.0)


@pytest.fixture
def sample_case_preset():
    def _make(preset_id="ercot_nogrr282", **kwargs):
        return case_from_preset(
            preset_id, facility=_sample_facility(), load_composition=_sample_load_composition(), **kwargs
        )

    return _make


@pytest.fixture
def sample_case_defaults():
    """A case whose it block is the PERC1 DLL at its own default CONs (source "defaults", no preset)."""
    def _make(model_id="perc1_dll"):
        return case_from_model_defaults(
            model_id, facility=_sample_facility(), load_composition=_sample_load_composition()
        )

    return _make


@pytest.fixture
def fake_psse_install(tmp_path):
    """A folder laid out like a PSS/E install whose psspy is tests/fixtures/fake_psse, for the running Python."""
    import shutil
    import sys

    from blackbox.psse_install import PsseSelection

    root = tmp_path / "PSSE35" / "35.6"
    (root / "PSSBIN").mkdir(parents=True)
    (root / "PSSLIB").mkdir()
    pspy = root / f"PSSPY{sys.version_info.major}{sys.version_info.minor}"
    shutil.copytree(Path(__file__).parent / "fixtures" / "fake_psse", pspy, ignore=shutil.ignore_patterns("__pycache__"))
    (pspy / "version.txt").write_text("35.6.4")
    return PsseSelection("35.6", str(root), sys.executable, pspy.name)


# The tests never read or write the developer's real app settings (the saved PSS/E selection, the run folder, ...): on a
# machine where the app has been set up, a saved selection would turn "PSS/E is not configured" tests into real PSS/E runs.
# Set at import, before any test module is collected, because some skip conditions are evaluated at collection.
_TEST_APP_DATA = tempfile.mkdtemp(prefix="perc-studio-test-appdata-")
os.environ["APPDATA"] = _TEST_APP_DATA
os.environ["LOCALAPPDATA"] = _TEST_APP_DATA
