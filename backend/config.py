"""Settings, read once from environment variables, so the same code runs on a laptop and on a
public server. Defaults suit a laptop; the Dockerfile sets the server values.

    SKYSHIFT_CACHE          downloaded data, safe to delete            (default: ./cache)
    SKYSHIFT_DATA           Hunt players, rounds and flags: keep it    (default: ./data)
    SKYSHIFT_CACHE_MAX_MB   prune least-recently-used downloads above this size, 0 = never (2048)
    SKYSHIFT_RATE_LIMIT     archive-heavy requests per minute per client, 0 = off (30)
    SKYSHIFT_MAX_FETCHES    sequences downloading at once; more get "busy, retry" (6)
    SKYSHIFT_PRECACHE       1 = download the tour and Hunt patches in the background at start (0)
    SKYSHIFT_PRECACHE_PATCHES  ecliptic Hunt patches for that precache (6)
    SKYSHIFT_BACKUP_REPO    Hugging Face dataset repo to back the Hunt database up to (off)
    HF_TOKEN                write token for that repo
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name, default):
    return int(os.environ.get(name) or default)


CACHE = Path(os.environ.get("SKYSHIFT_CACHE") or ROOT / "cache")
DATA = Path(os.environ.get("SKYSHIFT_DATA") or ROOT / "data")
CACHE_MAX_MB = _int("SKYSHIFT_CACHE_MAX_MB", 2048)
RATE_LIMIT = _int("SKYSHIFT_RATE_LIMIT", 30)
MAX_FETCHES = _int("SKYSHIFT_MAX_FETCHES", 6)
PRECACHE = os.environ.get("SKYSHIFT_PRECACHE", "0") == "1"
PRECACHE_PATCHES = _int("SKYSHIFT_PRECACHE_PATCHES", 6)
BACKUP_REPO = os.environ.get("SKYSHIFT_BACKUP_REPO") or None
HF_TOKEN = os.environ.get("HF_TOKEN") or None
