@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install pyinstaller
  if errorlevel 1 exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --name Phoebix ^
  --add-data "index.html;." --add-data "styles.css;." --add-data "app.js;." ^
  --add-data "manifest.json;." --add-data "sw.js;." --add-data "icon.svg;." ^
  --add-data "sample_state.json;." ^
  server.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Built dist\Phoebix.exe - copy this single file to any Windows PC and double-click it.
