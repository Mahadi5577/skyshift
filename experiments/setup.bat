@echo off
rem Windows setup: creates .venv, installs packages, runs the setup check.
rem Double-click it, or run "setup.bat" in a terminal ("setup.bat --no-pause" skips the final pause).
cd /d "%~dp0"

set PY=
py -3.12 -c "" >nul 2>nul && set PY=py -3.12
if not defined PY py -3.13 -c "" >nul 2>nul && set PY=py -3.13
if not defined PY py -3.11 -c "" >nul 2>nul && set PY=py -3.11
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3.11-3.13 not found. Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install. Then run setup.bat again.
  goto end
)
echo Using %PY%

if not exist .venv\Scripts\python.exe %PY% -m venv .venv
rem Do not upgrade pip inside the venv: it broke on a Windows file lock during testing.
.venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package install failed. See GUIDE.md, section 8: Troubleshooting.
  goto end
)
.venv\Scripts\python 00_check.py
echo.
echo Next: .venv\Scripts\python 01_epochs.py M51

:end
if not "%1"=="--no-pause" pause
