"""Time-zoom sequences: choose which SPHEREx frames to show, fetch them in parallel, cache them.

A sequence is a list of "entries" (frames shown to the user). Each entry is one exposure, or for
the months/year levels a median of several exposures from one survey pass. All entries share a
north-up grid centred on the target, so blinking and differencing compare like with like.
"""
import hashlib
import json
import math
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from astropy.convolution import Gaussian2DKernel, interpolate_replace_nans
from astropy.wcs import WCS
from reproject import reproject_interp

from . import spherex

CACHE = Path(__file__).resolve().parent.parent / "cache"
ZOOMS = ("hours", "days", "months", "year")
# Hours mode is about motion, so it accepts a wider wavelength spread and balances each frame.
TOLERANCE = {"hours": 0.10, "days": 0.02, "months": 0.02, "year": 0.02}
MAX_ENTRIES = 16
MEMBERS_PER_PASS = 5

_pool = ThreadPoolExecutor(8)  # more than 8 parallel S3 reads gave no gain in the sandbox
_lock = threading.Lock()
_sequences = {}
_coverage = {}


def _hash(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)


# --- coverage ----------------------------------------------------------------------------------
def coverage(ra, dec, collection="spherex_qr2"):
    """All images at (ra, dec) plus a summary: passes and a suggested wavelength. Cached on disk."""
    ra, dec = round(ra % 360, 5), round(dec, 5)
    key = _hash("cov", ra, dec, collection)
    if key in _coverage:
        return _coverage[key]
    path = CACHE / "coverage" / f"{key}.json"
    cov = _read_json(path)
    if cov is None:
        images = spherex.search(ra, dec, collection)
        passes = []
        for p in sorted({im["pass"] for im in images}):
            members = [im for im in images if im["pass"] == p]
            passes.append({"pass": p, "start": members[0]["date"], "end": members[-1]["date"],
                           "count": len(members)})
        cov = {"ra": ra, "dec": dec, "collection": collection, "images": images, "passes": passes}
        _write_json(path, cov)
    cov["suggested"] = {z: suggest_wave(cov["images"], z) for z in ZOOMS}
    _coverage[key] = cov
    return cov


def suggest_wave(images, zoom="months"):
    """Best wavelength for a zoom level; ties go to shorter wavelengths (sharper, more stars).
    hours: most frames in one 24-hour window. days: most frames in one survey pass.
    months/year: most passes covered, then frames (capped so short wavelengths can win)."""
    if not images:
        return None
    waves = np.array([im["wave"] for im in images])
    passes = np.array([im["pass"] for im in images])
    mjd = np.array([im["mjd"] for im in images])
    tol = TOLERANCE[zoom]

    def score(w):
        m = np.abs(waves - w) / w < tol
        if not m.any():
            return 0, 0, -w
        if zoom == "hours":
            t = mjd[m]
            return int(max(np.sum((t >= ti) & (t < ti + 1)) for ti in t)), 0, -w
        if zoom == "days":
            return int(np.bincount(passes[m]).max()), 0, -w
        return len(set(passes[m])), min(int(m.sum()), 4), -w

    return float(max(np.unique(np.round(waves, 2)), key=score))


# --- choosing frames ---------------------------------------------------------------------------
def _spread(items, k):
    if len(items) <= k:
        return items
    return [items[i] for i in np.unique(np.linspace(0, len(items) - 1, k).round().astype(int))]


def select(images, wave, zoom, t_min=None, t_max=None, tol=None):
    """Entries for one time-zoom level: [{label, members: [image], ...}]."""
    pool = [im for im in images
            if (t_min is None or im["mjd"] >= t_min) and (t_max is None or im["mjd"] <= t_max)]
    tol = tol or TOLERANCE[zoom]
    matched = [im for im in pool if abs(im["wave"] - wave) / wave < tol and im["edge"] > 40]
    if not matched:
        return []

    if zoom == "hours":
        # Densest 24-hour window.
        t = np.array([im["mjd"] for im in matched])
        counts = [np.sum((t >= ti) & (t < ti + 1)) for ti in t]
        i0 = int(np.argmax(counts))
        chosen = [im for im in matched if t[i0] <= im["mjd"] < t[i0] + 1]
        return [_single(im) for im in _spread(chosen, MAX_ENTRIES)]

    if zoom == "days":
        by_pass = {}
        for im in matched:
            by_pass.setdefault(im["pass"], []).append(im)
        best = max(by_pass.values(), key=len)
        return [_single(im) for im in _spread(best, MAX_ENTRIES)]

    by_pass = {}
    for im in matched:
        by_pass.setdefault(im["pass"], []).append(im)
    passes = sorted(by_pass)
    if zoom == "year":
        passes = [passes[0], passes[-1]] if len(passes) > 1 else passes
    entries = []
    for p in passes:
        members = sorted(by_pass[p], key=lambda im: abs(im["wave"] - wave))[:MEMBERS_PER_PASS]
        members.sort(key=lambda im: im["mjd"])
        mjd = float(np.mean([m["mjd"] for m in members]))
        entries.append({
            "label": f"Survey pass {p + 1}",
            "mjd": mjd,
            "date": members[len(members) // 2]["date"],
            "wave": round(float(np.mean([m["wave"] for m in members])), 3),
            "det": members[0]["det"],
            "pass": p,
            "members": members,
        })
    return entries


def _single(im):
    return {"label": im["id"], "mjd": im["mjd"], "date": im["date"], "wave": im["wave"],
            "det": im["det"], "pass": im["pass"], "members": [im]}


# --- pixels ------------------------------------------------------------------------------------
def grid_wcs(ra, dec, n):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [n / 2 + 0.5, n / 2 + 0.5]
    w.wcs.cdelt = [-spherex.PIXEL_SCALE / 3600, spherex.PIXEL_SCALE / 3600]
    return w


_fill_kernel = Gaussian2DKernel(1.0)
# Saturated cores leave holes too big to fill; they stay blank, which is fine.
warnings.filterwarnings("ignore", message="nan_treatment='interpolate'")


def frame(im, ra, dec, n):
    """One exposure on the common grid, cached as .npy. Hidden pixels are filled from neighbours."""
    path = CACHE / "frames" / f"{_hash(im['key'], f'{ra:.5f}', f'{dec:.5f}', n)}.npy"
    if path.exists():
        return np.load(path)
    half = math.ceil(n / math.sqrt(2)) + 3  # a rotated stamp must still cover the whole grid
    img, w = spherex.read_stamp(im["key"], ra, dec, half)
    # Fill hidden pixels on the native grid first: reprojection would mark them as "no coverage".
    img = interpolate_replace_nans(img, _fill_kernel)
    arr, cover = reproject_interp((img, w), grid_wcs(ra, dec, n), shape_out=(n, n))
    arr[cover == 0] = np.nan
    arr = arr.astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, arr)
    return arr


# --- sequence jobs -----------------------------------------------------------------------------
def start(ra, dec, zoom, wave=None, n=48, t_min=None, t_max=None, tol=None, collection="spherex_qr2"):
    """Create (or reuse) a sequence and start fetching its frames in the background."""
    if zoom not in ZOOMS:
        raise ValueError(f"zoom must be one of {ZOOMS}")
    cov = coverage(ra, dec, collection)
    ra, dec = cov["ra"], cov["dec"]
    wave = round(float(wave), 3) if wave else cov["suggested"][zoom]
    if wave is None:
        raise LookupError("SPHEREx has no images of this position yet")
    seq_id = _hash("seq", ra, dec, zoom, wave, n, t_min, t_max, tol, collection)
    with _lock:
        if seq_id in _sequences:
            return _sequences[seq_id]
    seq_dir = CACHE / "sequences" / seq_id
    meta = _read_json(seq_dir / "meta.json")
    if meta is None:
        entries = select(cov["images"], wave, zoom, t_min, t_max, tol)
        if not entries:
            raise LookupError("no frames at this wavelength and time range")
        meta = {"id": seq_id, "ra": ra, "dec": dec, "zoom": zoom, "wave": wave, "n": n,
                "scale": spherex.PIXEL_SCALE, "t_min": t_min, "t_max": t_max, "tol": tol,
                "balanced": zoom == "hours" or (tol or 0) > 0.03,
                "entries": [{k: v for k, v in e.items() if k != "members"}
                            | {"members": [m["id"] for m in e["members"]]} for e in entries]}
        _write_json(seq_dir / "meta.json", meta)
        member_lookup = {m["id"]: m for e in entries for m in e["members"]}
    else:
        member_lookup = {im["id"]: im for im in cov["images"]}
    seq = {"meta": meta, "status": ["pending"] * len(meta["entries"]), "errors": {}, "dir": seq_dir}
    with _lock:
        if seq_id in _sequences:
            return _sequences[seq_id]
        _sequences[seq_id] = seq
    for i, e in enumerate(meta["entries"]):
        if (seq_dir / f"{i}.npy").exists():
            seq["status"][i] = "ready"
        else:
            _pool.submit(_build_entry, seq, i, [member_lookup[m] for m in e["members"]])
    return seq


def _build_entry(seq, i, members):
    meta = seq["meta"]
    seq["status"][i] = "loading"
    arrays, errors = [], []
    for im in members:
        try:
            arrays.append(frame(im, meta["ra"], meta["dec"], meta["n"]))
        except Exception as e:  # one bad exposure should not sink a pass composite
            errors.append(f"{im['id']}: {e}")
    if not arrays:
        seq["status"][i] = "failed"
        seq["errors"][i] = "; ".join(errors)[:300]
        return
    arr = arrays[0] if len(arrays) == 1 else np.nanmedian(np.stack(arrays), axis=0).astype(np.float32)
    np.save(seq["dir"] / f"{i}.npy", arr)
    seq["status"][i] = "ready"


def get(seq_id):
    with _lock:
        seq = _sequences.get(seq_id)
    if seq is None:
        meta = _read_json(CACHE / "sequences" / seq_id / "meta.json")
        if meta is None:
            return None
        seq = start(meta["ra"], meta["dec"], meta["zoom"], meta["wave"], meta["n"],
                    meta["t_min"], meta["t_max"], meta.get("tol"))
    return seq


def summary(seq):
    return seq["meta"] | {"status": seq["status"], "errors": seq["errors"]}


def entry_bytes(seq, i):
    path = seq["dir"] / f"{i}.npy"
    if seq["status"][i] != "ready" or not path.exists():
        return None
    return np.load(path).astype("<f4").tobytes()


def cached_sequences(min_ready=5, zooms=("hours", "days")):
    """Fully downloaded sequences on disk, for Hunt mode."""
    out = []
    for meta_path in (CACHE / "sequences").glob("*/meta.json"):
        meta = _read_json(meta_path)
        ready = sum((meta_path.parent / f"{i}.npy").exists() for i in range(len(meta["entries"])))
        if meta["zoom"] in zooms and ready >= min_ready and ready == len(meta["entries"]):
            out.append(meta)
    return out
