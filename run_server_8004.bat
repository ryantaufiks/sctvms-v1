@echo off
rem Run Django development server on port 8004
setlocal ENABLEDELAYEDEXPANSION

rem Move to the directory where this script resides
cd /d "%~dp0"

rem Activate virtual environment if available
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else (
  echo [WARN] Virtual environment not found at .venv\Scripts\activate.bat
  echo        Proceeding without venv. Ensure dependencies are installed.
)

rem Use UTF-8 for consistent output
set PYTHONUTF8=1

rem Resolve Python executable (prefer venv python)
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  set "PYTHON_CMD=%VENV_PY%"
) else (
  echo [WARN] Venv python not found at %VENV_PY%
  echo        Falling back to system python. Ensure it's installed.
  set "PYTHON_CMD=python"
)

rem Start Media image server on port 8005 (serves /media)
pushd "%~dp0media"
start "Media Server 8005" "%PYTHON_CMD%" -m http.server 8005 --bind 0.0.0.0
popd

rem Start Django dev server on localhost:8004
"%PYTHON_CMD%" manage.py runserver 127.0.0.1:8004

endlocal