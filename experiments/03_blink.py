"""Experiment 3: blink, difference, and stretch tests on the stamps from 02_stamps.py.

    python 03_blink.py M51

Writes into data/<target>/:
  stretches.png      same frame under 3 stretches (what reads best for non-astronomers?)
  blink_frames.gif   every exposure in time order (hours/days time-zoom)
  blink_passes.gif   one median frame per survey pass (months time-zoom)
  difference.png     last pass minus first pass on a common grid (static sky -> noise only?)
"""
import argparse
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.visualization import (AsinhStretch, ImageNormalize, LinearStretch,
                                   MinMaxInterval, PercentileInterval, ZScaleInterval)
from astropy.wcs import WCS
from matplotlib.animation import FuncAnimation, PillowWriter
from reproject import reproject_interp

import spx

warnings.filterwarnings("ignore", "All-NaN slice")  # corners outside every stamp

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--fps", type=float, default=2)
args = ap.parse_args()

c = spx.target_coord(args.target)
out = spx.DATA / spx.slug(args.target)
sel = Table.read(out / "stamps.csv")
sel.sort("mjd")

# Common north-up grid centred on the target. Each epoch has a different roll angle and
# sub-pixel offset, so blinking or subtracting raw stamps would mostly show the rotation.
# Crop by sqrt(2): a rotated square stamp only fully covers its inscribed square.
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
        arr, _ = reproject_interp((img, WCS(h[0].header)), grid, shape_out=(n, n))
    frames.append(arr)
frames = np.array(frames)
labels = [f"{r['date'][:16]}  {r['wave_um']:.2f} um  D{r['detector']}" for r in sel]

passes = np.unique(sel["window"])
pass_frames = np.array([np.nanmedian(frames[sel["window"] == w], axis=0) for w in passes])
pass_labels = [f"pass {w}: {sel['date'][sel['window'] == w][0][:10]}  "
               f"({np.sum(sel['window'] == w)} frames)" for w in passes]

# One shared normalisation, so brightness changes between frames are real, not re-scaling.
ref = np.nanmedian(frames, axis=0)
norm = ImageNormalize(ref, interval=PercentileInterval(99.5), stretch=AsinhStretch(0.1))

fig, axes = plt.subplots(1, 3, figsize=(12, 4.3))
for ax, (name, interval, stretch) in zip(axes, [
        ("linear, min-max", MinMaxInterval(), LinearStretch()),
        ("linear, zscale", ZScaleInterval(), LinearStretch()),
        ("asinh, 99.5%", PercentileInterval(99.5), AsinhStretch(0.1))]):
    ax.imshow(ref, origin="lower", cmap="gray",
              norm=ImageNormalize(ref, interval=interval, stretch=stretch))
    ax.set_title(name)
    ax.axis("off")
fig.suptitle(f"{args.target}: median of {len(frames)} frames at {np.median(sel['wave_um']):.2f} um")
fig.tight_layout()
fig.savefig(out / "stretches.png", dpi=110)
plt.close(fig)


def gif(stack, titles, path):
    fig, ax = plt.subplots(figsize=(5, 5.3))
    im = ax.imshow(stack[0], origin="lower", cmap="gray", norm=norm)
    ax.plot(n / 2 - 0.5, n / 2 - 0.5, "+", color="tab:red", ms=14)
    title = ax.set_title(titles[0], fontsize=9)
    ax.axis("off")

    def step(i):
        im.set_data(stack[i])
        title.set_text(titles[i])
        return im, title

    FuncAnimation(fig, step, frames=len(stack)).save(path, writer=PillowWriter(fps=args.fps))
    plt.close(fig)


gif(frames, labels, out / "blink_frames.gif")
gif(pass_frames, pass_labels, out / "blink_passes.gif")

diff = pass_frames[-1] - pass_frames[0]
lim = np.nanpercentile(np.abs(diff), 99)
fig, axes = plt.subplots(1, 3, figsize=(12, 4.3))
for ax, img, t in zip(axes, [pass_frames[0], pass_frames[-1]], [pass_labels[0], pass_labels[-1]]):
    ax.imshow(img, origin="lower", cmap="gray", norm=norm)
    ax.set_title(t, fontsize=9)
    ax.axis("off")
axes[2].imshow(diff, origin="lower", cmap="RdBu_r", vmin=-lim, vmax=lim)
axes[2].set_title("difference (red = brighter later)", fontsize=9)
axes[2].axis("off")
fig.tight_layout()
fig.savefig(out / "difference.png", dpi=110)

noise = np.nanstd(diff) / np.sqrt(2)
print(f"{len(frames)} frames, {len(passes)} passes; difference rms {np.nanstd(diff):.3g} MJy/sr "
      f"(per-pass noise ~{noise:.3g}); peak |diff| {np.nanmax(np.abs(diff)):.3g}")
print(f"wrote stretches.png, blink_frames.gif, blink_passes.gif, difference.png in {out}")
