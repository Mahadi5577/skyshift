"""Hunt mode: practice rounds with planted fake movers, real rounds, player skill, candidate board.

Brightness levels come from sandbox experiment 07 (planting fakes in real frames):
automatic recovery 99.5% at peak S/N 12, 89% at 8, 13% at 5. The game starts easy and gets
harder as the player gets better. Fakes are always labelled as practice.

The server plants the fake into the frames it sends, so the browser never learns where it is
until the round is answered. Players, rounds and flags live in an SQLite file under
SKYSHIFT_DATA, apart from the download cache, so they survive restarts and cache clean-ups.
"""
import hashlib
import json
import math
import random
import secrets
import sqlite3
import threading
import time
from contextlib import closing

import numpy as np

from . import config, sequences

PRACTICE_SHARE = 0.7
LEVELS = [12, 8, 6, 5]  # peak signal-to-noise per frame
PSF_SIGMA = 0.9         # pixels; measured from a real star in experiment 07
HIT_RADIUS = 3.0        # pixels from the track counts as found
ROUND_TTL = 3600        # seconds a round's frames stay available
DB = config.DATA / "hunt.sqlite"

SCHEMA = """
create table if not exists players (
    name text primary key, key_hash text, rounds integer not null default 0,
    hits integer not null default 0, streak integer not null default 0,
    flags integer not null default 0, created real);
create table if not exists rounds (
    id text primary key, player text not null, seq_id text not null, practice integer not null,
    fake text, created real not null, answered real);
create table if not exists flags (
    id integer primary key, seq_id text not null, x real not null, y real not null,
    ra real, dec real, zoom text, player text not null, skill real not null, known text,
    time real not null);
"""

_lock = threading.Lock()  # one writer at a time inside this process
_ready = set()


def _db():
    """A connection to the Hunt database (created on first use). Use with closing(); commit()."""
    if DB not in _ready:
        DB.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(DB)) as con:
            con.executescript(SCHEMA)
        _ready.add(DB)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


class NameTaken(PermissionError):
    pass


def _player(con, name, key=None):
    """The player's stats. A name belongs to the first browser key that used it."""
    row = con.execute("select * from players where name = ?", (name,)).fetchone()
    key_hash = hashlib.sha256(key.encode()).hexdigest() if key else None
    if row is None:
        con.execute("insert into players (name, key_hash, created) values (?, ?, ?)",
                    (name, key_hash, time.time()))
        return {"name": name, "rounds": 0, "hits": 0, "streak": 0, "flags": 0}
    if key_hash and row["key_hash"] and row["key_hash"] != key_hash:
        raise NameTaken("that player name is already taken: pick another one")
    if key_hash and not row["key_hash"]:
        con.execute("update players set key_hash = ? where name = ?", (key_hash, name))
    return dict(row)


def skill(p):
    """Beta(1,1) estimate of how often this player finds planted movers."""
    return (p["hits"] + 1) / (p["rounds"] + 2)


def level(streak):
    return LEVELS[min(streak // 3, len(LEVELS) - 1)]


def _save_round(con, rnd):
    con.execute("insert into rounds (id, player, seq_id, practice, fake, created) values (?, ?, ?, ?, ?, ?)",
                (rnd["id"], rnd["player"], rnd["seq_id"], int(rnd["practice"]),
                 json.dumps(rnd.get("fake")), rnd.get("created", time.time())))


def get_round(round_id):
    """A round that has not expired (answered or not), or None."""
    with closing(_db()) as con:
        row = con.execute("select * from rounds where id = ? and created > ?",
                          (round_id, time.time() - ROUND_TTL)).fetchone()
    if row is None:
        return None
    return dict(row) | {"practice": bool(row["practice"]), "fake": json.loads(row["fake"])}


def new_round(player, key=None):
    pool = sequences.cached_sequences()
    if not pool:
        raise LookupError("no downloaded sequences yet: open some sky positions in Explore first, "
                          "or run scripts/precache.py")
    meta = random.choice(pool)
    practice = random.random() < PRACTICE_SHARE
    rnd = {"id": secrets.token_hex(12), "seq_id": meta["id"], "practice": practice, "player": player,
           "created": time.time()}
    with _lock, closing(_db()) as con:
        p = _player(con, player, key)
        if practice:
            n = meta["n"]
            ang = random.uniform(0, 2 * math.pi)
            length = random.uniform(6, 10)
            rnd["fake"] = {"x0": random.uniform(n * 0.25, n * 0.75), "y0": random.uniform(n * 0.25, n * 0.75),
                           "dx": length * math.cos(ang), "dy": length * math.sin(ang),
                           "snr": level(p["streak"]), "psf_sigma": PSF_SIGMA}
        con.execute("delete from rounds where created < ?", (time.time() - ROUND_TTL,))
        _save_round(con, rnd)
        con.commit()
    # No sequence id or position: those would let a script find the fake by differencing.
    return {"round_id": rnd["id"], "practice": practice, "n": meta["n"], "zoom": meta["zoom"],
            "entries": [{"mjd": e["mjd"], "date": e["date"], "wave": e["wave"]} for e in meta["entries"]],
            "snr": rnd["fake"]["snr"] if practice else None,
            "skill": round(skill(p), 3), "streak": p["streak"]}


def plant(arr, x, y, snr, sigma):
    """Add a Gaussian mover at grid pixel (x, y) with peak snr times the frame's own noise
    (from the median absolute deviation). Same recipe as the injection tests in experiment 07."""
    v = arr[np.isfinite(arr)]
    if not v.size:
        return arr
    med = np.median(v)
    amp = snr * 1.4826 * np.median(np.abs(v - med))
    yy, xx = np.mgrid[: arr.shape[0], : arr.shape[1]]
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    blob = np.where(d2 <= (4 * sigma) ** 2, amp * np.exp(-d2 / (2 * sigma ** 2)), 0)
    return (arr + blob).astype(np.float32)


def round_frame(round_id, i):
    """Frame i of a round as float32 bytes (with the fake planted in practice rounds), or None."""
    rnd = get_round(round_id)
    seq = sequences.get(rnd["seq_id"]) if rnd else None
    if seq is None or not 0 <= i < len(seq["status"]):
        return None
    arr = sequences.entry_array(seq, i)
    if arr is None:
        return None
    if rnd["fake"]:
        f = rnd["fake"]
        t = [e["mjd"] for e in seq["meta"]["entries"]]
        k = (t[i] - min(t)) / ((max(t) - min(t)) or 1)
        arr = plant(arr, f["x0"] + f["dx"] * k, f["y0"] + f["dy"] * k, f["snr"], f["psf_sigma"])
    return arr.astype("<f4").tobytes()


def _dist_to_track(fake, x, y):
    ax, ay = fake["x0"], fake["y0"]
    bx, by = ax + fake["dx"], ay + fake["dy"]
    t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (fake["dx"] ** 2 + fake["dy"] ** 2)))
    return math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)))


def answer(round_id, click, known=None):
    """click = [x, y] in grid pixels, or None for "nothing moves here"."""
    with _lock, closing(_db()) as con:
        row = con.execute("select * from rounds where id = ? and answered is null", (round_id,)).fetchone()
        if row is None:
            raise LookupError("unknown or already answered round")
        con.execute("update rounds set answered = ? where id = ?", (time.time(), round_id))
        p = _player(con, row["player"])
        if row["practice"]:
            fake = json.loads(row["fake"])
            found = click is not None and _dist_to_track(fake, *click) <= HIT_RADIUS
            p["rounds"] += 1
            p["hits"] += found
            p["streak"] = p["streak"] + 1 if found else 0
            result = {"practice": True, "found": found, "fake": fake}
        else:
            result = {"practice": False, "flagged": click is not None, "known_match": None}
            if click is not None:
                for obj in (known or {}).get("objects", []):
                    for xy in obj["positions"].values():
                        if math.hypot(xy[0] - click[0], xy[1] - click[1]) <= HIT_RADIUS:
                            result["known_match"] = obj["name"]
                # Store the sky position now: the sequence may later be pruned from the cache.
                seq = sequences.get(row["seq_id"])
                ra = dec = zoom = None
                if seq is not None:
                    meta = seq["meta"]
                    ra, dec = (round(float(v), 5) for v in sequences.grid_wcs(
                        meta["ra"], meta["dec"], meta["n"]).pixel_to_world_values(click[0], click[1]))
                    zoom = meta["zoom"]
                con.execute("insert into flags (seq_id, x, y, ra, dec, zoom, player, skill, known, time) "
                            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (row["seq_id"], click[0], click[1], ra, dec, zoom, row["player"], skill(p),
                             result["known_match"], time.time()))
                p["flags"] += 1
        con.execute("update players set rounds = ?, hits = ?, streak = ?, flags = ? where name = ?",
                    (p["rounds"], p["hits"], p["streak"], p["flags"], row["player"]))
        con.commit()
    return result | {"skill": round(skill(p), 3), "streak": p["streak"], "rounds": p["rounds"]}


def board():
    """Real-round flags grouped by sequence and position (within 3 px), ranked by skill-weighted votes."""
    with closing(_db()) as con:
        flags = [dict(r) for r in con.execute("select * from flags where ra is not null order by id")]
        players = con.execute("select count(*) from players").fetchone()[0]
    groups = []
    for f in flags:
        for g in groups:
            if g["seq_id"] == f["seq_id"] and math.hypot(g["x"] - f["x"], g["y"] - f["y"]) <= HIT_RADIUS:
                g["flags"].append(f)
                break
        else:
            groups.append({"seq_id": f["seq_id"], "x": f["x"], "y": f["y"], "flags": [f]})
    out = []
    for g in groups:
        first = g["flags"][0]
        out.append({"seq_id": g["seq_id"], "x": round(g["x"], 1), "y": round(g["y"], 1),
                    "ra": first["ra"], "dec": first["dec"], "zoom": first["zoom"],
                    "votes": len({f["player"] for f in g["flags"]}),
                    "score": round(sum(f["skill"] for f in g["flags"]), 2),
                    "known": next((f["known"] for f in g["flags"] if f["known"]), None),
                    "first": min(f["time"] for f in g["flags"])})
    out.sort(key=lambda c: (c["known"] is not None, -c["score"]))
    return {"candidates": out, "players": players}
