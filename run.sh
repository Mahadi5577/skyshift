#!/usr/bin/env bash
# SkyShift on macOS / Linux: first run creates .venv and installs packages, then starts the server.
#   bash run.sh            start on http://localhost:8000
#   bash run.sh precache   download tour + hunt data first (recommended before a demo)
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  PY=""
  for c in python3.12 python3.13 python3.11 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  [ -n "$PY" ] || { echo "Python 3.11-3.13 not found (macOS: brew install python@3.12)"; exit 1; }
  "$PY" -m venv .venv
  if [ -x .venv/bin/python ]; then .venv/bin/python -m pip install -r requirements.txt
  else .venv/Scripts/python -m pip install -r requirements.txt; fi
fi
if [ -x .venv/bin/python ]; then VPY=.venv/bin/python; else VPY=.venv/Scripts/python; fi

[ "$1" = "precache" ] && "$VPY" scripts/precache.py
echo "SkyShift is starting: open http://localhost:8000 in your browser. Press Ctrl+C to stop."
exec "$VPY" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
