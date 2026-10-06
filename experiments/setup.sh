#!/usr/bin/env bash
# macOS / Linux setup: creates .venv, installs packages, runs the setup check.
#   bash setup.sh
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.13 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11-3.13 not found. macOS: 'brew install python@3.12' or https://www.python.org/downloads/"
  echo "Linux: install python3.12 and python3.12-venv from your package manager."
  exit 1
fi
echo "Using $PY ($("$PY" --version))"

[ -d .venv ] || "$PY" -m venv .venv
if [ -x .venv/bin/python ]; then VPY=.venv/bin/python; else VPY=.venv/Scripts/python; fi
"$VPY" -m pip install --disable-pip-version-check -r requirements.txt
"$VPY" 00_check.py || true
echo
echo "Next: source .venv/bin/activate && python 01_epochs.py M51"
