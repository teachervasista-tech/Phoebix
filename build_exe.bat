@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Check Python
python --version >nul 2>nul
if errorlevel 1 (
  echo Error: Python is not installed or not in PATH.
  echo Please install Python 3.10+ from https://www.python.org/
  pause
  exit /b 1
)

REM Install/upgrade PyInstaller
echo Installing build tools...
python -m pip install --upgrade pyinstaller >nul 2>nul
if errorlevel 1 (
  echo Error: Failed to install PyInstaller
  pause
  exit /b 1
)

REM Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del *.spec 2>nul

REM Build executable
echo.
echo Building Phoebix.exe - this may take a minute...
echo.
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "Phoebix" ^
  --add-data "sample_state.json;." ^
  --distpath "dist" ^
  --workpath "build" ^
  main.py

if errorlevel 1 (
  echo.
  echo Build failed. Check the errors above.
  pause
  exit /b 1
)

REM Verify build
if not exist "dist\Phoebix.exe" (
  echo.
  echo Build failed: Phoebix.exe not found in dist directory.
  pause
  exit /b 1
)

REM Copy sample_state.json to dist folder
if exist "sample_state.json" (
  copy "sample_state.json" "dist\sample_state.json" >nul
)

echo.
echo ========================================================================
echo Build successful!
echo.
echo Release: dist\Phoebix.exe
echo Size:
for %%A in ("dist\Phoebix.exe") do echo   %%~sA bytes
echo.
echo To deploy on a new computer:
echo  1. Copy dist\Phoebix.exe to the target computer
echo  2. Double-click Phoebix.exe to run
echo  3. On first launch:
echo     - Database will be created in %%LOCALAPPDATA%%\Phoebix\
echo     - Sample data will be loaded
echo     - Set a new password for the admin account
echo  4. Ready to use!
echo.
echo Login credentials (before password change):
echo   Username: admin, Password: admin123
echo   Username: cashier, Password: cashier123
echo ========================================================================
echo.
pause
