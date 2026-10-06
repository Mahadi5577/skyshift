"""API tests that need no network."""
import os

import pytest
from fastapi.testclient import TestClient

from backend import sequences
from backend.app import app

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "SkyShift" in r.text


def test_resolve_coordinates_without_network():
    assert client.get("/api/resolve", params={"q": "10.5, -20"}).json() == {
        "name": "10.5, -20", "ra": 10.5, "dec": -20.0}
    assert client.get("/api/resolve", params={"q": "999,0"}).status_code == 400


def test_tour_stops_complete():
    stops = client.get("/api/tour").json()
    assert {"hygiea", "pluto", "ecliptic", "m51", "orion"} <= {s["id"] for s in stops}
    for s in stops:
        assert {"ra", "dec", "zoom", "n", "tol", "blurb"} <= s.keys()


def test_bad_zoom_rejected_before_any_download():
    r = client.post("/api/sequence", json={"ra": 10, "dec": 10, "zoom": "weeks"})
    assert r.status_code == 400


def test_unknown_ids():
    assert client.get("/api/sequence/not-an-id").status_code == 404
    assert client.post("/api/hunt/answer", json={"round_id": "nope", "click": None}).status_code == 404
    assert client.get(f"/api/hunt/round/{'0' * 24}/frame/0").status_code == 404


def test_health():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["version"] and h["downloading"] >= 0


def test_busy_becomes_503_with_retry_after(monkeypatch):
    def busy(*a, **k):
        raise sequences.Busy("busy")
    monkeypatch.setattr(sequences, "start", busy)
    r = client.post("/api/sequence", json={"ra": 10, "dec": 10, "zoom": "days"})
    assert r.status_code == 503 and r.headers["Retry-After"]


def test_heavy_requests_are_rate_limited(monkeypatch):
    from backend import limits
    monkeypatch.setattr(limits.RateLimiter, "wait", lambda self, key, now=None: 7.2)
    r = client.get("/api/resolve", params={"q": "1,1"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "8"


@pytest.mark.skipif(not os.environ.get("SKYSHIFT_NETWORK"), reason="set SKYSHIFT_NETWORK=1 to hit IRSA")
def test_coverage_m51_live():
    c = client.get("/api/coverage", params={"ra": 202.469575, "dec": 47.19525833}).json()
    assert len(c["images"]) > 300 and len(c["passes"]) >= 3
    assert set(c["suggested"]) == {"hours", "days", "months", "year"}
