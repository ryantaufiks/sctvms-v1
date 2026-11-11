@echo off
title VMS Auto Start Setup
color 0A
cls

echo ================================================
echo    Setup VMS Auto Start on Boot
echo ================================================
echo.

:: Get the current directory
set "PROJECT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: Create VBS script for silent start
echo Creating startup script...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDir = "%PROJECT_DIR%"
echo WshShell.Run "cmd /c .venv\Scripts\activate.bat ^& python manage.py runserver 0.0.0.0:8004", 0, False
) > "%PROJECT_DIR%\start_silent.vbs"

:: Create shortcut in Startup folder
echo Creating startup shortcut...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo Set shortcut = WshShell.CreateShortcut^("%STARTUP_DIR%\VMS Server.lnk"^)
echo shortcut.TargetPath = "%PROJECT_DIR%\start_silent.vbs"
echo shortcut.WorkingDirectory = "%PROJECT_DIR%"
echo shortcut.Description = "VMS Server Auto Start"
) > "%TEMP%\create_shortcut.vbs"

cscript //nologo "%TEMP%\create_shortcut.vbs"
del "%TEMP%\create_shortcut.vbs"

echo.
echo ================================================
echo    Setup Complete!
echo ================================================
echo.
echo    VMS Server will now start automatically
echo    when Windows boots up.
echo.
echo    Startup file: %STARTUP_DIR%\VMS Server.lnk
echo.
echo    To remove auto-start:
echo    Delete "VMS Server.lnk" from Startup folder:
echo    %STARTUP_DIR%
echo.
echo ================================================
echo.
pause
