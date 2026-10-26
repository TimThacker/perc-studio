; Inno Setup script for the release. Run through
; packaging/build_release.py, which passes /DAppVersion=... /DSourceDir=...
; /DOutputDir=... (and /DSign plus /Ssigntool=... when code signing).

#ifndef AppVersion
  #error AppVersion must be defined (run packaging/build_release.py)
#endif

#define AppName "PERC Studio"
#define AppExe "PERC Studio.exe"
#define AppPublisher "CURENT, The University of Tennessee, Knoxville"

[Setup]
; Never change AppId: it is how Windows matches upgrades and uninstalls.
AppId={{6C1E2B0A-5E3D-4F57-9B7B-2C0F6A3E9D41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (c) 2026 Tim Thacker; CURENT, The University of Tennessee, Knoxville; and the Tennessee Valley Authority
VersionInfoVersion={#AppVersion}
; Per-user install: no administrator rights needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}\_internal\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=PERC-Studio-{#AppVersion}-Setup
SetupIconFile=..\assets\branding\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes
#ifdef Sign
SignTool=signtool
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An upgrade replaces the whole bundle, so files dropped from a newer
; version do not linger.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
