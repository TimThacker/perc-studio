# PyInstaller spec for the release build. Run through
# packaging/build_release.py, which stages a copy of src/ with build_info.py's
# BUILD_COMMIT stamped and passes its path in PERC_STUDIO_STAGED_SRC.
# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
STAGED_SRC = Path(os.environ["PERC_STUDIO_STAGED_SRC"])
VERSION_FILE = os.environ.get("PERC_STUDIO_VERSION_FILE")

# Data files, at the same relative paths `resources.resource_path()` expects.
# docs/user/ (the Documentation tab) and docs/black_box/ (the Black-Box
# Validation guide) ship; the developer docs do not. Black-box validation runs
# psse_worker.py, and the outx.py reader it imports, as plain files under
# PSS/E's own Python, so both ship as data at their source paths.
datas = [
    (str(ROOT / "docs" / "user"), "docs/user"),
    (str(ROOT / "docs" / "black_box"), "docs/black_box"),
    (str(STAGED_SRC / "psse_worker" / "psse_worker.py"), "src/psse_worker"),
    (str(STAGED_SRC / "blackbox" / "outx.py"), "src/blackbox"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
for name in ("curent_logo.png", "curent_icon.png", "tva_logo.png", "app_icon.ico"):
    datas.append((str(ROOT / "assets" / "branding" / name), "assets/branding"))
# IBM Plex (SIL OFL 1.1, licence text in assets/fonts/OFL.txt and licenses/).
datas.append((str(ROOT / "assets" / "fonts"), "assets/fonts"))

# The perc-studio CLI and its pipeline install from source, not with the desktop
# app. The GUI never imports them, so they would not be collected anyway;
# excluding them makes a stray import fail the smoke test.
DEV_MODULES = ["dev"]
THIRD_PARTY_EXCLUDES = [
    "tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest", "IPython", "requests", "click",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtQuick3D", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtStateMachine", "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtAxContainer", "PySide6.QtBluetooth",
]

a = Analysis(
    [str(STAGED_SRC / "main.py")],
    pathex=[str(STAGED_SRC)],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    excludes=DEV_MODULES + THIRD_PARTY_EXCLUDES,
    noarchive=False,
    optimize=1,
)

# --- Trim Qt -------------------------------------------------------------------
# PyInstaller's QtWebEngine hook collects every QML module, and with them
# most of Qt (3D, Charts, Multimedia, Quick3D, ...), plus WebEngine's
# developer tools, debug resources and 50+ locales. This app uses none of
# them: it needs the Widgets UI, one QWebEngineView and SVG images. Keep the
# Python extension modules, Qt plugins and the WebEngine helper process,
# then keep only the Qt DLLs they actually import (transitively). The
# release build's frozen smoke test proves nothing needed was dropped.
from PyInstaller.depend.bindepend import get_imports  # noqa: E402


def _dest(entry):
    return entry[0].replace("\\", "/")


def _dropped_data(dest):
    name = dest.rsplit("/", 1)[-1]
    if dest.startswith("PySide6/qml/") or dest.startswith("PySide6/plugins/qmltooling/"):
        return True
    if dest.startswith("PySide6/resources/") and (".debug." in name or name.startswith("qtwebengine_devtools")):
        return True
    if dest.startswith("PySide6/translations/qtwebengine_locales/"):
        return name != "en-US.pak"
    return dest.startswith("PySide6/translations/") and name.endswith(".qm")


a.datas = [e for e in a.datas if not _dropped_data(_dest(e))]
binaries = [e for e in a.binaries if not _dropped_data(_dest(e))]
by_name = {}
for entry in binaries:
    by_name.setdefault(_dest(entry).rsplit("/", 1)[-1].lower(), entry)
roots = [e for e in binaries if not _dest(e).rsplit("/", 1)[-1].lower().startswith(("qt6", "pyside6qml"))]
needed, queue = set(), [e[1] for e in roots]
while queue:
    for dep in get_imports(queue.pop()):
        key = os.path.basename(dep[0] if isinstance(dep, tuple) else dep).lower()
        if key in by_name and key not in needed:
            needed.add(key)
            queue.append(by_name[key][1])
a.binaries = [e for e in binaries
              if not _dest(e).rsplit("/", 1)[-1].lower().startswith(("qt6", "pyside6qml"))
              or _dest(e).rsplit("/", 1)[-1].lower() in needed
              or _dest(e).rsplit("/", 1)[-1].lower() == "qt6webenginecore.dll"]

# Every bundled Python module, for build_release.py's leak scan.
with open(os.path.join(workpath, "bundled_modules.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(name for name, *_ in a.pure)))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PERC Studio",
    icon=str(ROOT / "assets" / "branding" / "app_icon.ico"),
    version=VERSION_FILE,
    console=False,
    debug=False,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PERC Studio",
)
