@echo off
title VMS Cloudflare Tunnel Setup
color 0A
cls

echo ================================================
echo    VMS Cloudflare Tunnel Configuration
echo ================================================
echo.
echo    This will configure Django to work with
echo    your Cloudflare Tunnel domain.
echo.

set /p TUNNEL_URL="Enter your tunnel URL (e.g. https://hcibs.sctvms.com): "

if "%TUNNEL_URL%"=="" (
    echo [ERROR] No URL entered!
    pause
    exit /b 1
)

python setup_tunnel.py "%TUNNEL_URL%"
echo.
pause
