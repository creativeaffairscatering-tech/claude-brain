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

python --version
echo.
echo Installing required packages...
echo.

pip install gspread google-auth click rich flask python-dotenv

if errorlevel 1 (
    echo.
    echo Package installation failed. Trying with --user flag...
    pip install --user gspread google-auth click rich flask python-dotenv
)

echo.
echo =========================================
echo  Setting up credentials and .env file...
echo =========================================
echo.

:: Create config folder
if not exist "%USERPROFILE%\.vendor-tracker" (
    mkdir "%USERPROFILE%\.vendor-tracker"
    echo Created folder: %USERPROFILE%\.vendor-tracker
)

:: Create .env file pointing to the key
set SCRIPT_DIR=%~dp0
if not exist "%SCRIPT_DIR%.env" (
    (
        echo GOOGLE_SERVICE_ACCOUNT_FILE=%USERPROFILE%\.vendor-tracker\service-account.json
        echo SPREADSHEET_ID=1vVhrW3j2aKXT5_UaaxYY6ZIZ673a9vO2iHmsIiNBED0
    ) > "%SCRIPT_DIR%.env"
    echo .env file created.
) else (
    echo .env file already exists.
)

echo.

:: Check for the key file
if exist "%USERPROFILE%\.vendor-tracker\service-account.json" (
    echo Google credentials found.
) else (
    echo -----------------------------------------------
    echo  ACTION REQUIRED:
    echo  Copy your service-account.json file to:
    echo  %USERPROFILE%\.vendor-tracker\service-account.json
    echo -----------------------------------------------
)

echo.
echo =========================================
echo  Creating desktop shortcut...
echo =========================================

set SHORTCUT=%USERPROFILE%\Desktop\Vendor Pricing Tracker.lnk

powershell -NoProfile -Command "$ws = New-Object -COM WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%SCRIPT_DIR%launch.vbs'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'Vendor Pricing Tracker — Creative Affairs Catering'; $s.Save()"

if exist "%SHORTCUT%" (
    echo Desktop shortcut created successfully!
) else (
    echo Could not create shortcut. You can manually run launch.bat instead.
)

echo.
echo =========================================
echo  Setup complete!
echo =========================================
echo.
echo Double-click "Vendor Pricing Tracker" on your Desktop to open the app.
echo.
pause
