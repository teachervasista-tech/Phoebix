@echo off
REM Rebuild Phoebix with a fresh database

echo.
echo Resetting Phoebix database...
echo.

REM Delete the existing database if it exists
for /d %%D in ("%LOCALAPPDATA%\Phoebix") do (
    if exist "%%D\data\phoebix_desktop.sqlite3" (
        echo Deleting old database at %%D\data\phoebix_desktop.sqlite3
        del /f /q "%%D\data\phoebix_desktop.sqlite3" 2>nul
        del /f /q "%%D\data\phoebix_desktop.sqlite3-wal" 2>nul
        del /f /q "%%D\data\phoebix_desktop.sqlite3-shm" 2>nul
    )
)

echo.
echo Building fresh Phoebix.exe...
echo.

REM Run the standard build
call build_exe.bat

if errorlevel 1 (
    echo.
    echo Build failed!
    exit /b 1
)

echo.
echo ========================================================================
echo Build complete! Fresh database will be created on first run.
echo ========================================================================
echo.
pause
