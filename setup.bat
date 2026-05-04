@echo off
title Vendor Pricing Tracker — Setup
echo.
echo =========================================
echo  Vendor Pricing Tracker — First-Time Setup
echo  Creative Affairs Catering
echo =========================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in your PATH.
    echo.
    echo Please download and install Python from:
    echo   https://www.python.org/downloads/
    echo.
    echo During install, check the box "Add Python to PATH"
    echo Then re-run this setup.
    pause
    exit /b 1
)

echo Python found. Installing required packages...
echo.

pip install gspread google-auth click rich flask python-dotenv pywebview --quiet

if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed.
    echo Try running this file as Administrator (right-click → Run as administrator)
    pause
    exit /b 1
)

echo.
echo =========================================
echo  Setting up your credentials...
echo =========================================
echo.

:: Create config folder
if not exist "%USERPROFILE%\.vendor-tracker" (
    mkdir "%USERPROFILE%\.vendor-tracker"
)

:: Check if key file already exists
if exist "%USERPROFILE%\.vendor-tracker\service-account.json" (
    echo Credentials file already found — skipping.
) else (
    echo IMPORTANT: You need your Google service account key file.
    echo.
    echo Please copy your service-account.json file to:
    echo   %USERPROFILE%\.vendor-tracker\service-account.json
    echo.
    echo Then re-run launch.bat to start the app.
)

:: Create .env file in the app folder
set SCRIPT_DIR=%~dp0
if not exist "%SCRIPT_DIR%.env" (
    echo GOOGLE_SERVICE_ACCOUNT_FILE=%USERPROFILE%\.vendor-tracker\service-account.json > "%SCRIPT_DIR%.env"
    echo SPREADSHEET_ID=1vVhrW3j2aKXT5_UaaxYY6ZIZ673a9vO2iHmsIiNBED0 >> "%SCRIPT_DIR%.env"
    echo .env file created.
) else (
    echo .env file already exists — skipping.
)

echo.
echo =========================================
echo  Creating desktop shortcut...
echo =========================================

set SHORTCUT_PATH=%USERPROFILE%\Desktop\Vendor Pricing Tracker.lnk
set TARGET=%SCRIPT_DIR%launch.vbs
set ICON=%SCRIPT_DIR%launch.vbs

powershell -NoProfile -Command ^
  "$ws = New-Object -COM WScript.Shell; ^
   $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); ^
   $s.TargetPath = '%SCRIPT_DIR%launch.vbs'; ^
   $s.WorkingDirectory = '%SCRIPT_DIR%'; ^
   $s.Description = 'Vendor Pricing Tracker'; ^
   $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo Desktop shortcut created!
) else (
    echo Could not create shortcut automatically.
    echo Manually create a shortcut to: %SCRIPT_DIR%launch.vbs
)

echo.
echo =========================================
echo  Setup complete!
echo =========================================
echo.
echo To open the app: double-click "Vendor Pricing Tracker" on your desktop.
echo.
pause
