@echo off
rem SkyShift on Windows: first run creates .venv and installs packages, then starts the server.
rem   run.bat            start on http://localhost:8000
rem   run.bat precache   download tour + hunt data first (recommended before a demo)
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto installed
set PY=
py -3.12 -c "" >nul 2>nul && set PY=py -3.12
if not defined PY py -3.13 -c "" >nul 2>nul && set PY=py -3.13
if not defined PY py -3.11 -c "" >nul 2>nul && set PY=py -3.11
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3.11-3.13 not found. Install Python 3.12 from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% -m venv .venv
.venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package install failed.
  pause
  exit /b 1
)

:installed
if "%1"=="precache" .venv\Scripts\python scripts\precache.py
echo.
echo SkyShift is starting: open http://localhost:8000 in your browser. Press Ctrl+C to stop.
.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
