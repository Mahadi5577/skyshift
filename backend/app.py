"""SkyShift API and web server.

    uvicorn backend.app:app --port 8000      (from the skyshift folder)

Settings come from environment variables: see backend/config.py.
"""
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from astropy.coordinates import SkyCoord
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, backup, config, hunt, known, limits, precache, sequences, tour

log = logging.getLogger("skyshift")
WEB = Path(__file__).resolve().parent.parent / "web"
MAINTENANCE_EVERY = 600  # seconds between cache prunes and Hunt backups
_state = {"started": time.time(), "precache": "running" if config.PRECACHE else "off"}
_stop = threading.Event()


def _precache():
    try:
        precache.run(config.PRECACHE_PATCHES, log=lambda m: log.info("precache: %s", m))
        _state["precache"] = "done"
    except Exception as e:
        log.exception("precache failed")
        _state["precache"] = f"failed: {e}"


def _maintenance():
    while True:
        try:
            sequences.prune_cache(config.CACHE_MAX_MB * 1024 ** 2)
            backup.sync()
        except Exception:
            log.exception("maintenance failed")
        if _stop.wait(MAINTENANCE_EVERY):
            return


@asynccontextmanager
async def lifespan(app):
    backup.restore()
    threading.Thread(target=_maintenance, name="maintenance", daemon=True).start()
    if config.PRECACHE:
        threading.Thread(target=_precache, name="precache", daemon=True).start()
    yield
    _stop.set()
    try:
        backup.sync()
    except Exception:
        log.exception("final Hunt backup failed")


# Archive-heavy calls share a small per-client budget; everything else gets 20 times more.
heavy = Depends(limits.dependency(limits.RateLimiter(config.RATE_LIMIT), "archive requests"))
light = Depends(limits.dependency(limits.RateLimiter(config.RATE_LIMIT * 20, burst=config.RATE_LIMIT * 10),
                                  "requests"))
app = FastAPI(title="SkyShift", version=__version__, lifespan=lifespan, dependencies=[light],
              description="Zoom through time in NASA SPHEREx sky images.")
_names = {}


@app.exception_handler(sequences.Busy)
def busy(request, e):
    return JSONResponse({"detail": str(e)}, status_code=503, headers={"Retry-After": "10"})


@app.exception_handler(requests.RequestException)
def archive_down(request, e):
    return JSONResponse({"detail": "the NASA archive did not answer: please try again in a minute"},
                        status_code=502)


@app.get("/api/health")
def health():
    """For uptime checks: version, load and cache state. Cheap: never touches the archive."""
    size = sequences.last_size["bytes"]
    return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - _state["started"]),
            "downloading": sequences.downloading(), "max_fetches": config.MAX_FETCHES,
            "hunt_pool": len(sequences.cached_sequences()), "precache": _state["precache"],
            "cache_mb": None if size is None else round(size / 1024 ** 2, 1),
            "cache_max_mb": config.CACHE_MAX_MB, "backup": backup.enabled()}


@app.get("/api/resolve", dependencies=[heavy])
def resolve(q: str = Query(..., min_length=1, max_length=100)):
    """Object name or 'RA,Dec' in degrees -> coordinates."""
    m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*[, ]\s*([-+]?\d+(?:\.\d+)?)\s*", q)
    if m:
        ra, dec = float(m[1]), float(m[2])
        if not (0 <= ra < 360 and -90 <= dec <= 90):
            raise HTTPException(400, "RA must be 0-360 and Dec -90 to 90 degrees")
        return {"name": q.strip(), "ra": ra, "dec": dec}
    key = q.strip().lower()
    if key not in _names:
        try:
            c = SkyCoord.from_name(q.strip())
        except Exception:
            raise HTTPException(404, f"could not find '{q}'. Try another name or RA,Dec in degrees")
        if len(_names) > 2000:  # bounded memory on a public server
            _names.clear()
        _names[key] = {"name": q.strip(), "ra": round(c.ra.deg, 6), "dec": round(c.dec.deg, 6)}
    return _names[key]


@app.get("/api/coverage", dependencies=[heavy])
def coverage(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90)):
    """Every SPHEREx image of a position, with the wavelength it saw there and its survey pass."""
    cov = sequences.coverage(ra, dec)
    return {k: v for k, v in cov.items() if k != "images"} | {
        "images": [{k: im[k] for k in ("id", "det", "date", "mjd", "wave", "pass")} for im in cov["images"]]}


class SequenceRequest(BaseModel):
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    zoom: str = "days"
    wave: float | None = Field(default=None, gt=0.5, lt=5.5)
    n: int = Field(default=48, ge=16, le=96)
    t_min: float | None = None
    t_max: float | None = None
    tol: float | None = Field(default=None, ge=0.005, le=0.2)


@app.post("/api/sequence", dependencies=[heavy])
def make_sequence(req: SequenceRequest):
    """Pick frames for a time-zoom level and start downloading them. Poll GET /api/sequence/{id}."""
    try:
        seq = sequences.start(req.ra, req.dec, req.zoom, req.wave, req.n, req.t_min, req.t_max, req.tol,
                              max_active=config.MAX_FETCHES)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    return sequences.summary(seq)


def _seq(seq_id):
    seq = sequences.get(seq_id) if re.fullmatch(r"[0-9a-f]{16}", seq_id) else None
    if seq is None:
        raise HTTPException(404, "unknown sequence")
    return seq


@app.get("/api/sequence/{seq_id}")
def sequence_status(seq_id: str):
    return sequences.summary(_seq(seq_id))


@app.get("/api/sequence/{seq_id}/frame/{i}")
def sequence_frame(seq_id: str, i: int):
    """One frame as raw little-endian float32, n*n values, row 0 at the bottom (south). NaN = no data."""
    seq = _seq(seq_id)
    if not 0 <= i < len(seq["status"]):
        raise HTTPException(404, "no such frame")
    data = sequences.entry_bytes(seq, i)
    if data is None:
        raise HTTPException(409, f"frame not ready ({seq['status'][i]})")
    return Response(data, media_type="application/octet-stream",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/sequence/{seq_id}/known", dependencies=[heavy])
def sequence_known(seq_id: str):
    """Known asteroids and comets (IMCCE SkyBoT) with pixel positions per frame."""
    try:
        return known.known_objects(_seq(seq_id))
    except sequences.Busy:
        raise
    except Exception as e:
        raise HTTPException(502, f"SkyBoT lookup failed: {e}")


@app.get("/api/tour")
def tour_stops():
    return tour.stops()


@app.get("/api/hunt/round")
def hunt_round(player: str = Query(..., min_length=1, max_length=40),
               key: str | None = Query(None, min_length=16, max_length=64)):
    """A new round: frame times only. Practice frames come with the fake already planted, from
    /api/hunt/round/{id}/frame/{i}; its track is revealed by /api/hunt/answer."""
    name = player.strip()
    if not name:
        raise HTTPException(400, "player name is empty")
    try:
        return hunt.new_round(name, key)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except hunt.NameTaken as e:
        raise HTTPException(403, str(e))


@app.get("/api/hunt/round/{round_id}/frame/{i}")
def hunt_frame(round_id: str, i: int):
    """Frame i of a round, in the same format as /api/sequence/{id}/frame/{i}."""
    data = hunt.round_frame(round_id, i) if re.fullmatch(r"[0-9a-f]{24}", round_id) else None
    if data is None:
        raise HTTPException(404, "round expired or frame unavailable")
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})


class Answer(BaseModel):
    round_id: str = Field(max_length=64)
    click: list[float] | None = Field(default=None, min_length=2, max_length=2)


@app.post("/api/hunt/answer")
def hunt_answer(a: Answer):
    rnd = hunt.get_round(a.round_id)
    if rnd is None or rnd["answered"]:
        raise HTTPException(404, "unknown or already answered round")
    k = None
    if not rnd["practice"] and a.click is not None:
        try:
            k = known.known_objects(_seq(rnd["seq_id"]))
        except Exception:
            k = None
    try:
        return hunt.answer(a.round_id, a.click, k)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/api/hunt/board")
def hunt_board():
    return hunt.board()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
