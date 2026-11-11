@echo off
title VMS Server - HCIBS [Port 8004]
color 0B
cls

echo ================================================
echo    VMS Server Starting...
echo    Port: 8004
echo ================================================
echo.
echo    Open browser and go to:
echo    http://localhost:8004
echo.
echo ================================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run install.bat first.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python manage.py runserver 0.0.0.0:8004
echo.
echo Server stopped.
pause
