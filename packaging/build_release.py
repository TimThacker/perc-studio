"""Build the release: a portable ZIP and a per-user installer.

    uv run --group packaging python packaging/build_release.py [--require-signing] [--skip-installer]

Steps (each one stops the build on failure):
  1. Stage a copy of src/ with build_info.py stamped with the build commit.
     The source tree itself is never modified.
  2. PyInstaller (packaging/perc_studio.spec) -> build/dist/PERC Studio/
  3. Copy the license texts into its licenses/ folder.
  4. Leak scan: the bundle holds only the desktop app (no CLI or test module, file or reference).
  5. Sign the app executable (when signing is configured).
  6. Smoke test: the frozen app builds its window, draws a live plot with
     the bundled plotly.js and writes a .dyr and an HTML report.
  7. ZIP -> dist/release/PERC-Studio-<version>-win64.zip
  8. Inno Setup -> dist/release/PERC-Studio-<version>-Setup.exe
     (signed, with its uninstaller, when signing is configured)
  9. dist/release/SHA256SUMS.txt

Code signing (see packaging/README.md) is configured with environment
variables: PERC_STUDIO_SIGN_ARGS holds the signtool arguments that select the
certificate and timestamp server (everything between `signtool sign` and
the file name), and PERC_STUDIO_SIGNTOOL optionally gives signtool.exe's path.
Without PERC_STUDIO_SIGN_ARGS the build is unsigned; --require-signing makes that
an error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"
STAGE_SRC = BUILD / "stage" / "src"
WORK = BUILD / "work"
DIST = BUILD / "dist"
RELEASE = ROOT / "dist" / "release"
APP_NAME = "PERC Studio"
APP_DIR = DIST / APP_NAME

# Code that belongs to a source install, not the desktop app bundle (module-name prefixes): the perc-studio CLI and its
# pipeline, and the tests.
FORBIDDEN_MODULES = ("dev", "tests")
# Development files that must never be bundled (path fragments, lower case).
FORBIDDEN_PATHS = ("psse_validation", "validation/", "dev/cli", "dev/validation", "utils/", "tests/", ".dyr", "raw_data",
                   "adding_a_", "architecture.md")
# Text that must not appear in the shipped documentation and notices.
FORBIDDEN_TEXT = ("psse_validation", "validation/perc", "validation/black_box", "src/",
                  "C:\\Users", "ISO-NE Code")
# Distributions whose license files ship in licenses/.
LICENSED_DISTS = ("PySide6-Essentials", "PySide6-Addons", "shiboken6", "plotly", "narwhals", "packaging",
                  "PyYAML")


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("    $ " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def stage_sources(commit: str) -> str:
    log("Staging src/ for the release build")
    shutil.rmtree(STAGE_SRC.parent, ignore_errors=True)
    shutil.copytree(ROOT / "src", STAGE_SRC, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    info = STAGE_SRC / "app" / "build_info.py"
    text = info.read_text(encoding="utf-8")
    text, n_commit = re.subn(r'^BUILD_COMMIT = ""$', f'BUILD_COMMIT = "{commit}"', text, flags=re.MULTILINE)
    if n_commit != 1:
        sys.exit("build_info.py no longer has the BUILD_COMMIT line this script stamps")
    info.write_text(text, encoding="utf-8")
    version = re.search(r'^__version__ = "([^"]+)"$', text, flags=re.MULTILINE).group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"version {version!r} is not MAJOR.MINOR.PATCH (the Windows version resource needs one)")
    return version


def write_version_file(version: str) -> Path:
    major, minor, patch = (int(p) for p in version.split("."))
    path = WORK / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'CURENT, The University of Tennessee, Knoxville'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'perc-studio'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Tim Thacker; CURENT, The University of Tennessee, Knoxville; and the Tennessee Valley Authority. MIT License.'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def pyinstaller(version_file: Path) -> None:
    log("PyInstaller")
    shutil.rmtree(DIST, ignore_errors=True)
    env = dict(os.environ, PERC_STUDIO_STAGED_SRC=str(STAGE_SRC), PERC_STUDIO_VERSION_FILE=str(version_file))
    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "perc_studio.spec"), "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(WORK)], env=env)


def copy_licenses() -> None:
    log("Copying license texts")
    target = APP_DIR / "licenses"
    target.mkdir(exist_ok=True)
    for src in (PACKAGING / "licenses").glob("*.txt"):
        shutil.copy2(src, target / src.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, target / "Python-LICENSE.txt")
    for dist_name in LICENSED_DISTS:
        dist = importlib.metadata.distribution(dist_name)
        for file in dist.files or []:
            parts = Path(str(file)).parts
            # Only the distribution's own license files (dist-info/...),
            # never a package module that happens to be named "licenses".
            if parts and parts[0].endswith(".dist-info") and (
                    "licenses" in parts or Path(str(file)).name.upper().startswith("LICENSE")):
                src = Path(dist.locate_file(file))
                if src.is_file() and "Commercial" not in src.name:
                    shutil.copy2(src, target / f"{dist_name}-{src.name}")


def leak_scan() -> None:
    log("Leak scan")
    problems = []
    modules = (WORK / "perc_studio" / "bundled_modules.txt")
    if not modules.is_file():
        modules = next(WORK.rglob("bundled_modules.txt"))
    for name in modules.read_text(encoding="utf-8").split():
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN_MODULES):
            problems.append(f"bundled module: {name}")
    for path in APP_DIR.rglob("*"):
        rel = path.relative_to(APP_DIR).as_posix().lower()
        if any(frag in rel for frag in FORBIDDEN_PATHS):
            problems.append(f"bundled file: {rel}")
    internal = APP_DIR / "_internal"
    texts = [*(internal / "docs" / "user").rglob("*.md"), internal / "docs" / "user" / "library.yaml",
             internal / "LICENSE", internal / "THIRD_PARTY_NOTICES.md"]
    for path in texts:
        text = path.read_text(encoding="utf-8")
        if path.name == "library.yaml":
            # The Developers group names documents that exist only in a source
            # checkout; the app hides it when they are absent. Scan the rest.
            text = text.split("  - title: Developers")[0]
        for needle in FORBIDDEN_TEXT:
            if needle in text:
                problems.append(f"{path.relative_to(APP_DIR)} contains {needle!r}")
    # The black-box guide ships too. It may describe the perc-studio CLI and the source layout, but not the
    # unpublished validation library or a local path.
    for path in (internal / "docs" / "black_box").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for needle in ("psse_validation", "validation/perc", "validation/black_box", "C:\\Users"):
            if needle in text:
                problems.append(f"{path.relative_to(APP_DIR)} contains {needle!r}")
    if problems:
        sys.exit("Leak scan failed:\n  " + "\n  ".join(problems))
    print("    clean")


def sign(path: Path) -> bool:
    args = os.environ.get("PERC_STUDIO_SIGN_ARGS")
    if not args:
        return False
    log(f"Signing {path.name}")
    signtool = os.environ.get("PERC_STUDIO_SIGNTOOL", "signtool")
    subprocess.run(f'"{signtool}" sign {args} "{path}"', check=True, shell=True)
    subprocess.run(f'"{signtool}" verify /pa "{path}"', check=True, shell=True)
    return True


def smoke_test() -> None:
    log("Smoke test (frozen app)")
    exe = APP_DIR / f"{APP_NAME}.exe"
    out = WORK / "smoke"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    result = subprocess.run([str(exe), "--smoke-test", str(out)], timeout=180, check=False)
    if result.returncode != 0:
        sys.exit(f"smoke test failed (exit code {result.returncode})")
    for name in ("smoke.dyr", "smoke_report.html"):
        if not (out / name).is_file() or (out / name).stat().st_size < 1000:
            sys.exit(f"smoke test did not write {name}")
    print("    passed")


def make_zip(version: str) -> Path:
    log("ZIP")
    RELEASE.mkdir(parents=True, exist_ok=True)
    path = RELEASE / f"PERC-Studio-{version}-win64.zip"
    top = f"{APP_NAME} {version}"
    readme = (PACKAGING / "zip_extras" / "README.txt").read_text(encoding="utf-8").replace("{version}", version)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in sorted(APP_DIR.rglob("*")):
            if file.is_file():
                zf.write(file, f"{top}/{file.relative_to(APP_DIR).as_posix()}")
        zf.write(PACKAGING / "zip_extras" / "Create Desktop Shortcut.cmd", f"{top}/Create Desktop Shortcut.cmd")
        zf.writestr(f"{top}/README.txt", readme.replace("\r\n", "\n").replace("\n", "\r\n"))
    return path


def find_iscc() -> Path | None:
    candidates = [shutil.which("ISCC"),
                  Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe"]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def make_installer(version: str, signing: bool) -> Path:
    log("Installer (Inno Setup)")
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) not found - install it (see packaging/README.md) or pass --skip-installer")
    cmd = [str(iscc), "/Q", f"/DAppVersion={version}", f"/DSourceDir={APP_DIR}", f"/DOutputDir={RELEASE}"]
    if signing:
        signtool = os.environ.get("PERC_STUDIO_SIGNTOOL", "signtool")
        cmd += ["/DSign", f'/Ssigntool="{signtool}" sign {os.environ["PERC_STUDIO_SIGN_ARGS"]} $f']
    run([*cmd, str(PACKAGING / "installer.iss")], cwd=PACKAGING)
    return RELEASE / f"PERC-Studio-{version}-Setup.exe"


def write_checksums(files: list[Path]) -> None:
    lines = []
    for f in files:
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{digest}  {f.name}")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join("    " + line for line in lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--require-signing", action="store_true", help="fail unless code signing is configured")
    parser.add_argument("--skip-installer", action="store_true", help="build and test the ZIP only")
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("The release build targets Windows")
    signing = bool(os.environ.get("PERC_STUDIO_SIGN_ARGS"))
    if args.require_signing and not signing:
        sys.exit("--require-signing: set PERC_STUDIO_SIGN_ARGS (see packaging/README.md)")

    commit = git_commit()
    version = stage_sources(commit)
    log(f"Version {version}, build {commit}, {'signed' if signing else 'UNSIGNED'}")
    pyinstaller(write_version_file(version))
    copy_licenses()
    leak_scan()
    sign(APP_DIR / f"{APP_NAME}.exe")
    smoke_test()
    shutil.rmtree(RELEASE, ignore_errors=True)
    outputs = [make_zip(version)]
    if not args.skip_installer:
        outputs.append(make_installer(version, signing))
    write_checksums(outputs)
    log("Done: " + ", ".join(str(p.relative_to(ROOT)) for p in outputs))
    if not signing:
        print("    NOTE: unsigned build - Windows SmartScreen will warn on first run (see packaging/README.md).")


if __name__ == "__main__":
    main()
