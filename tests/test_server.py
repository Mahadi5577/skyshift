"""Public-server safeguards: rate limits, download cap, cache pruning, Hunt backup. No network."""
import json
import os
import sqlite3
from contextlib import closing

import numpy as np
import pytest

from backend import backup, hunt, limits, sequences


def test_rate_limiter_allows_burst_then_refills():
    rl = limits.RateLimiter(per_minute=60, burst=3)
    assert [rl.wait("a", now=0) for _ in range(3)] == [0, 0, 0]
    assert rl.wait("a", now=0) == pytest.approx(1.0)  # one token per second
    assert rl.wait("b", now=0) == 0                  # other clients are unaffected
    assert rl.wait("a", now=1.0) == 0


def test_rate_limit_off():
    assert all(limits.RateLimiter(0).wait("a") == 0 for _ in range(100))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sequences, "CACHE", tmp_path)
    monkeypatch.setattr(sequences, "_sequences", {})
    return tmp_path


def make_seq(cache, seq_id, mtime, kb=100):
    d = cache / "sequences" / seq_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}")
    (d / "0.npy").write_bytes(b"x" * kb * 1024)
    os.utime(d / "meta.json", (mtime, mtime))
    return d


def test_prune_removes_oldest_unpinned_first(cache):
    old, pinned, new = (make_seq(cache, s, t) for s, t in (("old", 1000), ("pinned", 500), ("new", 3000)))
    sequences.pin(["pinned"])
    res = sequences.prune_cache(max_bytes=250 * 1024)
    assert not old.exists() and pinned.exists() and new.exists()
    assert res["deleted"] == 1 and res["after"] < 250 * 1024


def test_prune_keeps_downloading_sequences(cache):
    busy = make_seq(cache, "busy", 1000)
    sequences._sequences["busy"] = {"status": ["loading"], "used": 0}
    sequences.prune_cache(max_bytes=10 * 1024)
    assert busy.exists()


def test_prune_under_limit_does_nothing(cache):
    d = make_seq(cache, "a", 1000)
    assert sequences.prune_cache(max_bytes=10 * 1024 ** 2)["deleted"] == 0 and d.exists()


def test_download_cap_raises_busy(cache, monkeypatch):
    images = [{"id": f"im{i}", "det": 2, "mjd": 60800 + i * 2, "date": "2025-01-01T00:00:00Z", "wave": 1.3,
               "edge": 500, "key": f"k{i}", "pass": 0} for i in range(6)]
    monkeypatch.setattr(sequences, "coverage", lambda ra, dec, collection: {
        "ra": ra, "dec": dec, "images": images, "suggested": {"days": 1.3}})
    sequences._sequences["other"] = {"status": ["loading"], "used": 0}
    with pytest.raises(sequences.Busy):
        sequences.start(10.0, 10.0, "days", max_active=1)
    assert "other" in sequences._sequences and len(sequences._sequences) == 1


def test_get_loads_by_id_without_rederiving_it(cache, monkeypatch):
    # Caches written by older versions can hold ids that the stored parameters no longer hash to.
    d = cache / "sequences" / "abcdef0123456789"
    d.mkdir(parents=True)
    meta = {"id": d.name, "ra": 10.0, "dec": 10.0, "zoom": "days", "wave": 1.30001, "n": 48,
            "t_min": None, "t_max": None, "tol": None, "entries": [{"mjd": 1, "members": ["im0"]}]}
    (d / "meta.json").write_text(json.dumps(meta))
    np.save(d / "0.npy", np.zeros((48, 48), np.float32))
    monkeypatch.setattr(sequences, "coverage", lambda *a: pytest.fail("complete sequences need no search"))
    seq = sequences.get(d.name)
    assert seq["status"] == ["ready"] and [p.name for p in (cache / "sequences").iterdir()] == [d.name]


class FakeHub:
    def __init__(self, stored=None):
        self.stored, self.uploads = stored, 0

    def create_repo(self, *a, **k):
        pass

    def hf_hub_download(self, repo, filename, repo_type, local_dir):
        if self.stored is None:
            raise FileNotFoundError("no backup yet")
        path = os.path.join(local_dir, filename)
        with open(path, "wb") as f:
            f.write(self.stored)
        return path

    def upload_file(self, path_or_fileobj, **k):
        with open(path_or_fileobj, "rb") as f:
            self.stored = f.read()
        self.uploads += 1


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt, "DB", tmp_path / "hunt.sqlite")
    monkeypatch.setattr(backup.config, "BACKUP_REPO", "me/skyshift-hunt")
    monkeypatch.setattr(backup.config, "HF_TOKEN", "hf_x")
    monkeypatch.setattr(backup, "_last", {"mtime": None, "repo": False})
    return FakeHub()


def test_backup_uploads_only_changes_and_restores(hub, tmp_path):
    assert not backup.restore(hub)  # first run: nothing to restore
    with closing(hunt._db()) as con:
        hunt._player(con, "ana")
        con.commit()
    assert backup.sync(hub) and not backup.sync(hub) and hub.uploads == 1
    hunt.DB.unlink()  # the host wiped its disk
    hunt._ready.clear()
    assert backup.restore(hub)
    with closing(sqlite3.connect(hunt.DB)) as con:
        assert con.execute("select name from players").fetchall() == [("ana",)]


def test_backup_off_without_settings(monkeypatch):
    monkeypatch.setattr(backup.config, "BACKUP_REPO", None)
    assert not backup.enabled() and not backup.sync() and not backup.restore()


def test_entry_array_round_trips(tmp_path):
    arr = np.arange(16, dtype=np.float32).reshape(4, 4)
    np.save(tmp_path / "0.npy", arr)
    seq = {"dir": tmp_path, "status": ["ready"]}
    assert np.array_equal(np.frombuffer(sequences.entry_bytes(seq, 0), "<f4"), arr.ravel())
