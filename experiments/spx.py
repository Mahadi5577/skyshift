"""Shared helpers for SPHEREx sandbox experiments (learning only, not SkyShift app code).

Findings baked in here (see README "Findings log"):
  * Raw SIA over HTTP takes ~1.5 s; astroquery's Irsa.query_sia took ~33 s for the same query.
  * IRSA cutouts ship the full 5 MB PSF cube, so each takes ~37 s on our test connection.
    Reading sections from the public S3 bucket with a 256 KB block size takes ~6 s and skips the PSF.
  * em_min/em_max in SIA rows give the whole detector's range. The wavelength at the target
    comes from the WCS-WAVE lookup table evaluated at the target's pixel position.
"""
import io
import json
import re
import threading
import time
from pathlib import Path

import numpy as np
import requests
from astropy import log
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits, votable
from astropy.wcs import WCS

log.setLevel("WARNING")  # silence the SIP "-SIP suffix" INFO spam on every WCS build

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
S3_BUCKET = "nasa-irsa-spherex"
S3_HTTP = f"https://{S3_BUCKET}.s3.us-east-1.amazonaws.com/"
DATA = Path(__file__).parent / "data"
PIXEL_SCALE_ARCSEC = 6.15

# FLAGS bit numbers, from MP_* keywords in the FLAGS header.
FLAG_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "PHANTOM": 4, "REFERENCE": 5,
    "NONFUNC": 6, "DICHROIC": 7, "MISSING_DATA": 9, "HOT": 10, "COLD": 11,
    "FULLSAMPLE": 12, "PHANMISS": 14, "NONLINEAR": 15, "PERSIST": 17,
    "OUTLIER": 19, "SOURCE": 21,
}
# OUTLIER is left out on purpose: a moving object can look like an outlier in a single frame.
BAD_FLAGS = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "PHANTOM", "NONFUNC",
             "MISSING_DATA", "HOT", "COLD", "NONLINEAR", "PERSIST")


_local = threading.local()


def _session():
    """One kept-alive connection per thread: a fresh TLS handshake costs ~4 round trips (~1 s from here)."""
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def _get(url, retries=4, timeout=120, **kwargs):
    """GET with retries: long-haul links to US servers drop connections now and then."""
    for attempt in range(retries):
        try:
            r = _session().get(url, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == retries - 1 or (isinstance(e, requests.HTTPError) and r.status_code < 500):
                raise
            time.sleep(2 ** attempt)


def bad_mask(flags, names=BAD_FLAGS):
    bits = sum(1 << FLAG_BITS[n] for n in names)
    return (flags & bits) != 0


def resolve(target):
    """'M51' or '202.4696,47.1952' -> SkyCoord."""
    m = re.fullmatch(r"\s*([-+\d.]+)\s*[, ]\s*([-+\d.]+)\s*", target)
    if m:
        return SkyCoord(float(m[1]), float(m[2]), unit="deg")
    return SkyCoord.from_name(target)


def slug(target):
    return re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_")


def target_coord(target):
    """Like resolve(), but cached in data/<target>/target.json so later steps work offline."""
    path = DATA / slug(target) / "target.json"
    if path.exists():
        d = json.loads(path.read_text())
        return SkyCoord(d["ra"], d["dec"], unit="deg")
    c = resolve(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target": target, "ra": c.ra.deg, "dec": c.dec.deg}))
    return c


def query_images(ra, dec, radius_deg=0.003, collection="spherex_qr2", time_mjd=None):
    """SIA v2 query over plain HTTP. Returns an astropy Table (ObsCore columns)."""
    params = {"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} {radius_deg}",
              "RESPONSEFORMAT": "VOTABLE"}
    if time_mjd is not None:
        params["TIME"] = f"{time_mjd[0]} {time_mjd[1]}"
    r = _get(SIA_URL, params=params)
    return votable.parse(io.BytesIO(r.content)).get_first_table().to_table(use_names_over_ids=True)


def s3_key(row):
    return json.loads(row["cloud_access"])["aws"]["key"]


def _read_header(buf, start):
    """Parse one FITS header from bytes at `start`. Returns (header, byte offset of its data)."""
    i = start
    while True:
        card = buf[i:i + 80]
        if len(card) < 80:
            raise ValueError("header truncated; fetch a bigger byte range")
        i += 80
        if card[:8] == b"END     ":
            break
    data_start = start + 2880 * -(-(i - start) // 2880)
    return fits.Header.fromstring(buf[start:i]), data_start


def image_header(key, nbytes=32768):
    """IMAGE-extension header via a single byte-range request (the primary HDU has no data)."""
    r = _get(S3_HTTP + key, headers={"Range": f"bytes=0-{nbytes - 1}"}, timeout=60)
    _, off = _read_header(r.content, 0)
    hdr, _ = _read_header(r.content, off)
    return hdr


def open_s3(key, block=256 * 1024):
    return fits.open(f"s3://{S3_BUCKET}/{key}", use_fsspec=True, lazy_load_hdus=True,
                     fsspec_kwargs={"anon": True, "default_block_size": block})


def wave_table(detector, key):
    """WCS-WAVE lookup table for a detector, cached on disk.

    Assumes the table is fixed per detector (the filter is bolted to the array);
    checked for D3 across exposures, see README.
    """
    path = DATA / "wave_tables" / f"wcs_wave_D{detector}.fits"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_s3(key) as h:
            fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU(h["WCS-WAVE"].data,
                          h["WCS-WAVE"].header)]).writeto(path)
    return fits.open(path)[1]


def wavelength_at(hdr, wave_hdu, ra, dec):
    """Target pixel (x, y) and the wavelength / bandwidth (um) the LVF sees there."""
    x, y = WCS(hdr).world_to_pixel_values(ra, dec)
    hl = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(header=hdr, name="IMAGE"), wave_hdu])
    sw = WCS(header=hdr, fobj=hl, key="W")
    sw.sip = None  # wavelength does not follow optical distortion
    wl, bw = sw.pixel_to_world(x, y)
    return float(x), float(y), wl.to_value(u.um), bw.to_value(u.um)


def read_stamp(key, ra, dec, half=16):
    """Small (2*half)^2 stamp around (ra, dec): IMAGE - ZODI, FLAGS, and the stamp's WCS."""
    with open_s3(key) as h:
        hdr = h["IMAGE"].header
        w = WCS(hdr)
        x, y = w.world_to_pixel_values(ra, dec)
        xi, yi = int(round(float(x))), int(round(float(y)))
        y0, y1 = max(yi - half, 0), min(yi + half, hdr["NAXIS2"])
        x0, x1 = max(xi - half, 0), min(xi + half, hdr["NAXIS1"])
        if y1 <= y0 or x1 <= x0:
            raise ValueError("target outside image")
        sl = (slice(y0, y1), slice(x0, x1))
        img = np.asarray(h["IMAGE"].section[sl], dtype=np.float32)
        zodi = np.asarray(h["ZODI"].section[sl], dtype=np.float32)
        flags = np.asarray(h["FLAGS"].section[sl])
    return img - zodi, flags, w[sl], hdr


def save_stamp(path, img, flags, wcs, meta):
    hdr = wcs.to_header(relax=True)
    for k, v in meta.items():
        hdr[k] = v
    fits.HDUList([fits.PrimaryHDU(img, header=hdr),
                  fits.ImageHDU(flags.astype(np.int32), name="FLAGS")]).writeto(path, overwrite=True)
