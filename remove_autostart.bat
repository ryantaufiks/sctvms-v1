@echo off
title VMS Auto Start - Remove
color 0C
cls

echo ================================================
echo    Remove VMS Auto Start
echo ================================================
echo.

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if exist "%STARTUP_DIR%\VMS Server.lnk" (
    del "%STARTUP_DIR%\VMS Server.lnk"
    echo [OK] Auto start removed.
) else (
    echo [INFO] Auto start shortcut not found.
)

if exist "%~dp0start_silent.vbs" (
    del "%~dp0start_silent.vbs"
    echo [OK] Silent start script removed.
)

echo.
echo ================================================
echo    Done! VMS will no longer auto start on boot.
echo ================================================
echo.
pause
