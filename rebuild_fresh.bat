@echo off
REM Rebuild Phoebix with a fresh database

echo.
echo Resetting Phoebix database...
echo.

REM Back up, then delete, the existing database if it exists.
REM Close Phoebix first: the -wal file may hold recent sales that are not yet in the main file.
for /d %%D in ("%LOCALAPPDATA%\Phoebix") do (
    if exist "%%D\data\phoebix_desktop.sqlite3" (
        for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%T
        call :backup "%%D"
        if errorlevel 1 (
            echo Backup failed - the old database was NOT deleted.
            exit /b 1
        )
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
exit /b 0

:backup
set "BK=%~1\backups\pre-rebuild-%STAMP%"
mkdir "%BK%" 2>nul
echo Backing up old database to %BK%
copy /y "%~1\data\phoebix_desktop.sqlite3" "%BK%\" >nul || exit /b 1
if exist "%~1\data\phoebix_desktop.sqlite3-wal" copy /y "%~1\data\phoebix_desktop.sqlite3-wal" "%BK%\" >nul
if exist "%~1\data\phoebix_desktop.sqlite3-shm" copy /y "%~1\data\phoebix_desktop.sqlite3-shm" "%BK%\" >nul
exit /b 0
