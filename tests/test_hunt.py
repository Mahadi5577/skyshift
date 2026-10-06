import pytest

from backend import hunt


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt, "STORE", tmp_path / "hunt.json")
    hunt._rounds.clear()


def practice_round(rid="r1"):
    hunt._rounds[rid] = {"id": rid, "seq_id": "0" * 16, "practice": True, "player": "ana",
                         "fake": {"x0": 10, "y0": 10, "dx": 8, "dy": 0, "snr": 12, "psf_sigma": 0.9}}
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
    res = hunt.answer(practice_round(), [14, 11])
    assert res["found"] and res["streak"] == 1 and res["skill"] > 0.5


def test_practice_miss_and_nothing():
    assert not hunt.answer(practice_round("a"), [30, 30])["found"]
    res = hunt.answer(practice_round("b"), None)
    assert not res["found"] and res["streak"] == 0


def test_round_can_only_be_answered_once():
    rid = practice_round()
    hunt.answer(rid, None)
    with pytest.raises(LookupError):
        hunt.answer(rid, None)


def test_real_flag_matches_known_object():
    hunt._rounds["r"] = {"id": "r", "seq_id": "0" * 16, "practice": False, "player": "ana"}
    known = {"objects": [{"name": "(10) Hygiea", "positions": {"0": [20.0, 20.0]}}]}
    res = hunt.answer("r", [21, 20], known)
    assert res["flagged"] and res["known_match"] == "(10) Hygiea"


def test_board_groups_flags_and_ranks_unknown_first(monkeypatch):
    from backend import sequences
    seq = {"meta": {"ra": 180.0, "dec": 0.0, "n": 48, "zoom": "days"}}
    monkeypatch.setattr(hunt.sequences, "get", lambda seq_id: seq)
    for i, (player, click, known) in enumerate([("ana", [10, 10], None), ("bo", [11, 10], None),
                                                ("ana", [30, 30], {"objects": [
                                                    {"name": "(9) Metis", "positions": {"0": [30, 30]}}]})]):
        hunt._rounds[f"r{i}"] = {"id": f"r{i}", "seq_id": "0" * 16, "practice": False, "player": player}
        hunt.answer(f"r{i}", click, known)
    cands = hunt.board()["candidates"]
    assert [c["votes"] for c in cands] == [2, 1]
    assert cands[0]["known"] is None and cands[1]["known"] == "(9) Metis"
    assert sequences  # imported to make the monkeypatch target explicit
