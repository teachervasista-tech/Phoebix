@echo off
REM Phoebix Pharmacy App - Windows Installer
REM This script installs Phoebix on a Windows computer
REM No dependencies required - just copy this file and Phoebix.exe to the target machine

setlocal enabledelayedexpansion

REM Colors for output
for /F %%A in ('copy /Z "%~f0" nul') do set "BS=%%A"

echo.
echo ========================================================================
echo  Phoebix Pharmacy Management System - Windows Installer
echo ========================================================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Status: Running with Administrator privileges
) else (
    echo Warning: Not running as Administrator
    echo Some features may be limited. Consider running as Administrator.
    echo.
)

REM Look for Phoebix.exe in current directory
if not exist "Phoebix.exe" (
    echo Error: Phoebix.exe not found in the current directory.
    echo.
    echo Please ensure that:
    echo  1. This installer and Phoebix.exe are in the same folder
    echo  2. Phoebix.exe exists and is not corrupted
    echo.
    pause
    exit /b 1
)

echo Found: Phoebix.exe
for %%A in ("Phoebix.exe") do echo Size: %%~sA bytes
echo.

REM Create application data directory
echo Creating Phoebix data directory...
set "PHOEBIX_HOME=%LOCALAPPDATA%\Phoebix"
if not exist "%PHOEBIX_HOME%" (
    mkdir "%PHOEBIX_HOME%"
    if errorLevel 1 (
        echo Error: Could not create %PHOEBIX_HOME%
        pause
        exit /b 1
    )
    echo Created: %PHOEBIX_HOME%
) else (
    echo Directory exists: %PHOEBIX_HOME%
)

echo Creating data subdirectory...
if not exist "%PHOEBIX_HOME%\data" (
    mkdir "%PHOEBIX_HOME%\data"
)

REM Ask about creating shortcuts
echo.
echo ========================================================================
echo  Create Shortcuts
echo ========================================================================
set /p CREATE_DESKTOP="Create shortcut on Desktop? (y/n): "
if /i "%CREATE_DESKTOP%"=="y" (
    REM Create desktop shortcut
    set "DESKTOP=%USERPROFILE%\Desktop"
    echo Creating shortcut: !DESKTOP!\Phoebix.lnk

    REM Use PowerShell to create shortcut (more reliable than VBS)
    powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%DESKTOP%\Phoebix.lnk'); $Shortcut.TargetPath = '%CD%\Phoebix.exe'; $Shortcut.WorkingDirectory = '%CD%'; $Shortcut.Description = 'Phoebix - Pharmacy Management'; $Shortcut.Save()" 2>nul

    if exist "!DESKTOP!\Phoebix.lnk" (
        echo Success: Shortcut created
    )
)

set /p CREATE_STARTMENU="Create shortcut in Start Menu? (y/n): "
if /i "%CREATE_STARTMENU%"=="y" (
    REM Create Start Menu shortcut
    set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
    echo Creating shortcut: !STARTMENU!\Phoebix.lnk

    powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTMENU%\Phoebix.lnk'); $Shortcut.TargetPath = '%CD%\Phoebix.exe'; $Shortcut.WorkingDirectory = '%CD%'; $Shortcut.Description = 'Phoebix - Pharmacy Management'; $Shortcut.Save()" 2>nul

    if exist "!STARTMENU!\Phoebix.lnk" (
        echo Success: Start Menu shortcut created
    )
)

REM Optional configuration
echo.
echo ========================================================================
echo  Configuration (Optional)
echo ========================================================================
echo.
set /p CONFIGURE=".env file setup? (y/n): "
if /i "%CONFIGURE%"=="y" (
    if exist "%PHOEBIX_HOME%\.env" (
        echo .env file already exists at %PHOEBIX_HOME%\.env
        set /p OVERWRITE="Overwrite? (y/n): "
        if not /i "%OVERWRITE%"=="y" (
            goto :skip_env
        )
    )

    echo.
    echo Creating .env file for configuration
    echo Enter values (press Enter to skip):
    echo.

    set /p ADMIN_PASS="Admin password (or leave empty for 'admin123'): "
    set /p DB_PATH="Custom database path (or leave empty for default): "
    set /p PHONEPE_ENV="PhonePe environment - sandbox or production (or leave empty): "
    set /p PHONEPE_ID="PhonePe Client ID (or leave empty): "
    set /p PHONEPE_SECRET="PhonePe Client Secret (or leave empty): "

    (
        if not "!ADMIN_PASS!"=="" echo PHOEBIX_ADMIN_PASSWORD=!ADMIN_PASS!
        if not "!DB_PATH!"=="" echo PHOEBIX_DB_PATH=!DB_PATH!
        if not "!PHONEPE_ENV!"=="" echo PHONEPE_ENV=!PHONEPE_ENV!
        if not "!PHONEPE_ID!"=="" echo PHONEPE_CLIENT_ID=!PHONEPE_ID!
        if not "!PHONEPE_SECRET!"=="" echo PHONEPE_CLIENT_SECRET=!PHONEPE_SECRET!
    ) > "%PHOEBIX_HOME%\.env"

    echo Configuration saved to %PHOEBIX_HOME%\.env
    :skip_env
)

REM Installation complete
echo.
echo ========================================================================
echo  Installation Complete!
echo ========================================================================
echo.
echo Phoebix has been configured for this computer.
echo.
echo Data location:
echo   %PHOEBIX_HOME%
echo.
echo To start Phoebix:
echo   - Double-click Phoebix.exe, or
echo   - Use the Desktop/Start Menu shortcut
echo.
echo First Launch:
echo   1. Login with: admin / admin123
echo   2. Set a new password (8+ characters required)
echo   3. Configure pharmacy details in Settings
echo.
echo For help, see: DEPLOYMENT.md
echo.

REM Offer to start the app
echo ========================================================================
set /p START_APP="Start Phoebix now? (y/n): "
if /i "%START_APP%"=="y" (
    echo.
    echo Starting Phoebix...
    echo.
    echo Note: Database initialization on first launch may take 5-10 seconds.
    echo Please wait while sample data is being loaded...
    echo.
    start "Phoebix" "Phoebix.exe"
) else (
    echo.
    echo You can launch Phoebix anytime by:
    echo   1. Double-clicking Phoebix.exe
    echo   2. Using the desktop or Start Menu shortcut
    echo.
)

echo Installation finished.
pause
