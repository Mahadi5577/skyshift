"""Experiment 7: plant fake movers in real SPHEREx frames. How faint can a mover be and still be found?

Needs stamps from 02_stamps.py for the target.

    python 07_inject.py "180,0"

For several brightness levels (peak signal-to-noise per frame), plants a moving point source along
random straight tracks, then asks two questions:
  * automatic: does a matched filter on (frame - median of all frames) find it at >= 5 sigma?
  * by eye: inject_panels.png shows the same tracks for a human to judge.

Writes data/<target>/inject_panels.png, inject_snr5.gif, inject_results.csv.
"""
import argparse
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.convolution import Gaussian2DKernel, convolve
from astropy.io import fits
from astropy.table import Table
from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval
from astropy.wcs import WCS
from matplotlib.animation import FuncAnimation, PillowWriter
from reproject import reproject_interp

import spx

warnings.filterwarnings("ignore", "All-NaN slice")

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--trials", type=int, default=30, help="random tracks per brightness level")
ap.add_argument("--motion", type=float, default=8, help="track length over the sequence, pixels")
ap.add_argument("--seed", type=int, default=1)
args = ap.parse_args()
rng = np.random.default_rng(args.seed)

c = spx.target_coord(args.target)
out = spx.DATA / spx.slug(args.target)
sel = Table.read(out / "stamps.csv")
sel.sort("mjd")

n = int(max(fits.getheader(out / "stamps" / f)["NAXIS1"] for f in sel["file"]) / np.sqrt(2))
grid = WCS(naxis=2)
grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
grid.wcs.crval = [c.ra.deg, c.dec.deg]
grid.wcs.crpix = [n / 2 + 0.5, n / 2 + 0.5]
grid.wcs.cdelt = [-spx.PIXEL_SCALE_ARCSEC / 3600, spx.PIXEL_SCALE_ARCSEC / 3600]

frames = []
for row in sel:
    with fits.open(out / "stamps" / row["file"]) as h:
        img = h[0].data.astype(float)
        img[spx.bad_mask(h["FLAGS"].data)] = np.nan
        frames.append(reproject_interp((img, WCS(h[0].header)), grid, shape_out=(n, n))[0])
frames = np.array(frames)
t = np.asarray(sel["mjd"])
tfrac = (t - t[0]) / (t[-1] - t[0])

template = np.nanmedian(frames, axis=0)
resid = frames - template
sigma = 1.4826 * np.nanmedian(np.abs(resid - np.nanmedian(resid, axis=(1, 2), keepdims=True)), axis=(1, 2))

# PSF width from the brightest star in the template (second moments in a 7x7 box).
inner = np.where(np.isfinite(template), template, -np.inf)
inner[:5, :], inner[-5:, :], inner[:, :5], inner[:, -5:] = -np.inf, -np.inf, -np.inf, -np.inf
py, px = np.unravel_index(np.argmax(inner), inner.shape)
box = template[py - 3:py + 4, px - 3:px + 4] - np.nanmedian(template)
yy, xx = np.mgrid[-3:4, -3:4]
w = np.clip(np.nan_to_num(box), 0, None)
psf_sigma = float(np.clip(np.sqrt((w * (xx ** 2 + yy ** 2)).sum() / w.sum() / 2), 0.6, 3.0))
print(f"{len(frames)} frames, {n}x{n} px; noise per frame median {np.median(sigma):.3g} MJy/sr; "
      f"PSF sigma ~{psf_sigma:.2f} px (FWHM {2.355 * psf_sigma:.1f} px)")

yy, xx = np.mgrid[0:n, 0:n]
kernel = Gaussian2DKernel(psf_sigma)


def track():
    x0, y0 = rng.uniform(n * 0.25, n * 0.75, 2)
    ang = rng.uniform(0, 2 * np.pi)
    return x0 + args.motion * tfrac * np.cos(ang), y0 + args.motion * tfrac * np.sin(ang)


def plant(xs, ys, snr):
    amp = snr * sigma
    blobs = np.exp(-((xx[None] - xs[:, None, None]) ** 2 + (yy[None] - ys[:, None, None]) ** 2)
                   / (2 * psf_sigma ** 2))
    return frames + amp[:, None, None] * blobs


def mf_map(stack):
    """Matched-filter significance map of each frame minus the median of all frames."""
    r = stack - np.nanmedian(stack, axis=0)
    maps = []
    for img in r:
        m = convolve(img, kernel, nan_treatment="interpolate", boundary="extend")
        s = 1.4826 * np.nanmedian(np.abs(m - np.nanmedian(m)))
        maps.append((m - np.nanmedian(m)) / s)
    return np.array(maps)


# False alarms: 5-sigma peaks in the real frames with nothing planted.
base = mf_map(frames)
edge = 4
core = np.zeros((n, n), bool)
core[edge:-edge, edge:-edge] = True
false_peaks = np.mean([np.sum((m > 5) & core) for m in base])
print(f"false 5-sigma pixels per frame with nothing planted: {false_peaks:.1f}")

levels = [2, 3, 5, 8, 12]
rows = []
for snr in levels:
    hit = []
    for _ in range(args.trials):
        xs, ys = track()
        maps = mf_map(plant(xs, ys, snr))
        for i, m in enumerate(maps):
            xi, yi = int(round(xs[i])), int(round(ys[i]))
            hit.append(np.nanmax(m[yi - 1:yi + 2, xi - 1:xi + 2]) >= 5)
    rows.append((snr, np.mean(hit)))
    print(f"  peak S/N {snr:3d} per frame: found in {np.mean(hit):6.1%} of frames")
Table(rows=rows, names=["snr_peak", "recovered"]).write(out / "inject_results.csv", overwrite=True)

# Panels for the human eye: first, middle and last frame plus last-minus-first, per level.
norm = ImageNormalize(template, interval=PercentileInterval(99.5), stretch=AsinhStretch(0.1))
cols = [0, len(frames) // 2, len(frames) - 1]
fig, axes = plt.subplots(len(levels), 4, figsize=(9, 2.3 * len(levels)))
for r_, snr in enumerate(levels):
    xs, ys = track()
    stack = plant(xs, ys, snr)
    for c_, i in enumerate(cols):
        ax = axes[r_, c_]
        ax.imshow(stack[i], origin="lower", cmap="gray", norm=norm)
        ax.plot(xs[i], ys[i], "o", mfc="none", mec="tab:orange", ms=12, mew=1)
        ax.set_title(f"S/N {snr}, frame {i + 1}" if c_ == 0 else f"frame {i + 1}", fontsize=8)
    d = stack[-1] - stack[0]
    lim = np.nanpercentile(np.abs(d), 99.5)
    axes[r_, 3].imshow(d, origin="lower", cmap="RdBu_r", vmin=-lim, vmax=lim)
    axes[r_, 3].set_title("last - first", fontsize=8)
for ax in axes.ravel():
    ax.axis("off")
fig.suptitle(f"Fake movers in real SPHEREx frames ({args.target}); ring = planted position", fontsize=10)
fig.tight_layout()
fig.savefig(out / "inject_panels.png", dpi=100)
plt.close(fig)

xs, ys = track()
stack = plant(xs, ys, 5)
fig, ax = plt.subplots(figsize=(5, 5.3))
im = ax.imshow(stack[0], origin="lower", cmap="gray", norm=norm)
title = ax.set_title("", fontsize=9)
ax.axis("off")


def step(i):
    im.set_data(stack[i])
    title.set_text(f"planted mover at S/N 5 (find it!)  frame {i + 1}/{len(stack)}")
    return im, title


FuncAnimation(fig, step, frames=len(stack)).save(out / "inject_snr5.gif", writer=PillowWriter(fps=3))
print(f"wrote inject_panels.png, inject_snr5.gif, inject_results.csv in {out}")
