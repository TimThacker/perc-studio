PERC Studio - third-party software notices

The app's own code is licensed under the MIT License (see LICENSE). The
Windows build bundles the following third-party components, each under its
own license. The full license texts are in the "licenses" folder next to
the application.

Component            Version   License
-------------------  --------  -------------------------------------------
Python               3.13      Python Software Foundation License
Qt 6 (incl. Qt       6.12      GNU LGPL v3 (licenses/LGPL-3.0.txt,
  WebEngine)                   licenses/GPL-3.0.txt)
PySide6, Shiboken6   6.12      GNU LGPL v3
Chromium (inside     -         BSD-3-Clause and other permissive licenses;
  Qt WebEngine)                see https://doc.qt.io/qt-6/qtwebengine-licensing.html
plotly (incl.        7.1       MIT
  plotly.js)
narwhals             2.26      MIT
packaging            26.3      Apache-2.0 or BSD-2-Clause
PyYAML               6.0       MIT
IBM Plex Sans and    3.005,    SIL Open Font License 1.1
  IBM Plex Mono      2.005     (licenses/OFL-1.1-IBM-Plex.txt)
  (fonts)
PyInstaller          6.x       GPL v2+ with an exception that allows
  bootloader                   distributing the bundled application under
                               any license

Qt and PySide6 (LGPL v3)
------------------------
Qt and PySide6 are used unmodified and are dynamically linked: they are the
separate Qt6*.dll, PySide6 and shiboken6 files in the application folder
(the "_internal" folder of the installation). You may replace them with
other compatible builds of the same libraries. Their source code is
available from The Qt Company at https://download.qt.io/official_releases/
(Qt) and https://download.qt.io/official_releases/QtForPython/ (PySide6).

Neither PSS/E nor the PERC1 or PERC2 user-defined model DLLs (ISO-NE) are
included with, or distributed by, this application.
