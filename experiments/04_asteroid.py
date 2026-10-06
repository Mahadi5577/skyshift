"""Experiment 4: catch a known asteroid moving between SPHEREx exposures (hours/days time-zoom).

    python 04_asteroid.py 10                      # (10) Hygiea, numbered asteroid
    python 04_asteroid.py 433 --start 2025-05-01 --stop 2026-06-30
    python 04_asteroid.py 999 --major --spread --field 10     # Pluto: slow mover, days time-zoom

1. JPL Horizons gives the asteroid's sky position each day.
2. SIA (POS + TIME) finds SPHEREx images taken near that place and time.
3. Each image header confirms the asteroid really lands on the detector at the exposure time.
4. Picks the longest run of frames that fits in one small field, downloads stamps on a FIXED
   sky position, and animates them: stars stay put, the asteroid should walk across.

Writes data/ast_<id>/hits.csv, asteroid.gif, asteroid_panels.png.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table, unique, vstack
from astropy.time import Time
from astropy.visualization import ImageNormalize, AsinhStretch, PercentileInterval
from astropy.wcs import WCS
from astroquery.jplhorizons import Horizons
from matplotlib.animation import FuncAnimation, PillowWriter
from reproject import reproject_interp

import spx

ap = argparse.ArgumentParser()
ap.add_argument("id", help="Horizons small-body id, e.g. 10 for Hygiea")
ap.add_argument("--start", default="2025-05-01")
ap.add_argument("--stop", default="2026-06-30")
ap.add_argument("--collection", default="spherex_qr2")
ap.add_argument("--field", type=float, default=6.0, help="max motion shown, arcmin")
ap.add_argument("--max-frames", type=int, default=16)
ap.add_argument("--major", action="store_true", help="id is a major body (e.g. 999 = Pluto)")
ap.add_argument("--spread", action="store_true",
                help="spread frames evenly over the run's time span instead of taking the first ones")
ap.add_argument("--workers", type=int, default=8)
args = ap.parse_args()

out = spx.DATA / f"ast_{spx.slug(args.id)}"
(out / "stamps").mkdir(parents=True, exist_ok=True)

# Geocentric is fine: SPHEREx's low orbit shifts a main-belt asteroid by ~1", well under a pixel.
eph = Horizons(id=args.id, id_type=None if args.major else "smallbody", location="500",
               epochs={"start": args.start, "stop": args.stop, "step": "1d"}).ephemerides()
name = str(eph["targetname"][0])
emjd = Time(np.asarray(eph["datetime_jd"]), format="jd").mjd
ra_u = np.degrees(np.unwrap(np.radians(np.asarray(eph["RA"]))))
dec = np.asarray(eph["DEC"])
print(f"{name}: {len(eph)} daily positions, V {np.nanmin(eph['V']):.1f}-{np.nanmax(eph['V']):.1f}")


def where(mjd):
    return SkyCoord(np.interp(mjd, emjd, ra_u) % 360, np.interp(mjd, emjd, dec), unit="deg")


def day_query(i):
    # 0.3 deg radius covers ~a day of main-belt motion; the header check below is exact.
    return spx.query_images(ra_u[i] % 360, dec[i], radius_deg=0.3, collection=args.collection,
                            time_mjd=(emjd[i] - 0.5, emjd[i] + 0.5))


with ThreadPoolExecutor(args.workers) as pool:
    found = [t for t in pool.map(day_query, range(len(eph))) if len(t)]
if not found:
    raise SystemExit("no SPHEREx images near this asteroid in the date range")
cand = unique(vstack(found, metadata_conflicts="silent"), keys=["obs_id", "energy_bandpassname"])
cand["mjd"] = (np.asarray(cand["t_min"]) + np.asarray(cand["t_max"])) / 2
print(f"{len(cand)} candidate images; checking which really contain the asteroid...")


def check(row):
    pos = where(row["mjd"])
    hdr = spx.image_header(spx.s3_key(row))
    x, y = WCS(hdr).world_to_pixel_values(pos.ra.deg, pos.dec.deg)
    inside = 40 <= x < hdr["NAXIS1"] - 40 and 40 <= y < hdr["NAXIS2"] - 40
    det = int(row["energy_bandpassname"].split("-D")[-1])
    wl = spx.wavelength_at(hdr, spx.wave_table(det, spx.s3_key(row)), pos.ra.deg, pos.dec.deg)[2]
    return inside, pos.ra.deg, pos.dec.deg, wl, det


with ThreadPoolExecutor(args.workers) as pool:
    res = list(pool.map(check, cand))
hits = cand[np.array([r[0] for r in res], dtype=bool)]
hits["ast_ra"] = [r[1] for r in res if r[0]]
hits["ast_dec"] = [r[2] for r in res if r[0]]
hits["wave_um"] = [r[3] for r in res if r[0]]
hits["detector"] = [r[4] for r in res if r[0]]
hits["key"] = [spx.s3_key(r) for r in hits]
hits.sort("mjd")
hits["date"] = Time(hits["mjd"], format="mjd").iso
hits["obs_id", "detector", "date", "wave_um", "ast_ra", "ast_dec", "key"].write(
    out / "hits.csv", overwrite=True)
print(f"{len(hits)} images contain {name}:")
for r in hits:
    print(f"  {r['date'][:16]}  D{r['detector']}  {r['wave_um']:.2f} um")

# Longest run of frames whose asteroid positions all fit inside the field.
pos = SkyCoord(hits["ast_ra"], hits["ast_dec"], unit="deg")
best = (0, 0)
for i in range(len(hits)):
    j = i
    while j + 1 < len(hits) and pos[i].separation(pos[j + 1]) < args.field * u.arcmin:
        j += 1
    if j - i > best[1] - best[0]:
        best = (i, j)
run = hits[best[0]:best[1] + 1]
if args.spread and len(run) > args.max_frames:
    run = run[np.unique(np.linspace(0, len(run) - 1, args.max_frames).round().astype(int))]
run = run[:args.max_frames]
if len(run) < 2:
    raise SystemExit("no two frames close enough in time; try a larger --field")
run_pos = SkyCoord(run["ast_ra"], run["ast_dec"], unit="deg")
centre = SkyCoord(np.mean(run["ast_ra"]), np.mean(run["ast_dec"]), unit="deg")
span_h = (run["mjd"][-1] - run["mjd"][0]) * 24
motion = run_pos[0].separation(run_pos[-1]).arcsec
print(f"\nanimating {len(run)} frames over {span_h:.1f} h; asteroid moves {motion:.0f}\" "
      f"= {motion / spx.PIXEL_SCALE_ARCSEC:.1f} px")

n = int(motion / spx.PIXEL_SCALE_ARCSEC) + 30  # field fits the whole track plus margin
half = int(n / np.sqrt(2)) + 4                    # fetch bigger so rotation leaves no corners


def fetch(row):
    img, flags, w, _ = spx.read_stamp(row["key"], centre.ra.deg, centre.dec.deg, half)
    img = img.astype(float)
    img[spx.bad_mask(flags)] = np.nan
    return img, w


with ThreadPoolExecutor(args.workers) as pool:
    stamps = list(pool.map(fetch, run))

grid = WCS(naxis=2)
grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
grid.wcs.crval = [centre.ra.deg, centre.dec.deg]
grid.wcs.crpix = [n / 2 + 0.5, n / 2 + 0.5]
grid.wcs.cdelt = [-spx.PIXEL_SCALE_ARCSEC / 3600, spx.PIXEL_SCALE_ARCSEC / 3600]

frames = []
for img, w in stamps:
    arr, _ = reproject_interp((img, w), grid, shape_out=(n, n))
    # Wavelengths differ frame to frame, so scale each to its own background noise.
    med = np.nanmedian(arr)
    mad = 1.4826 * np.nanmedian(np.abs(arr - med))
    frames.append((arr - med) / mad)
frames = np.array(frames)
px = np.array(grid.world_to_pixel(run_pos)).T
norm = ImageNormalize(frames, interval=PercentileInterval(99.5), stretch=AsinhStretch(0.2))
labels = [f"{name}\n{r['date'][:16]} UT  {r['wave_um']:.2f} um" for r in run]

fig, ax = plt.subplots(figsize=(5.5, 6))
im = ax.imshow(frames[0], origin="lower", cmap="gray", norm=norm)
ax.plot(px[:, 0], px[:, 1], ":", color="tab:orange", lw=1)
ring, = ax.plot([], [], "o", mfc="none", mec="tab:orange", ms=18, mew=1.5)
title = ax.set_title(labels[0], fontsize=9)
ax.axis("off")


def step(i):
    im.set_data(frames[i])
    ring.set_data([px[i, 0]], [px[i, 1]])
    title.set_text(labels[i])
    return im, ring, title


FuncAnimation(fig, step, frames=len(frames)).save(out / "asteroid.gif", writer=PillowWriter(fps=2))
plt.close(fig)

k = min(len(frames), 4)
picks = np.linspace(0, len(frames) - 1, k).astype(int)
fig, axes = plt.subplots(1, k, figsize=(3.2 * k, 3.6))
for ax, i in zip(np.atleast_1d(axes), picks):
    ax.imshow(frames[i], origin="lower", cmap="gray", norm=norm)
    ax.plot(px[i, 0], px[i, 1], "o", mfc="none", mec="tab:orange", ms=16, mew=1.5)
    ax.set_title(labels[i].split("\n")[1], fontsize=8)
    ax.axis("off")
fig.suptitle(f"{name}: ring = JPL predicted position", fontsize=10)
fig.tight_layout()
fig.savefig(out / "asteroid_panels.png", dpi=110)
print(f"wrote {out / 'asteroid.gif'} and asteroid_panels.png")
