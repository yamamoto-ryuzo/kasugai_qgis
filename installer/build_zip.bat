@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM kasugai_qgis distribution ZIP build batch
REM Run "cargo build --release" before this script
REM Output: ..\public\kasugai_qgis.zip

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

set "STAGE_DIR=%TEMP%\kasugai_qgis_zip_stage"
set "APP_DIR=%STAGE_DIR%\kasugai_qgis"
set "ZIP_OUT=..\public\kasugai_qgis.zip"

REM clean stage directory
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
mkdir "%APP_DIR%"

REM copy executable and settings
copy "..\target\release\qgis_launcher.exe" "%APP_DIR%\"
copy "..\download\qgis_settings.json" "%APP_DIR%\"
copy "..\download\qgislocalsync.config.example" "%APP_DIR%\"
copy "..\download\qgis_settings_override.json.example" "%APP_DIR%\"
copy "..\download\qgis_settings_USERNAME.json.example" "%APP_DIR%\"

REM copy bundled folders
xcopy /E /I /Y "..\download\ini" "%APP_DIR%\ini"
xcopy /E /I /Y "..\download\profiles" "%APP_DIR%\profiles"
xcopy /E /I /Y "..\download\ProjectFiles" "%APP_DIR%\ProjectFiles"

REM remove existing ZIP
if exist "%ZIP_OUT%" del "%ZIP_OUT%"

REM create ZIP using tar if available, otherwise PowerShell Compress-Archive
tar -acf "%ZIP_OUT%" -C "%STAGE_DIR%" kasugai_qgis >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Compress-Archive -Path '%APP_DIR%' -DestinationPath '%ZIP_OUT%' -Force" >nul
    if errorlevel 1 (
        echo ERROR: ZIP creation failed.
        rmdir /s /q "%STAGE_DIR%"
        exit /b 1
    )
)

rmdir /s /q "%STAGE_DIR%"

echo Done: %ZIP_OUT%
