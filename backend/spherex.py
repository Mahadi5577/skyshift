"""SPHEREx data access: image search, wavelength at a sky position, and small reads from S3.

Design notes (measured in the sandbox, see sandbox/FINDINGS.md):
  * Search is one SIA request over plain HTTP. The wavelength each image saw at the target comes
    from the image's corner polygon (s_region) plus the per-detector WCS-WAVE table: max error 0.2%,
    with no per-image header downloads.
  * Pixels come from the public S3 bucket via byte-range reads (256 KB blocks). Only the IMAGE
    and FLAGS layers are read; the smooth zodiacal background is removed with a median instead.
"""
import io
import json
import threading
import time
from pathlib import Path

import numpy as np
import requests
from astropy import log
from astropy.io import fits, votable
from astropy.time import Time
from astropy.wcs import WCS
from scipy.interpolate import RegularGridInterpolator

log.setLevel("WARNING")

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
S3_BUCKET = "nasa-irsa-spherex"
PIXEL_SCALE = 6.15  # arcsec per pixel
NPIX = 2040
PASS_GAP_DAYS = 20
WAVE_DIR = Path(__file__).parent / "wave_tables"

# FLAGS bits hidden for display. PERSIST and OUTLIER stay visible on purpose: both were seen on
# real asteroids. SOURCE (bit 21) just marks known sources.
FLAG_BITS = {"TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "PHANTOM": 4, "NONFUNC": 6,
             "MISSING_DATA": 9, "HOT": 10, "COLD": 11, "NONLINEAR": 15}
HIDE_MASK = sum(1 << b for b in FLAG_BITS.values())

_local = threading.local()


def _session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def http_get(url, retries=4, timeout=120, **kwargs):
    """GET with a kept-alive connection per thread and retries for flaky long-haul links."""
    for attempt in range(retries):
        try:
            r = _session().get(url, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == retries - 1 or (isinstance(e, requests.HTTPError) and r.status_code < 500):
                raise
            time.sleep(2 ** attempt)


# --- wavelength --------------------------------------------------------------------------------
_wave_interp = {}


def wave_at(det, x, y):
    """Wavelength (um) seen by detector `det` at 0-based pixel (x, y), from the WCS-WAVE table."""
    if det not in _wave_interp:
        with fits.open(WAVE_DIR / f"wcs_wave_D{det}.fits") as h:
            d = h[1].data
            gx, gy, v = (np.asarray(d[c][0], float) for c in ("X", "Y", "VALUES"))
        _wave_interp[det] = RegularGridInterpolator(
            (gy - 1, gx - 1), v.reshape(len(gy), len(gx), 2)[..., 0], bounds_error=False, fill_value=None)
    return float(_wave_interp[det]([[y, x]])[0])


def _tan(ra, dec, ra0, dec0):
    ra, dec, ra0, dec0 = map(np.radians, (ra, dec, ra0, dec0))
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    x = np.cos(dec) * np.sin(ra - ra0) / cosc
    y = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cosc
    return np.degrees(x), np.degrees(y)


_CORNER_PIX = np.array([[0, 0], [NPIX - 1, 0], [NPIX - 1, NPIX - 1], [0, NPIX - 1]], float)


def pixel_from_region(s_region, s_ra, s_dec, ra, dec):
    """Approximate pixel (x, y) of (ra, dec) from the image's corner polygon (~6 px accuracy)."""
    v = [float(t) for t in s_region.replace("POLYGON", "").replace("ICRS", "").split()]
    cra, cdec = np.array(v[0::2])[:4], np.array(v[1::2])[:4]
    px, py = _tan(cra, cdec, s_ra, s_dec)
    a = np.c_[px, py, np.ones(4)]
    cx = np.linalg.lstsq(a, _CORNER_PIX[:, 0], rcond=None)[0]
    cy = np.linalg.lstsq(a, _CORNER_PIX[:, 1], rcond=None)[0]
    tx, ty = _tan(ra, dec, s_ra, s_dec)
    return float(cx @ [tx, ty, 1]), float(cy @ [tx, ty, 1])


# --- search ------------------------------------------------------------------------------------
def search(ra, dec, collection="spherex_qr2"):
    """Every image covering (ra, dec): time, detector, wavelength at the target, survey pass."""
    r = http_get(SIA_URL, params={"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} 0.003",
                                  "RESPONSEFORMAT": "VOTABLE"})
    rows = votable.parse(io.BytesIO(r.content)).get_first_table().to_table(use_names_over_ids=True)
    images = []
    for row in rows:
        det = int(str(row["energy_bandpassname"]).split("-D")[-1])
        x, y = pixel_from_region(str(row["s_region"]), float(row["s_ra"]), float(row["s_dec"]), ra, dec)
        mjd = (float(row["t_min"]) + float(row["t_max"])) / 2
        images.append({
            "id": f"{row['obs_id']}_D{det}",
            "det": det,
            "mjd": mjd,
            "date": Time(mjd, format="mjd").isot[:19] + "Z",
            "wave": round(wave_at(det, x, y), 4),
            "edge": round(float(min(x, y, NPIX - 1 - x, NPIX - 1 - y)), 1),
            "key": json.loads(str(row["cloud_access"]))["aws"]["key"],
        })
    images.sort(key=lambda im: im["mjd"])
    p = 0
    for i, im in enumerate(images):
        if i and im["mjd"] - images[i - 1]["mjd"] > PASS_GAP_DAYS:
            p += 1
        im["pass"] = p
    return images


# --- pixels ------------------------------------------------------------------------------------
def open_s3(key, block=256 * 1024):
    return fits.open(f"s3://{S3_BUCKET}/{key}", use_fsspec=True, lazy_load_hdus=True,
                     fsspec_kwargs={"anon": True, "default_block_size": block})


def read_stamp(key, ra, dec, half):
    """(2*half)^2 stamp around (ra, dec): background-subtracted IMAGE with hidden flags set to NaN,
    plus its WCS. Raises ValueError if the position is off the detector."""
    with open_s3(key) as h:
        hdr = h["IMAGE"].header
        w = WCS(hdr)
        x, y = w.world_to_pixel_values(ra, dec)
        xi, yi = int(round(float(x))), int(round(float(y)))
        y0, y1 = max(yi - half, 0), min(yi + half, hdr["NAXIS2"])
        x0, x1 = max(xi - half, 0), min(xi + half, hdr["NAXIS1"])
        if y1 - y0 < 4 or x1 - x0 < 4:
            raise ValueError("target is off the detector")
        sl = (slice(y0, y1), slice(x0, x1))
        img = np.asarray(h["IMAGE"].section[sl], dtype=np.float32)
        flags = np.asarray(h["FLAGS"].section[sl])
    img[(flags & HIDE_MASK) != 0] = np.nan
    img -= np.nanmedian(img)
    return img, w[sl]
