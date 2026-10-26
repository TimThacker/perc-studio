"""The PSS/E install the user picked, and the check that proves it works.

The app does not search the disk for PSS/E. The user chooses a version and
the install folder (pre-filled with that version's default path); the Python
that runs `psspy` follows from the folder's `PSSPYxx` subfolder. `check_install`
then starts that Python on `psse_worker.py probe` and reports what PSS/E itself
says: its exact version, the Python version, and whether it could initialize
and solve the rig's power flow.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.settings import app_folder

from . import supervisor

# Versions offered in the tab. Only 64-bit PSS/E 35 and later are supported.
SUPPORTED_VERSIONS: tuple[str, ...] = (
    "35.0", "35.1", "35.2", "35.3", "35.4", "35.5", "35.6",
    "36.0", "36.1", "36.2", "36.3", "36.4", "36.5", "36.6", "36.7",
)
PROBE_TIMEOUT_S = 90.0

_PSSPY_RE = re.compile(r"^PSSPY(\d)(\d+)$", re.IGNORECASE)


def parse_version(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.\d+)?\s*", text or "")
    if not match:
        raise ValueError(f"PSS/E version must look like 35.6, not {text!r}")
    return int(match.group(1)), int(match.group(2))


def default_install_dir(version: str) -> str:
    major, minor = parse_version(version)
    return rf"C:\Program Files\PTI\PSSE{major}\{major}.{minor}"


@dataclass(frozen=True)
class InstallLayout:
    """What the chosen folder holds: PSSBIN, and one PSSPYxx folder per Python version PSS/E supports."""

    folder: str
    has_pssbin: bool
    pspy_folders: tuple[tuple[str, tuple[int, int]], ...]
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def inspect_install(folder: str) -> InstallLayout:
    path = Path(folder)
    problems = []
    if not path.is_dir():
        return InstallLayout(folder, False, (), (f"{folder} is not a folder",))
    has_bin = (path / "PSSBIN").is_dir()
    if not has_bin:
        problems.append(f"no PSSBIN folder in {folder}; choose the version folder, e.g. {default_install_dir('35.6')}")
    pspy = []
    for child in sorted(path.iterdir()):
        match = _PSSPY_RE.match(child.name)
        if child.is_dir() and match:
            pspy.append((child.name, (int(match.group(1)), int(match.group(2)))))
    if not pspy:
        problems.append(f"no PSSPYxx folder in {folder}, so there is no Python interface to use")
    pspy.sort(key=lambda item: item[1], reverse=True)
    return InstallLayout(folder, has_bin, tuple(pspy), tuple(problems))


def python_version(python_exe: str, timeout: float = 30.0) -> tuple[int, int] | None:
    """(major, minor) of an interpreter, or None if it cannot be started."""
    try:
        out = subprocess.run(
            [python_exe, "-I", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=timeout, check=False, creationflags=supervisor.NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        major, minor = out.stdout.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def find_python(version: tuple[int, int]) -> str | None:
    """An interpreter of exactly `version`: the `py` launcher first, then the
    PEP 514 registry entries. This looks up Python, never PSS/E."""
    tag = f"{version[0]}.{version[1]}"
    if shutil.which("py"):
        try:
            out = subprocess.run(["py", f"-{tag}", "-c", "import sys; print(sys.executable)"],
                                 capture_output=True, text=True, timeout=30, check=False, creationflags=supervisor.NO_WINDOW)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    if sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf"Software\Python\PythonCore\{tag}\InstallPath") as key:
                    try:
                        exe = winreg.QueryValueEx(key, "ExecutablePath")[0]
                    except OSError:
                        exe = str(Path(winreg.QueryValueEx(key, "")[0]) / "python.exe")
                if exe and Path(exe).is_file():
                    return exe
            except OSError:
                continue
    return None


@dataclass
class PsseSelection:
    """The user's choice. `pspy_folder` is e.g. "PSSPY311"; empty means the newest one in the folder."""

    version: str
    install_dir: str
    python_exe: str = ""
    pspy_folder: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PsseSelection:
        return cls(d.get("version", ""), d.get("install_dir", ""), d.get("python_exe", ""), d.get("pspy_folder", ""))

    def resolved(self) -> PsseSelection:
        """Fill in the PSSPYxx folder and the Python if the user left them blank."""
        layout = inspect_install(self.install_dir)
        pspy = self.pspy_folder or (layout.pspy_folders[0][0] if layout.pspy_folders else "")
        python = self.python_exe
        if not python and pspy:
            wanted = dict(layout.pspy_folders).get(pspy)
            python = (find_python(wanted) if wanted else None) or ""
        return PsseSelection(self.version, self.install_dir, python, pspy)


@dataclass
class CheckResult:
    ok: bool
    message: str
    selection: PsseSelection
    psse_version: str | None = None
    python_version: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["selection"] = self.selection.to_dict()
        return d


def _fail(selection, message, **details):
    return CheckResult(False, message, selection, details=details)


def check_install(selection: PsseSelection, *, timeout: float = PROBE_TIMEOUT_S) -> CheckResult:
    """Prove the selection works by starting PSS/E with it. Never raises for a
    bad selection; the result says what is wrong."""
    try:
        wanted_version = parse_version(selection.version)
    except ValueError as exc:
        return _fail(selection, str(exc))
    layout = inspect_install(selection.install_dir)
    if not layout.ok:
        return _fail(selection, "; ".join(layout.problems))
    sel = selection.resolved()
    pspy = dict(layout.pspy_folders)
    if sel.pspy_folder not in pspy:
        return _fail(sel, f"{sel.pspy_folder or 'PSSPYxx'} is not in {sel.install_dir}")
    needed = pspy[sel.pspy_folder]
    if not sel.python_exe:
        return _fail(sel, f"{sel.pspy_folder} needs Python {needed[0]}.{needed[1]}, and none was found. "
                          f"Install it or choose its python.exe.")
    found = python_version(sel.python_exe)
    if found is None:
        return _fail(sel, f"could not start {sel.python_exe}")
    if found != needed:
        return _fail(sel, f"{sel.pspy_folder} needs Python {needed[0]}.{needed[1]}, but {sel.python_exe} is "
                          f"Python {found[0]}.{found[1]}")

    work = Path(tempfile.mkdtemp(prefix="bbv_probe_"))
    try:
        script = supervisor.stage_worker(work)
        out_json = work / "probe.json"
        outcome = supervisor.run_process(
            [sel.python_exe, "-I", str(script), "probe", str(out_json), sel.install_dir, sel.pspy_folder],
            cwd=work, timeout_s=timeout,
        )
        if outcome.timed_out:
            return _fail(sel, f"PSS/E did not answer within {timeout:.0f} s (stopped)", stderr=outcome.stderr_tail)
        if not out_json.exists():
            return _fail(sel, "PSS/E's Python exited without a result: " + (outcome.stderr_tail or f"exit code {outcome.returncode}"),
                         stderr=outcome.stderr_tail)
        probe = json.loads(out_json.read_text())
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if not probe.get("ok"):
        return _fail(sel, f"PSS/E failed at {probe.get('stage', 'start-up')}: {probe.get('error', 'unknown error')}",
                     probe=probe)
    v = probe.get("version", {})
    reported = f"{v.get('major')}.{v.get('minor')}" + (f".{v['patch']}" if v.get("patch") is not None else "")
    if (v.get("major"), v.get("minor")) != wanted_version:
        return CheckResult(False, f"this folder holds PSS/E {reported}, not {selection.version}", sel, reported,
                           probe.get("python"), {"probe": probe})
    if probe.get("bits") != 64:
        return CheckResult(False, "this is a 32-bit Python; PSS/E 35 and later need 64-bit", sel, reported,
                           probe.get("python"), {"probe": probe})
    return CheckResult(True, f"PSS/E {reported} with Python {probe.get('python')}: ready", sel, reported,
                       probe.get("python"), {"probe": probe})


def settings_path() -> Path:
    return app_folder(Path(os.environ.get("APPDATA") or str(Path.home()))) / "psse_selection.json"


def load_saved_selection() -> PsseSelection | None:
    try:
        return PsseSelection.from_dict(json.loads(settings_path().read_text()))
    except (OSError, ValueError):
        return None


def save_selection(selection: PsseSelection) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(selection.to_dict(), indent=1))
