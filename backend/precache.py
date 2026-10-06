"""Download everything a demo needs ahead of time: tour stops plus sky patches for Hunt mode.
Used by scripts/precache.py and, with SKYSHIFT_PRECACHE=1, by the server at start-up.
Everything downloaded here is pinned, so cache pruning never removes it.
"""
import time

import astropy.units as u
from astropy.coordinates import GeocentricTrueEcliptic, SkyCoord

from . import known, sequences, tour


def jobs(patches=6, include_tour=True):
    out = []
    if include_tour:
        for s in tour.stops():
            out.append((f"tour: {s['title']}", dict(ra=s["ra"], dec=s["dec"], zoom=s["zoom"], wave=s["wave"],
                                                     n=s["n"], t_min=s["t_min"], t_max=s["t_max"], tol=s["tol"])))
    # Hunt patches along the ecliptic, where asteroids are most common.
    for k in range(patches):
        c = SkyCoord(lon=(150 + 12 * k) * u.deg, lat=0 * u.deg, frame=GeocentricTrueEcliptic).icrs
        for zoom in ("days", "hours"):
            out.append((f"hunt patch {k + 1} ({zoom})", dict(ra=round(c.ra.deg, 4), dec=round(c.dec.deg, 4),
                                                              zoom=zoom)))
    return out


def run(patches=6, include_tour=True, log=print):
    for label, kw in jobs(patches, include_tour):
        log(label)
        try:
            seq = sequences.start(**kw)
        except LookupError as e:
            log(f"  skipped: {e}")
            continue
        except Exception as e:  # archive down: carry on with the rest
            log(f"  failed: {e}")
            continue
        sequences.pin([seq["meta"]["id"]])
        t0 = time.time()
        while any(s in ("pending", "loading") for s in seq["status"]):
            time.sleep(1)
        log(f"  {label}: {seq['status'].count('ready')}/{len(seq['status'])} frames in {time.time() - t0:.0f}s")
        try:
            k = known.known_objects(seq)
            if k["objects"]:
                log(f"    known objects: {', '.join(o['name'] for o in k['objects'][:5])}")
        except Exception as e:
            log(f"    known objects unavailable: {e}")
    n = len(sequences.cached_sequences(max_age=0))
    log(f"done; hunt pool now has {n} complete sequences")
