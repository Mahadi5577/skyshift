"""Download everything a demo needs ahead of time: tour stops plus sky patches for Hunt mode.

    python scripts/precache.py              # tour + 6 ecliptic hunt patches
    python scripts/precache.py --patches 12

After this, the tour and Hunt mode work instantly, even with a slow connection.
"""
import argparse
import sys
import time
from pathlib import Path

import astropy.units as u
from astropy.coordinates import GeocentricTrueEcliptic, SkyCoord

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import known, sequences, tour  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--patches", type=int, default=6, help="ecliptic patches for Hunt mode")
ap.add_argument("--skip-tour", action="store_true")
args = ap.parse_args()


def wait(seq, label):
    t0 = time.time()
    while any(s in ("pending", "loading") for s in seq["status"]):
        time.sleep(1)
    ok = seq["status"].count("ready")
    print(f"  {label}: {ok}/{len(seq['status'])} frames in {time.time() - t0:.0f}s", flush=True)
    try:
        k = known.known_objects(seq)
        if k["objects"]:
            print(f"    known objects: {', '.join(o['name'] for o in k['objects'][:5])}")
    except Exception as e:
        print(f"    known objects unavailable: {e}")


jobs = []
if not args.skip_tour:
    for s in tour.stops():
        jobs.append((f"tour: {s['title']}", dict(ra=s["ra"], dec=s["dec"], zoom=s["zoom"], wave=s["wave"],
                                                  n=s["n"], t_min=s["t_min"], t_max=s["t_max"], tol=s["tol"])))
# Hunt patches along the ecliptic, where asteroids are most common.
for k in range(args.patches):
    c = SkyCoord(lon=(150 + 12 * k) * u.deg, lat=0 * u.deg, frame=GeocentricTrueEcliptic).icrs
    for zoom in ("days", "hours"):
        jobs.append((f"hunt patch {k + 1} ({zoom})", dict(ra=round(c.ra.deg, 4), dec=round(c.dec.deg, 4), zoom=zoom)))

for label, kw in jobs:
    print(label, flush=True)
    try:
        wait(sequences.start(**kw), label)
    except LookupError as e:
        print(f"  skipped: {e}")
print(f"done; hunt pool now has {len(sequences.cached_sequences())} complete sequences")
