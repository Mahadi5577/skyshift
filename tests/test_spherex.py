import numpy as np
from astropy.wcs import WCS

from backend import spherex


def test_wave_at_matches_header_based_value():
    # M51 in exposure 2025W19_1B_0146_1, detector 3: astropy's WAVE-TAB WCS on the full header gave
    # 1.649484 um at this pixel (sandbox, 2026-10-05).
    assert abs(spherex.wave_at(3, 1363.768, 1947.350) - 1.649484) < 1e-4


def test_each_detector_covers_its_band():
    lo = [spherex.wave_at(d, 1020, 5) for d in range(1, 7)]
    hi = [spherex.wave_at(d, 1020, 2035) for d in range(1, 7)]
    for d in range(6):
        assert 0.7 < min(lo[d], hi[d]) < max(lo[d], hi[d]) < 5.1
    # detectors get redder from D1 to D6
    mids = [(a + b) / 2 for a, b in zip(lo, hi)]
    assert mids == sorted(mids)


def _wcs(ra, dec, rot_deg):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [1020.5, 1020.5]
    s, r = spherex.PIXEL_SCALE / 3600, np.radians(rot_deg)
    w.wcs.cd = [[-s * np.cos(r), s * np.sin(r)], [s * np.sin(r), s * np.cos(r)]]
    return w


def test_pixel_from_region_recovers_pixels():
    w = _wcs(150.0, 30.0, 37.0)
    # SIA lists the corners in pixel order and repeats the first one to close the polygon.
    ra, dec = w.pixel_to_world_values([0, 2039, 2039, 0, 0], [0, 0, 2039, 2039, 0])
    s_region = "POLYGON ICRS " + " ".join(f"{a} {b}" for a, b in zip(ra, dec))
    s_ra, s_dec = (float(v) for v in w.pixel_to_world_values(1019.5, 1019.5))
    for x, y in [(100, 200), (1500, 900), (1900, 1950)]:
        tra, tdec = (float(v) for v in w.pixel_to_world_values(x, y))
        px, py = spherex.pixel_from_region(s_region, s_ra, s_dec, tra, tdec)
        assert abs(px - x) < 1 and abs(py - y) < 1


def test_hide_mask_keeps_flags_seen_on_real_asteroids():
    assert not spherex.HIDE_MASK & (1 << 17)  # PERSIST: hit Hygiea in one frame
    assert not spherex.HIDE_MASK & (1 << 19)  # OUTLIER: a mover can look like one
    assert not spherex.HIDE_MASK & (1 << 21)  # SOURCE: marks known sources
    assert spherex.HIDE_MASK & (1 << 6)       # NONFUNC stays hidden
