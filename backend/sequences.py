"""Time-zoom sequences: choose which SPHEREx frames to show, fetch them in parallel, cache them.

A sequence is a list of "entries" (frames shown to the user). Each entry is one exposure, or for
the months/year levels a median of several exposures from one survey pass. All entries share a
north-up grid centred on the target, so blinking and differencing compare like with like.
"""
import hashlib
import json
import math
import os
import shutil
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.convolution import Gaussian2DKernel, interpolate_replace_nans
from astropy.wcs import WCS
from reproject import reproject_interp

from . import config, spherex

CACHE = config.CACHE
ZOOMS = ("hours", "days", "months", "year")
# Hours mode is about motion, so it accepts a wider wavelength spread and balances each frame.
TOLERANCE = {"hours": 0.10, "days": 0.02, "months": 0.02, "year": 0.02}
MAX_ENTRIES = 16
MEMBERS_PER_PASS = 5

_pool = ThreadPoolExecutor(8)  # more than 8 parallel S3 reads gave no gain in the sandbox
_searches = threading.BoundedSemaphore(4)  # archive searches at once; each takes ~1.5-12 s
_lock = threading.Lock()
_create_lock = threading.Lock()  # one thread at a time writes a new sequence's meta.json
_sequences = {}  # in memory: the ones downloading plus up to KEEP_IN_MEMORY idle ones
_coverage = OrderedDict()
KEEP_IN_MEMORY = 256
COVERAGE_IN_MEMORY = 128


class Busy(RuntimeError):
    """The server is at its download or search limit; the client should retry shortly."""


def _hash(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj))
    try:
        tmp.replace(path)
    except PermissionError:  # Windows: another thread holds the same file; its content is the same
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise


# --- coverage ----------------------------------------------------------------------------------
def coverage(ra, dec, collection="spherex_qr2"):
    """All images at (ra, dec) plus a summary: passes and a suggested wavelength. Cached on disk."""
    ra, dec = round(ra % 360, 5), round(dec, 5)
    key = _hash("cov", ra, dec, collection)
    with _lock:
        if key in _coverage:
            _coverage.move_to_end(key)
            return _coverage[key]
    path = CACHE / "coverage" / f"{key}.json"
    cov = _read_json(path)
    if cov is None:
        if not _searches.acquire(timeout=60):
            raise Busy("too many archive searches are running: try again in a minute")
        try:
            images = spherex.search(ra, dec, collection)
        finally:
            _searches.release()
        passes = []
        for p in sorted({im["pass"] for im in images}):
            members = [im for im in images if im["pass"] == p]
            passes.append({"pass": p, "start": members[0]["date"], "end": members[-1]["date"],
                           "count": len(members)})
        cov = {"ra": ra, "dec": dec, "collection": collection, "images": images, "passes": passes}
        _write_json(path, cov)
    cov["suggested"] = {z: suggest_wave(cov["images"], z) for z in ZOOMS}
    with _lock:
        _coverage[key] = cov
        while len(_coverage) > COVERAGE_IN_MEMORY:
            _coverage.popitem(last=False)
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
        os.utime(path)  # recently used: keep it when the cache is pruned
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
def _downloading(seq):
    return any(s in ("pending", "loading") for s in seq["status"])


def downloading():
    """How many sequences are downloading now."""
    with _lock:
        return sum(map(_downloading, _sequences.values()))


def _remember(seq_id, seq):
    """Keep a sequence in memory; forget the longest-idle finished ones beyond KEEP_IN_MEMORY.
    Call with _lock held. Forgotten sequences are reloaded from disk by get()."""
    _sequences[seq_id] = seq
    extra = len(_sequences) - KEEP_IN_MEMORY
    if extra > 0:
        idle = sorted((s["used"], k) for k, s in _sequences.items() if not _downloading(s))
        for _, k in idle[:extra]:
            del _sequences[k]


def start(ra, dec, zoom, wave=None, n=48, t_min=None, t_max=None, tol=None, collection="spherex_qr2",
          max_active=None):
    """Create (or reuse) a sequence and start fetching its frames in the background.
    With max_active, raise Busy instead of starting a download when that many are already running."""
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
    path = CACHE / "sequences" / seq_id / "meta.json"
    with _create_lock:
        meta = _read_json(path)
        if meta is None:
            entries = select(cov["images"], wave, zoom, t_min, t_max, tol)
            if not entries:
                raise LookupError("no frames at this wavelength and time range")
            meta = {"id": seq_id, "ra": ra, "dec": dec, "zoom": zoom, "wave": wave, "n": n,
                    "scale": spherex.PIXEL_SCALE, "t_min": t_min, "t_max": t_max, "tol": tol,
                    "balanced": zoom == "hours" or (tol or 0) > 0.03,
                    "entries": [{k: v for k, v in e.items() if k != "members"}
                                | {"members": [m["id"] for m in e["members"]]} for e in entries]}
            _write_json(path, meta)
    return _activate(seq_id, meta, lambda: cov["images"], max_active)


def _activate(seq_id, meta, images, max_active=None):
    """Put a sequence in memory and queue downloads of its missing frames. `images` is called
    only if frames are missing; it returns the coverage images the entries were chosen from."""
    seq_dir = CACHE / "sequences" / seq_id
    seq = {"meta": meta, "status": ["pending"] * len(meta["entries"]), "errors": {}, "dir": seq_dir,
           "used": time.time()}
    todo = []
    for i in range(len(meta["entries"])):
        if (seq_dir / f"{i}.npy").exists():
            seq["status"][i] = "ready"
        else:
            todo.append(i)
    lookup = {im["id"]: im for im in images()} if todo else {}
    with _lock:
        if seq_id in _sequences:
            return _sequences[seq_id]
        if todo and max_active and sum(map(_downloading, _sequences.values())) >= max_active:
            raise Busy("the server is busy downloading other views: try again shortly")
        _remember(seq_id, seq)
    for i in todo:
        members = [lookup[m] for m in meta["entries"][i]["members"] if m in lookup]
        _pool.submit(_build_entry, seq, i, members)
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
        seq["errors"][i] = "; ".join(errors)[:300] or "its images are no longer listed by the archive"
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
        # Load by id: re-deriving the id from the stored parameters is not guaranteed to match.
        seq = _activate(seq_id, meta, lambda: coverage(meta["ra"], meta["dec"])["images"])
    seq["used"] = time.time()
    return seq


def summary(seq):
    return seq["meta"] | {"status": seq["status"], "errors": seq["errors"]}


def entry_array(seq, i):
    path = seq["dir"] / f"{i}.npy"
    if seq["status"][i] != "ready" or not path.exists():
        return None
    return np.load(path)


def entry_bytes(seq, i):
    arr = entry_array(seq, i)
    return None if arr is None else arr.astype("<f4").tobytes()


_hunt_pool = {"time": 0.0, "metas": []}


def cached_sequences(max_age=60):
    """Fully downloaded Hours and Days sequences on disk (5+ frames), for Hunt mode.
    The disk is rescanned at most every max_age seconds."""
    if time.time() - _hunt_pool["time"] < max_age:
        return _hunt_pool["metas"]
    out = []
    for meta_path in (CACHE / "sequences").glob("*/meta.json"):
        meta = _read_json(meta_path)
        ready = sum((meta_path.parent / f"{i}.npy").exists() for i in range(len(meta["entries"])))
        if meta["zoom"] in ("hours", "days") and ready >= 5 and ready == len(meta["entries"]):
            out.append(meta)
    _hunt_pool.update(time=time.time() if out else 0.0, metas=out)
    return out


# --- cache size --------------------------------------------------------------------------------
def pin(seq_ids):
    """Never prune these sequences (tour stops and precached Hunt patches)."""
    path = CACHE / "pinned.json"
    _write_json(path, sorted(set(_read_json(path) or []) | set(seq_ids)))


def _bytes(path):
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size


last_size = {"bytes": None, "time": None}


def prune_cache(max_bytes, keep=0.9):
    """If the cache is over max_bytes, delete the least recently used frames, searches and
    sequences until it is under keep * max_bytes. Pinned and downloading sequences stay.
    Returns {"before", "after"} in bytes and the number of items deleted."""
    total = _bytes(CACHE) if CACHE.exists() else 0
    before, deleted = total, 0
    if max_bytes and total > max_bytes:
        pinned = set(_read_json(CACHE / "pinned.json") or [])
        with _lock:
            mem = dict(_sequences)
        items = []  # (last used, path)
        for sub, pattern in (("frames", "*.npy"), ("coverage", "*.json")):
            items += [(f.stat().st_mtime, f) for f in (CACHE / sub).glob(pattern)]
        for d in (CACHE / "sequences").glob("*"):
            if d.name in pinned or not (d / "meta.json").exists():
                continue
            seq = mem.get(d.name)
            items.append((max((d / "meta.json").stat().st_mtime, seq["used"] if seq else 0), d))
        for _, path in sorted(items, key=lambda t: t[0]):
            if total <= keep * max_bytes:
                break
            if path.is_dir():
                with _lock:
                    seq = _sequences.get(path.name)
                    if seq is not None and _downloading(seq):
                        continue
                    _sequences.pop(path.name, None)
                size = _bytes(path)
                shutil.rmtree(path, ignore_errors=True)
            else:
                size = path.stat().st_size
                path.unlink(missing_ok=True)
            total -= size
            deleted += 1
    last_size.update(bytes=total, time=time.time())
    return {"before": before, "after": total, "deleted": deleted}
