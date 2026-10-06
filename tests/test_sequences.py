import numpy as np
import pytest

from backend import sequences as S


def im(i, mjd, wave, p, edge=500):
    return {"id": f"im{i}", "det": 2, "mjd": mjd, "date": "2025-01-01T00:00:00Z",
            "wave": wave, "edge": edge, "key": f"k{i}", "pass": p}


@pytest.fixture
def images():
    out = []
    k = 0
    # Pass 0: a burst of 6 exposures within 3 hours at 1.30-1.38 um, plus 3 more at 1.30 on later days.
    for j in range(6):
        out.append(im(k, 60800 + j * 0.02, 1.30 + j * 0.015, 0)); k += 1
    for d in (2, 4, 6):
        out.append(im(k, 60800 + d, 1.30, 0)); k += 1
    # Pass 1 (~6 months later): 2 at 1.30, and 4 at 2.00 within one pass.
    for j in range(2):
        out.append(im(k, 60990 + j, 1.30, 1)); k += 1
    for j in range(4):
        out.append(im(k, 60990 + j * 2, 2.00, 1)); k += 1
    # Pass 2: 1 at 1.30; 1 at 2.00 too close to the detector edge.
    out.append(im(k, 61180, 1.30, 2)); k += 1
    out.append(im(k, 61181, 2.00, 2, edge=10)); k += 1
    return out


def test_hours_takes_densest_day_with_wide_tolerance(images):
    entries = S.select(images, 1.30, "hours")
    t = [e["mjd"] for e in entries]
    assert len(entries) == 6                      # the 3-hour burst, 1.30-1.375 um (10% tolerance)
    assert max(t) - min(t) < 1


def test_days_takes_richest_pass_at_matched_wavelength(images):
    entries = S.select(images, 1.30, "days")
    assert {e["pass"] for e in entries} == {0}
    assert all(abs(e["wave"] - 1.30) / 1.30 < 0.02 for e in entries)
    assert len(entries) == 5                      # 1.30 and 1.315 from the burst (1.33+ is >2% off) + days 2, 4, 6


def test_months_one_composite_per_pass(images):
    entries = S.select(images, 1.30, "months")
    assert [e["pass"] for e in entries] == [0, 1, 2]
    assert all(1 <= len(e["members"]) <= S.MEMBERS_PER_PASS for e in entries)


def test_year_first_and_last_pass(images):
    entries = S.select(images, 1.30, "year")
    assert [e["pass"] for e in entries] == [0, 2]


def test_edge_images_are_skipped(images):
    entries = S.select(images, 2.00, "months")
    assert [e["pass"] for e in entries] == [1]    # pass 2's 2.00 um image is 10 px from the edge


def test_time_window(images):
    entries = S.select(images, 1.30, "days", t_min=60801, t_max=60807)
    assert [round(e["mjd"]) for e in entries] == [60802, 60804, 60806]


def test_suggest_wave_depends_on_zoom(images):
    assert S.suggest_wave(images, "hours") == pytest.approx(1.30, abs=0.02)
    assert S.suggest_wave(images, "months") == pytest.approx(1.30, abs=0.01)  # in all 3 passes
    assert S.suggest_wave([], "days") is None


def test_grid_centre_is_target():
    w = S.grid_wcs(210.0, -5.0, 48)
    ra, dec = w.pixel_to_world_values(23.5, 23.5)
    assert np.allclose([ra, dec], [210.0, -5.0])
