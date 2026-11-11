@echo off
title VMS Installation - HCIBS
color 0A
cls

echo ================================================
echo    VMS (Visitor Management System) Installer
echo    Hwa Chong Institution Boarding School
echo ================================================
echo.

:: Check if Python is installed
echo [1/7] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.8+ from: https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYTHON_VERSION=%%a
echo [OK] Python %PYTHON_VERSION% found.
echo.

:: Check Python version (need 3.8+)
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.8 or higher is required.
    echo Please download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Create virtual environment
echo [2/7] Creating virtual environment...
if exist ".venv" (
    echo [SKIP] Virtual environment already exists.
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)
echo.

:: Activate venv and upgrade pip
echo [3/7] Upgrading pip...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo [OK] Pip upgraded.
echo.

:: Install dependencies
echo [4/7] Installing dependencies (this may take a few minutes)...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.
echo.

:: Run migrations
echo [5/7] Setting up database...
python manage.py migrate --run-syncdb 2>nul
if %errorlevel% neq 0 (
    python manage.py migrate
)
echo [OK] Database configured.
echo.

:: Create superuser automatically
echo [6/7] Creating default admin account...
python setup_admin.py
echo.

:: Create media directories
echo [7/7] Creating required directories...
if not exist "media\face_images" mkdir media\face_images
if not exist "media\plate_images" mkdir media\plate_images
if not exist "media\fdlib_faces" mkdir media\fdlib_faces
if not exist "media\qr_codes" mkdir media\qr_codes
if not exist "media\logos" mkdir media\logos
if not exist "backups" mkdir backups
if not exist "logs" mkdir logs
echo [OK] Directories created.
echo.

echo ================================================
echo    Installation Complete!
echo ================================================
echo.
echo    Default Login:
echo      Username : admin
echo      Password : Hcibs12345
echo.
echo    Start server : Double-click start_server.bat
echo    Stop server  : Double-click stop_server.bat
echo.
echo    Server will run at: http://localhost:8004
echo.
echo    NOTE: Use localhost, NOT 0.0.0.0 in browser!
echo ================================================
echo.
pause
