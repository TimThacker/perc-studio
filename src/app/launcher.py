"""The `perc-studio` command: the desktop app, or the automation CLI.

`perc-studio` with no arguments, or with only options (`--mode`, `--version`,
`--smoke-test`), opens the PySide6 desktop app. `perc-studio <command> ...`
(`params`, `export`, `sweep`, `blackbox`, ...) runs the automation CLI in
`dev.cli`, which never starts Qt; `perc-studio help` lists its commands. The CLI
comes with a source install: the installer bundles the desktop app only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.build_info import __version__

APP_USER_MODEL_ID = "CURENT.PERCStudio"


def _modes() -> list[str]:
    return ["screening", "post-commissioning"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perc-studio",
        description="Open the PERC Studio desktop app.",
        epilog="Automation CLI: perc-studio <command> [options]. Run `perc-studio help` for the commands "
               "(params, export, run, validate, report, sweep, blackbox, ...).",
    )
    parser.add_argument("--mode", choices=_modes(), default="screening", help="Open the main window on this workflow's tab.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--smoke-test", nargs="?", const=".", default=None, metavar="OUT_DIR", help="Build the main window, render a live plot, write a .dyr and an HTML report into OUT_DIR, then exit (0 = success). Used by the release build.")
    return parser


def _set_windows_app_id() -> None:
    """Group the app's windows under its own taskbar entry and icon, not
    python.exe's."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass


def _run_cli(args: list[str]) -> int:
    """`perc-studio <command> ...`: hand the arguments to the automation CLI. It is
    imported here, not at module level, so the desktop app never loads it."""
    try:
        from dev.cli.main import main as cli_main
    except ImportError:
        print("perc-studio: the automation CLI comes with a source install; this installed app is the desktop "
              "app only. See https://github.com/TimThacker/perc-studio#install.", file=sys.stderr)
        return 2
    return cli_main(["--help"] if args == ["help"] else args)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        return _run_cli(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = str(args.mode)

    _set_windows_app_id()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app.config import APP_ICON_PATH

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("PERC Studio")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(APP_ICON_PATH))

    if args.smoke_test is not None:
        return _smoke_test(app, args.smoke_test)

    from ui.main_window import MainWindow

    window = MainWindow(initial_mode=mode)

    window.show()
    return app.exec()


def _smoke_test(app, out_dir: str) -> int:
    """Construct the main window, wait for the live chart to load and draw
    its Plotly figure, and write a .dyr and an HTML report. Proves the frozen
    build has its data files, QtWebEngine, the bundled plotly.js and every
    module the export path needs."""
    from pathlib import Path

    from PySide6.QtCore import QTimer

    from export.dyr import build_dyr_text
    from export.report import build_html_report
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    out = Path(out_dir)
    state = window._state_from_screening_report_form()
    (out / "smoke.dyr").write_text(build_dyr_text(state), encoding="utf-8")
    (out / "smoke_report.html").write_text(build_html_report(state), encoding="utf-8")
    window.tabs.setCurrentWidget(window.docs_tab)  # render the doc library too
    window.tabs.setCurrentIndex(0)

    view = window.pc_screening_preview.view
    result = {"code": 1}

    def check(attempts_left: int = 60) -> None:
        def got(value) -> None:
            if value:
                result["code"] = 0
                app.quit()
            elif attempts_left > 0:
                QTimer.singleShot(500, lambda: check(attempts_left - 1))
            else:
                app.quit()

        view.page().runJavaScript(
            "!!(window.Plotly && document.querySelector('.js-plotly-plot .main-svg'))", 0, got)

    QTimer.singleShot(500, check)
    QTimer.singleShot(60_000, app.quit)  # hard stop
    app.exec()
    print("smoke test", "passed" if result["code"] == 0 else "FAILED")
    return result["code"]
