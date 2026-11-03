@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install pyinstaller
  if errorlevel 1 exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name Phoebix ^
  --add-data "sample_state.json;." ^
  main.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Built dist\Phoebix.exe - copy this single file to any Windows PC and double-click it.
