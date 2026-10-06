"""Hunt mode: practice rounds with planted fake movers, real rounds, player skill, candidate board.

Brightness levels come from sandbox experiment 07 (planting fakes in real frames):
automatic recovery 99.5% at peak S/N 12, 89% at 8, 13% at 5. The game starts easy and gets
harder as the player gets better. Fakes are always labelled as practice.
"""
import json
import math
import random
import threading
import time
import uuid

from . import sequences

PRACTICE_SHARE = 0.7
LEVELS = [12, 8, 6, 5]  # peak signal-to-noise per frame
PSF_SIGMA = 0.9         # pixels; measured from a real star in experiment 07
HIT_RADIUS = 3.0        # pixels from the track counts as found
STORE = sequences.CACHE / "hunt.json"

_lock = threading.Lock()
_rounds = {}


def _load():
    return json.loads(STORE.read_text()) if STORE.exists() else {"players": {}, "flags": []}


def _save(db):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1))
    tmp.replace(STORE)


def _player(db, name):
    return db["players"].setdefault(name, {"rounds": 0, "hits": 0, "streak": 0, "flags": 0})


def skill(p):
    """Beta(1,1) estimate of how often this player finds planted movers."""
    return (p["hits"] + 1) / (p["rounds"] + 2)


def new_round(player):
    pool = sequences.cached_sequences()
    if not pool:
        raise LookupError("no downloaded sequences yet: open some sky positions in Explore first, "
                          "or run scripts/precache.py")
    meta = random.choice(pool)
    with _lock:
        p = _player(_load(), player)
    practice = random.random() < PRACTICE_SHARE
    rnd = {"id": uuid.uuid4().hex[:12], "seq_id": meta["id"], "practice": practice, "player": player,
           "created": time.time()}
    if practice:
        level = LEVELS[min(p["streak"] // 3, len(LEVELS) - 1)]
        n = meta["n"]
        x0, y0 = random.uniform(n * 0.25, n * 0.75), random.uniform(n * 0.25, n * 0.75)
        ang = random.uniform(0, 2 * math.pi)
        length = random.uniform(6, 10)
        rnd["fake"] = {"x0": x0, "y0": y0, "dx": length * math.cos(ang), "dy": length * math.sin(ang),
                       "snr": level, "psf_sigma": PSF_SIGMA}
    _rounds[rnd["id"]] = rnd
    return {"round_id": rnd["id"], "seq_id": meta["id"], "practice": practice,
            "fake": rnd.get("fake"), "skill": round(skill(p), 3), "streak": p["streak"]}


def _dist_to_track(fake, x, y):
    ax, ay = fake["x0"], fake["y0"]
    bx, by = ax + fake["dx"], ay + fake["dy"]
    t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (fake["dx"] ** 2 + fake["dy"] ** 2)))
    return math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)))


def answer(round_id, click, known=None):
    """click = [x, y] in grid pixels, or None for "nothing moves here"."""
    rnd = _rounds.pop(round_id, None)
    if rnd is None:
        raise LookupError("unknown or already answered round")
    with _lock:
        db = _load()
        p = _player(db, rnd["player"])
        if rnd["practice"]:
            found = click is not None and _dist_to_track(rnd["fake"], *click) <= HIT_RADIUS
            p["rounds"] += 1
            p["hits"] += found
            p["streak"] = p["streak"] + 1 if found else 0
            result = {"practice": True, "found": found, "fake": rnd["fake"]}
        else:
            result = {"practice": False, "flagged": click is not None, "known_match": None}
            if click is not None:
                for obj in (known or {}).get("objects", []):
                    for xy in obj["positions"].values():
                        if math.hypot(xy[0] - click[0], xy[1] - click[1]) <= HIT_RADIUS:
                            result["known_match"] = obj["name"]
                db["flags"].append({"seq_id": rnd["seq_id"], "x": click[0], "y": click[1],
                                    "player": rnd["player"], "skill": skill(p),
                                    "known": result["known_match"], "time": time.time()})
                p["flags"] += 1
        _save(db)
        result |= {"skill": round(skill(p), 3), "streak": p["streak"], "rounds": p["rounds"]}
    return result


def board():
    """Real-round flags grouped by sequence and position (within 3 px), ranked by skill-weighted votes."""
    with _lock:
        db = _load()
    groups = []
    for f in db["flags"]:
        for g in groups:
            if g["seq_id"] == f["seq_id"] and math.hypot(g["x"] - f["x"], g["y"] - f["y"]) <= HIT_RADIUS:
                g["flags"].append(f)
                break
        else:
            groups.append({"seq_id": f["seq_id"], "x": f["x"], "y": f["y"], "flags": [f]})
    out = []
    for g in groups:
        seq = sequences.get(g["seq_id"])
        if seq is None:
            continue
        meta = seq["meta"]
        ra, dec = sequences.grid_wcs(meta["ra"], meta["dec"], meta["n"]).pixel_to_world_values(g["x"], g["y"])
        players = {f["player"] for f in g["flags"]}
        known = next((f["known"] for f in g["flags"] if f["known"]), None)
        out.append({"seq_id": g["seq_id"], "x": round(g["x"], 1), "y": round(g["y"], 1),
                    "ra": round(float(ra), 5), "dec": round(float(dec), 5), "zoom": meta["zoom"],
                    "votes": len(players), "score": round(sum(f["skill"] for f in g["flags"]), 2),
                    "known": known, "first": min(f["time"] for f in g["flags"])})
    out.sort(key=lambda c: (c["known"] is not None, -c["score"]))
    return {"candidates": out, "players": len(db["players"])}
