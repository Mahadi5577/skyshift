"""SkyShift API and web server.

    uvicorn backend.app:app --port 8000      (from the skyshift folder)
"""
import re
from pathlib import Path

from astropy.coordinates import SkyCoord
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import hunt, known, sequences, tour

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="SkyShift", description="Zoom through time in NASA SPHEREx sky images.")
_names = {}


@app.get("/api/resolve")
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
        _names[key] = {"name": q.strip(), "ra": round(c.ra.deg, 6), "dec": round(c.dec.deg, 6)}
    return _names[key]


@app.get("/api/coverage")
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


@app.post("/api/sequence")
def make_sequence(req: SequenceRequest):
    """Pick frames for a time-zoom level and start downloading them. Poll GET /api/sequence/{id}."""
    try:
        seq = sequences.start(req.ra, req.dec, req.zoom, req.wave, req.n, req.t_min, req.t_max, req.tol)
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


@app.get("/api/sequence/{seq_id}/known")
def sequence_known(seq_id: str):
    """Known asteroids and comets (IMCCE SkyBoT) with pixel positions per frame."""
    try:
        return known.known_objects(_seq(seq_id))
    except Exception as e:
        raise HTTPException(502, f"SkyBoT lookup failed: {e}")


@app.get("/api/tour")
def tour_stops():
    return tour.stops()


@app.get("/api/hunt/round")
def hunt_round(player: str = Query(..., min_length=1, max_length=40)):
    try:
        return hunt.new_round(player.strip())
    except LookupError as e:
        raise HTTPException(404, str(e))


class Answer(BaseModel):
    round_id: str
    click: list[float] | None = Field(default=None, min_length=2, max_length=2)


@app.post("/api/hunt/answer")
def hunt_answer(a: Answer):
    rnd = hunt._rounds.get(a.round_id)
    if rnd is None:
        raise HTTPException(404, "unknown or already answered round")
    k = None
    if not rnd["practice"] and a.click is not None:
        try:
            k = known.known_objects(_seq(rnd["seq_id"]))
        except Exception:
            k = None
    return hunt.answer(a.round_id, a.click, k)


@app.get("/api/hunt/board")
def hunt_board():
    return hunt.board()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
