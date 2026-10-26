@echo off
rem Creates a "PERC Studio" shortcut on your desktop that starts the
rem app from this folder. Run it again if you move the folder.
setlocal
set "APPDIR=%~dp0"
set "EXE=%APPDIR%PERC Studio.exe"
if not exist "%EXE%" (
  echo Could not find "%EXE%". Run this file from the extracted app folder.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\PERC Studio.lnk'); $s.TargetPath=$env:EXE; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:EXE + ',0'; $s.Description='PERC Studio'; $s.Save()"
if errorlevel 1 (
  echo The shortcut could not be created.
  pause
  exit /b 1
)
echo Created the "PERC Studio" shortcut on your desktop.
timeout /t 3 >nul
