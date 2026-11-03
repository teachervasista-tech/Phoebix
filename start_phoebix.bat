@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required to start Phoebix.
  echo Install Python 3 and try again.
  pause
  exit /b 1
)

python server.py
if errorlevel 1 (
  echo Phoebix stopped because the database or web server could not start.
  pause
  exit /b 1
)
