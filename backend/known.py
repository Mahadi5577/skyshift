"""Known solar-system objects in a sequence, from IMCCE SkyBoT, as grid pixel positions per frame.

One SkyBoT query per cluster of frames taken within a day, then linear extrapolation with the
reported on-sky rates (arcsec/hour, RA rate already multiplied by cos Dec).
"""
import json
import math

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.imcce import Skybot

from . import sequences

V_LIMIT = 19.0  # fainter than this is invisible in single SPHEREx frames anyway


def _val(q, unit=None):
    """SkyBoT returns a QTable: strip units (converting first if asked)."""
    return float(q.to_value(unit) if hasattr(q, "to_value") else q)


def known_objects(seq):
    meta = seq["meta"]
    path = seq["dir"] / "known.json"
    if path.exists():
        return json.loads(path.read_text())
    if meta["zoom"] in ("months", "year"):
        result = {"objects": [], "note": "Moving objects blur out of survey-pass composites."}
        path.write_text(json.dumps(result))
        return result

    n, ra0, dec0 = meta["n"], meta["ra"], meta["dec"]
    grid = sequences.grid_wcs(ra0, dec0, n)
    mjds = [e["mjd"] for e in meta["entries"]]
    clusters, cur = [], [0]
    for i in range(1, len(mjds)):
        if mjds[i] - mjds[cur[-1]] > 0.5:
            clusters.append(cur)
            cur = []
        cur.append(i)
    clusters.append(cur)

    # Search wide enough to catch fast movers that cross the field during the cluster.
    half_diag = n * meta["scale"] / math.sqrt(2)
    objects = {}
    for idx in clusters:
        t_mid = float(np.mean([mjds[i] for i in idx]))
        span_h = (max(mjds[i] for i in idx) - min(mjds[i] for i in idx)) * 24 / 2
        radius = half_diag + 60 * max(span_h, 1)  # up to 60"/h main-belt rates
        try:
            res = Skybot.cone_search(SkyCoord(ra0, dec0, unit="deg"), radius * u.arcsec,
                                     Time(t_mid, format="mjd"), location="500")
        except Exception as e:
            # An empty field comes back as an error; anything else (network) is a real failure.
            if "No solar system object" in str(e) or "No table found" in str(e):
                continue
            raise
        for r in res:
            v = _val(r["V"]) if r["V"] is not np.ma.masked else 99
            if v > V_LIMIT:
                continue
            name = str(r["Name"])
            num = r["Number"]
            label = f"({num}) {name}" if num is not np.ma.masked and str(num) != "--" else name
            rate_ra, rate_dec = _val(r["RA_rate"], u.arcsec / u.h), _val(r["DEC_rate"], u.arcsec / u.h)
            ra, dec = _val(r["RA"], u.deg), _val(r["DEC"], u.deg)
            for i in idx:
                dt_h = (mjds[i] - t_mid) * 24
                ra_i = ra + rate_ra * dt_h / 3600 / math.cos(math.radians(dec))
                dec_i = dec + rate_dec * dt_h / 3600
                x, y = grid.world_to_pixel_values(ra_i, dec_i)
                if -2 <= x <= n + 1 and -2 <= y <= n + 1:
                    obj = objects.setdefault(label, {"name": label, "V": v, "type": str(r["Type"]),
                                                     "rate": round(math.hypot(rate_ra, rate_dec), 1),
                                                     "positions": {}})
                    obj["positions"][i] = [round(float(x), 2), round(float(y), 2)]
    result = {"objects": sorted(objects.values(), key=lambda o: o["V"]), "note": None}
    path.write_text(json.dumps(result))
    return result
