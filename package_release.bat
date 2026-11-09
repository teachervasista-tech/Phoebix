@echo off
REM Package Phoebix Release
REM Creates a distribution package with all necessary files for deployment

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Check if build exists
if not exist "dist\Phoebix.exe" (
    echo Error: dist\Phoebix.exe not found.
    echo Please run build_exe.bat first.
    pause
    exit /b 1
)

REM Create release directory with timestamp
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set RELEASE_DIR=Phoebix-Release-%mydate%-%mytime%

if exist "%RELEASE_DIR%" (
    rmdir /s /q "%RELEASE_DIR%"
)

echo Creating release package: %RELEASE_DIR%
mkdir "%RELEASE_DIR%"

REM Copy executable
echo Copying executable...
copy "dist\Phoebix.exe" "%RELEASE_DIR%\" >nul

REM Copy deployment files
echo Copying deployment files...
copy "install.bat" "%RELEASE_DIR%\" >nul
copy "DEPLOYMENT.md" "%RELEASE_DIR%\" >nul
copy ".env.example" "%RELEASE_DIR%\" >nul

REM Create README for release
(
    echo. Phoebix Pharmacy Management System - Release Package
    echo.
    echo This package contains everything needed to deploy Phoebix on Windows computers.
    echo.
    echo Contents:
    echo  - Phoebix.exe          Main application executable
    echo  - install.bat          Automated installer script
    echo  - DEPLOYMENT.md        Detailed deployment guide
    echo  - .env.example         Configuration template
    echo  - README.txt           This file
    echo.
    echo Quick Start:
    echo  1. Run install.bat to set up the application
    echo  2. Double-click Phoebix.exe to launch
    echo  3. Login with: admin / admin123
    echo  4. Set a new password on first launch
    echo.
    echo For detailed instructions, see DEPLOYMENT.md
    echo.
    echo System Requirements:
    echo  - Windows 10/11 64-bit
    echo  - 200 MB disk space
    echo  - 2 GB RAM
    echo  - No additional software needed
    echo.
) > "%RELEASE_DIR%\README.txt"

REM Create version info
for %%A in ("dist\Phoebix.exe") do set EXE_SIZE=%%~sA
(
    echo Version: 1.0.0
    echo Build Date: %mydate% %mytime%
    echo Executable Size: %EXE_SIZE% bytes
    echo.
    echo This is a single-file distribution. No installation required.
    echo Simply copy Phoebix.exe to any Windows 10/11 computer and run it.
) > "%RELEASE_DIR%\VERSION.txt"

echo.
echo ========================================================================
echo Release Package Created Successfully!
echo ========================================================================
echo.
echo Location: %RELEASE_DIR%
echo.
dir "%RELEASE_DIR%"
echo.
echo To distribute:
echo  1. Copy the entire %RELEASE_DIR% folder to target machines
echo  2. Run install.bat on each target machine
echo  3. Or simply double-click Phoebix.exe to run directly
echo.
echo For deployment on multiple machines, you can:
echo  - Email install.bat and Phoebix.exe
echo  - Copy to a shared network location
echo  - Create USB drives with the release package
echo.
pause
