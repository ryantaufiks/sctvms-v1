@echo off
title VMS Server - Restart
color 0E
cls

echo ================================================
echo    Restarting VMS Server...
echo ================================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8004" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo Server stopped. Starting in 2 seconds...
timeout /t 2 /nobreak >nul
call start_server.bat
