"""Download everything a demo needs ahead of time: tour stops plus sky patches for Hunt mode.

    python scripts/precache.py              # tour + 6 ecliptic hunt patches
    python scripts/precache.py --patches 12

After this, the tour and Hunt mode work instantly, even with a slow connection.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import precache  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--patches", type=int, default=6, help="ecliptic patches for Hunt mode")
ap.add_argument("--skip-tour", action="store_true")
args = ap.parse_args()
precache.run(args.patches, not args.skip_tour, log=lambda m: print(m, flush=True))
