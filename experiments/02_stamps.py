"""Experiment 2: download small wavelength-matched stamps of one spot across all epochs.

Needs data/<target>/index.csv from 01_epochs.py.

    python 02_stamps.py M51                 # auto-pick the wavelength seen in the most survey passes
    python 02_stamps.py M51 --wave 1.65     # or force one (um)

Writes data/<target>/stamps/*.fits (IMAGE - ZODI, plus FLAGS) and stamps.csv.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.table import Table

import spx

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--wave", type=float, help="wavelength in um; default = best covered")
ap.add_argument("--tol", type=float, default=0.02, help="fractional wavelength match")
ap.add_argument("--half", type=int, default=24, help="stamp half-size in pixels (6.15 arcsec/px)")
ap.add_argument("--workers", type=int, default=6)
args = ap.parse_args()

c = spx.target_coord(args.target)
out = spx.DATA / spx.slug(args.target)
idx = Table.read(out / "index.csv")
wl = np.asarray(idx["wave_um"])

if args.wave is None:
    # Score each candidate wavelength by (survey passes covered, images matched).
    def score(w0):
        m = np.abs(wl - w0) / w0 < args.tol
        return len(set(idx["window"][m])), m.sum()
    args.wave = float(max(wl, key=score))
sel = idx[np.abs(wl - args.wave) / args.wave < args.tol]
print(f"{len(sel)} images within {args.tol:.0%} of {args.wave:.3f} um, "
      f"passes {sorted(set(sel['window']))}")

(out / "stamps").mkdir(exist_ok=True)


def fetch(row):
    path = out / "stamps" / f"{row['obs_id']}_D{row['detector']}.fits"
    if not path.exists():
        img, flags, w, _ = spx.read_stamp(row["key"], c.ra.deg, c.dec.deg, args.half)
        spx.save_stamp(path, img, flags, w, {
            "MJD-MID": row["mjd"], "WAVE_UM": row["wave_um"], "DETECTOR": row["detector"],
            "WINDOW": row["window"], "OBS_ID": row["obs_id"]})
    return path.name


with ThreadPoolExecutor(args.workers) as pool:
    for i, name in enumerate(pool.map(fetch, sel), 1):
        print(f"  [{i}/{len(sel)}] {name}", flush=True)

sel["file"] = [f"{r['obs_id']}_D{r['detector']}.fits" for r in sel]
sel.write(out / "stamps.csv", overwrite=True)
print(f"wrote {len(sel)} stamps to {out / 'stamps'}")
