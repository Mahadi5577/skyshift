from contextlib import closing

import numpy as np
import pytest

from backend import hunt

FAKE = {"x0": 10, "y0": 10, "dx": 8, "dy": 0, "snr": 12, "psf_sigma": 0.9}


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt, "DB", tmp_path / "hunt.sqlite")


def add_round(rid, practice=True, player="ana", seq_id="0" * 16):
    with closing(hunt._db()) as con:
        hunt._save_round(con, {"id": rid, "seq_id": seq_id, "practice": practice, "player": player,
                               "fake": FAKE if practice else None})
        con.commit()
    return rid


def test_distance_to_track():
    fake = {"x0": 0, "y0": 0, "dx": 10, "dy": 0}
    assert hunt._dist_to_track(fake, 5, 0) == 0
    assert hunt._dist_to_track(fake, 5, 2) == pytest.approx(2)
    assert hunt._dist_to_track(fake, -3, 4) == pytest.approx(5)  # beyond the start: distance to x0


def test_skill_prior():
    assert hunt.skill({"rounds": 0, "hits": 0}) == 0.5
    assert hunt.skill({"rounds": 8, "hits": 8}) == 0.9


def test_practice_hit_raises_skill_and_streak():
    res = hunt.answer(add_round("r1"), [14, 11])
    assert res["found"] and res["streak"] == 1 and res["skill"] > 0.5


def test_practice_miss_and_nothing():
    assert not hunt.answer(add_round("a"), [30, 30])["found"]
    res = hunt.answer(add_round("b"), None)
    assert not res["found"] and res["streak"] == 0


def test_round_can_only_be_answered_once():
    rid = add_round("r1")
    hunt.answer(rid, None)
    with pytest.raises(LookupError):
        hunt.answer(rid, None)


def test_stats_survive_a_restart():
    hunt.answer(add_round("r1"), [14, 10])
    hunt._ready.clear()  # a new process opens the same file
    res = hunt.answer(add_round("r2"), [14, 10])
    assert res["rounds"] == 2 and res["streak"] == 2


def test_player_name_belongs_to_first_key(monkeypatch):
    monkeypatch.setattr(hunt.sequences, "cached_sequences",
                        lambda: [{"id": "0" * 16, "n": 48, "zoom": "days", "entries": []}])
    hunt.new_round("ana", "k" * 32)
    hunt.new_round("ana", "k" * 32)
    with pytest.raises(hunt.NameTaken):
        hunt.new_round("ana", "x" * 32)


def test_new_round_hides_the_fake(monkeypatch):
    monkeypatch.setattr(hunt.sequences, "cached_sequences",
                        lambda: [{"id": "0" * 16, "n": 48, "zoom": "days",
                                  "entries": [{"mjd": 1.0, "date": "d", "wave": 1.3, "label": "img-id"}]}])
    monkeypatch.setattr(hunt, "PRACTICE_SHARE", 1.0)
    r = hunt.new_round("ana", "k" * 32)
    assert r["practice"] and r["snr"] == 12
    assert not {"fake", "seq_id"} & r.keys() and "label" not in r["entries"][0]
    assert hunt.get_round(r["round_id"])["fake"]["snr"] == 12


def test_plant_peak_matches_requested_snr():
    rng = np.random.default_rng(1)
    arr = rng.normal(0, 2.0, (48, 48)).astype(np.float32)
    out = hunt.plant(arr, 20.0, 30.0, 8, 0.9)
    added = out - arr
    assert added[30, 20] == pytest.approx(8 * 2.0, rel=0.1)  # row = y, column = x
    assert added[0, 0] == 0 and np.argmax(added) == 30 * 48 + 20


def test_round_frame_plants_the_fake_along_its_track(monkeypatch):
    frames = [np.random.default_rng(i).normal(0, 1, (48, 48)).astype(np.float32) for i in range(3)]
    seq = {"meta": {"entries": [{"mjd": 0.0}, {"mjd": 0.5}, {"mjd": 1.0}]}, "status": ["ready"] * 3}
    monkeypatch.setattr(hunt.sequences, "get", lambda seq_id: seq)
    monkeypatch.setattr(hunt.sequences, "entry_array", lambda s, i: frames[i])
    rid = add_round("r1")
    last = np.frombuffer(hunt.round_frame(rid, 2), "<f4").reshape(48, 48) - frames[2]
    assert np.unravel_index(np.argmax(last), last.shape) == (10, 18)  # x0 + dx at the last frame
    add_round("r2", practice=False)
    assert np.array_equal(np.frombuffer(hunt.round_frame("r2", 0), "<f4").reshape(48, 48), frames[0])
    assert hunt.round_frame("missing", 0) is None


def test_real_flag_matches_known_object():
    known = {"objects": [{"name": "(10) Hygiea", "positions": {"0": [20.0, 20.0]}}]}
    res = hunt.answer(add_round("r", practice=False), [21, 20], known)
    assert res["flagged"] and res["known_match"] == "(10) Hygiea"


def test_board_groups_flags_and_ranks_unknown_first(monkeypatch):
    seq = {"meta": {"ra": 180.0, "dec": 0.0, "n": 48, "zoom": "days"}}
    monkeypatch.setattr(hunt.sequences, "get", lambda seq_id: seq)
    for i, (player, click, known) in enumerate([("ana", [10, 10], None), ("bo", [11, 10], None),
                                                ("ana", [30, 30], {"objects": [
                                                    {"name": "(9) Metis", "positions": {"0": [30, 30]}}]})]):
        hunt.answer(add_round(f"r{i}", practice=False, player=player), click, known)
    monkeypatch.setattr(hunt.sequences, "get", lambda seq_id: None)  # board must not need the cache
    data = hunt.board()
    cands = data["candidates"]
    assert [c["votes"] for c in cands] == [2, 1] and data["players"] == 2
    assert cands[0]["known"] is None and cands[1]["known"] == "(9) Metis"
    assert cands[0]["zoom"] == "days" and abs(cands[0]["ra"] - 180) < 0.1
