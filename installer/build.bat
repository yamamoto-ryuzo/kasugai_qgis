@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM kasugai_qgis NSIS installer build batch
REM Run "cargo build --release" before this script
REM Output: ..\public\kasugai_qgis-setup.exe  (full: EXE + data, for initial install / full update)
REM         ..\public\kasugai_qgis-update.exe (EXE only, for normal auto-update)

set "VERSION=1.4.0"

if not exist "..\target\release\qgis_launcher.exe" (
    echo ERROR: release build of qgis_launcher.exe not found.
    echo        Run "cargo build --release" first.
    exit /b 1
)

if not exist "..\download\qgis_settings.json" (
    echo ERROR: ..\download\qgis_settings.json not found.
    exit /b 1
)

REM Search for makensis.exe in several locations
set "MAKENSIS="
if exist "%NSISDIR%\makensis.exe" set "MAKENSIS=%NSISDIR%\makensis.exe"
if "%MAKENSIS%"=="" if exist "C:\nsis\makensis.exe" set "MAKENSIS=C:\nsis\makensis.exe"
if "%MAKENSIS%"=="" if exist "C:\Program Files\NSIS\makensis.exe" set "MAKENSIS=C:\Program Files\NSIS\makensis.exe"
if "%MAKENSIS%"=="" if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "MAKENSIS=C:\Program Files (x86)\NSIS\makensis.exe"

if "%MAKENSIS%"=="" (
    where makensis.exe >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%a in ('where makensis.exe') do set "MAKENSIS=%%a"
    )
)

if "%MAKENSIS%"=="" (
    echo ERROR: makensis.exe not found. Install NSIS or set NSISDIR env var.
    echo        https://nsis.sourceforge.io/Download
    exit /b 1
)

echo makensis: %MAKENSIS%

REM Compile NSIS script with UTF-8 input (full installer: EXE + data)
"%MAKENSIS%" /INPUTCHARSET UTF8 setup.nsi
if errorlevel 1 (
    echo ERROR: NSIS compilation failed. [full installer]
    exit /b 1
)

echo Done: ..\public\kasugai_qgis-setup.exe

REM Compile update-only installer (EXE only, no data)
"%MAKENSIS%" /INPUTCHARSET UTF8 /DUPDATE_ONLY setup.nsi
if errorlevel 1 (
    echo ERROR: NSIS compilation failed. [update-only installer]
    exit /b 1
)

echo Done: ..\public\kasugai_qgis-update.exe

REM build distribution ZIP as well
call build_zip.bat
if errorlevel 1 (
    echo ERROR: ZIP build failed.
    exit /b 1
)
