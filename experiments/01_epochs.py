"""Experiment 1: how often does SPHEREx look at one spot, and at which wavelengths?

Answers the go/no-go question for time-zoom: are there repeat looks at a *similar wavelength*,
and how far apart in time are they (hours / days / months)?

    python 01_epochs.py M51
    python 01_epochs.py "202.4696,47.1952" --collection spherex_qr2

Writes data/<target>/index.csv and data/<target>/epochs.png.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.table import Table
from astropy.time import Time

import spx

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--collection", default="spherex_qr2")
ap.add_argument("--tol", type=float, default=0.02, help="fractional wavelength match, default 2%%")
ap.add_argument("--workers", type=int, default=8)
args = ap.parse_args()

c = spx.target_coord(args.target)
ra, dec = c.ra.deg, c.dec.deg
out = spx.DATA / spx.slug(args.target)
out.mkdir(parents=True, exist_ok=True)

rows = spx.query_images(ra, dec, collection=args.collection)
print(f"{args.target} ({ra:.5f}, {dec:.5f}) in {args.collection}: {len(rows)} images")
if not len(rows):
    raise SystemExit("no coverage; try another --collection")

keys = [spx.s3_key(r) for r in rows]
dets = [int(r["energy_bandpassname"].split("-D")[-1]) for r in rows]

# One wavelength table per detector, then one 32 KB header request per image.
tables = {d: spx.wave_table(d, keys[dets.index(d)]) for d in sorted(set(dets))}


def measure(i):
    hdr = spx.image_header(keys[i])
    return spx.wavelength_at(hdr, tables[dets[i]], ra, dec)


with ThreadPoolExecutor(args.workers) as pool:
    meas = list(pool.map(measure, range(len(rows))))

mjd = (np.asarray(rows["t_min"]) + np.asarray(rows["t_max"])) / 2
idx = Table({
    "obs_id": [str(r["obs_id"]) for r in rows],
    "detector": dets,
    "mjd": mjd,
    "date": Time(mjd, format="mjd").iso,
    "wave_um": [m[2] for m in meas],
    "bw_um": [m[3] for m in meas],
    "x": [m[0] for m in meas],
    "y": [m[1] for m in meas],
    "key": keys,
})
idx.sort("mjd")

# Visit windows: SPHEREx sweeps past a spot, then leaves for months. Split on gaps > 20 days.
t = np.asarray(idx["mjd"])
win = np.concatenate([[0], np.cumsum(np.diff(t) > 20)])
idx["window"] = win
idx.write(out / "index.csv", overwrite=True)
print("\nVisit windows (one per sky survey pass):")
for w in np.unique(win):
    s = idx[win == w]
    print(f"  #{w}: {s['date'][0][:10]} -> {s['date'][-1][:10]}  {len(s):3d} images  "
          f"{s['wave_um'].min():.2f}-{s['wave_um'].max():.2f} um")

# Time-zoom feasibility: time gaps between image pairs whose wavelengths match within tol.
wl = np.asarray(idx["wave_um"])
dt = np.abs(t[:, None] - t[None, :])
same = (np.abs(wl[:, None] - wl[None, :]) / wl[:, None] < args.tol) & (dt > 0)
gaps = dt[np.triu(same)]
bins = [(0, 1 / 24, "< 1 hour"), (1 / 24, 1, "1 hour - 1 day"), (1, 30, "1 - 30 days"),
        (30, 250, "1 - 8 months"), (250, 1e9, "> 8 months")]
print(f"\nPairs at matching wavelength (within {args.tol:.0%}), by time gap:")
for lo, hi, label in bins:
    print(f"  {label:15s} {np.sum((gaps >= lo) & (gaps < hi)):6d}")
if len(gaps):
    print(f"  shortest gap: {gaps.min() * 24 * 60:.1f} min")

print("\nImages per detector:", dict(sorted(Counter(dets).items())))

fig, ax = plt.subplots(figsize=(10, 4.5))
sc = ax.scatter(idx["mjd"] - idx["mjd"][0], idx["wave_um"], c=idx["detector"], cmap="viridis", s=12)
ax.set_xlabel(f"days since {idx['date'][0][:10]}")
ax.set_ylabel("wavelength at target (um)")
ax.set_title(f"SPHEREx looks at {args.target}: when and at which wavelength")
fig.colorbar(sc, label="detector")
fig.tight_layout()
fig.savefig(out / "epochs.png", dpi=130)
print(f"\nwrote {out / 'index.csv'} and {out / 'epochs.png'}")
