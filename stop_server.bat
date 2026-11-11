@echo off
title VMS Server - Stop
color 0C
cls

echo ================================================
echo    Stopping VMS Server...
echo ================================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8004" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo Server stopped.
echo.
pause
