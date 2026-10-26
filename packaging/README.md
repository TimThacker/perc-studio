# Building a release

The release is built from this repository's source. There is no separate
release branch. `build_release.py` stages a copy of `src/` with
`build_info.BUILD_COMMIT` stamped, bundles what the GUI imports plus
`docs/user/`, `docs/black_box/`, the black-box PSS/E worker, the branding and
the license files, checks that the bundle holds only the desktop app, smoke-tests the
frozen app, and produces:

| File | What it is |
|---|---|
| `dist/release/PERC-Studio-<version>-Setup.exe` | Per-user installer (no admin rights). Adds a desktop shortcut and a Start-menu entry, and an uninstaller |
| `dist/release/PERC-Studio-<version>-win64.zip` | Portable build, with **Create Desktop Shortcut.cmd** and a README |
| `dist/release/SHA256SUMS.txt` | Checksums to publish with the files |

## What the installer contains

The installer and ZIP are the desktop app: Screening, Post-Commissioning,
Black-Box Validation and Documentation, the same as from source. The rest of
the project installs from source:

| | Source install | Installer / ZIP |
|---|---|---|
| Desktop app | yes | yes |
| `perc-studio` automation CLI (`src/dev/`) | yes | from source |
| Test suite, `utils/` scripts | yes | from source |
| Documentation → Developers group (contributor docs) | yes | from source |

## One-time setup

1. `uv sync --group packaging`
2. Install Inno Setup 6, for example
   `winget install --id JRSoftware.InnoSetup -e --scope user`. The build
   finds `ISCC.exe` on PATH or in the default install folders.

## Build

```powershell
uv run --group packaging python packaging/build_release.py
```

`--skip-installer` builds and tests the ZIP only. `--require-signing` fails
the build unless code signing is configured (use it for real releases).

## Release checklist

1. Bump `__version__` in `src/app/build_info.py` (SemVer; also the installer and
   the About page). Update `CHANGELOG.md`.
2. Regenerate the SVG figures if presets changed:
   `uv run python utils/scripts/generate_envelope_figures.py` and
   `uv run python utils/scripts/generate_parameter_preset_figures.py`.
3. `uv run pytest -q` passes, including the user-docs and release tests.
4. Commit, then build from a clean tree (a dirty tree stamps the build
   commit `-dirty`).
5. On a clean Windows account or VM:
   - install, launch from the desktop shortcut, and check the icon on the
     desktop, window and taskbar;
   - **disconnect the network** and check that the live charts still draw;
   - export a `.dyr` and a report from each tab, then uninstall;
   - repeat with the ZIP and its shortcut script.
6. Tag `v<version>` and publish the three files from `dist/release/`.

## Code signing

Unsigned Windows programs downloaded from the internet or email get a
Microsoft Defender SmartScreen warning ("Windows protected your PC").
Recipients must click **More info → Run anyway**, and some organizations
block unsigned programs outright. Sign every public release.

**Getting a certificate (choose one):**

- **An institutional certificate.** If the maintainer's organization (for
  example a university IT office) has an organization-validated code-signing
  certificate or signing service, use it. This is usually the cheapest option
  and puts the organization's name on the signature.
- **Azure Artifact Signing** (formerly Trusted Signing). A Microsoft-managed
  signing service billed monthly. It needs an Azure subscription and
  identity validation of the organization or individual. Signing uses
  `signtool` with Microsoft's dlib plugin.
- **A commercial OV code-signing certificate** (DigiCert, Sectigo, SSL.com
  and others). Since 2023 these are issued on a hardware token or a cloud
  HSM, not as a `.pfx` file.

A new certificate still builds SmartScreen reputation over time, so early
downloads can show a warning even when signed. Signing does make the warning
name the publisher, and it lets IT departments allow the app by publisher.

**Configuring the build.** Install the Windows SDK's `signtool.exe`, then set
`PERC_STUDIO_SIGN_ARGS` to the signtool arguments that select your certificate and
timestamp server (everything between `signtool sign` and the file name):

```powershell
# Certificate in the Windows certificate store (token or HSM)
$env:PERC_STUDIO_SIGN_ARGS = '/sha1 <certificate thumbprint> /fd SHA256 /tr http://timestamp.digicert.com /td SHA256'
# Azure Artifact Signing
$env:PERC_STUDIO_SIGN_ARGS = '/fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib <path>\Azure.CodeSigning.Dlib.dll /dmdf <path>\metadata.json'
# Optional, if signtool.exe is not on PATH
$env:PERC_STUDIO_SIGNTOOL = 'C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\signtool.exe'

uv run --group packaging python packaging/build_release.py --require-signing
```

The build signs the app executable (then verifies it), the installer and the
installer's uninstaller.

## Files

| File | Purpose |
|---|---|
| `build_release.py` | The one-command build described above |
| `perc_studio.spec` | PyInstaller spec: data files, excluded development modules, icon, version resource |
| `installer.iss` | Inno Setup script (per-user install, desktop shortcut, uninstaller). Never change its `AppId` |
| `make_icon.py` | Regenerates `assets/branding/app_icon.ico` (the CURENT mark on white) |
| `zip_extras/` | The ZIP's shortcut script and README |
| `licenses/` | LGPL and GPL texts shipped for Qt and PySide6 |
