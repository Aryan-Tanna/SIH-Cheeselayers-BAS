import pytest

from scripts.split import SplitError, split_by_session


def _rows(session_prop_pairs):
    """session_prop_pairs: list of (clip_id, session_id, prop_family)"""
    return [
        {"clip_id": c, "session_id": s, "prop_family": p}
        for c, s, p in session_prop_pairs
    ]


def test_holdout_session_forced_into_val():
    rows = _rows([
        ("c1", "S00", "jar"), ("c2", "S00", "jar"),
        ("c3", "S01", "jar"), ("c4", "S02", "jar"),
    ])
    train, val = split_by_session(rows, val_fraction=0.0, seed=1, holdout_prop_family=None,
                                   holdout_session={"S02"})
    val_sessions = {r["session_id"] for r in val}
    train_sessions = {r["session_id"] for r in train}
    assert "S02" in val_sessions
    assert "S02" not in train_sessions


def test_unknown_holdout_session_raises():
    rows = _rows([("c1", "S00", "jar")])
    with pytest.raises(SplitError):
        split_by_session(rows, val_fraction=0.2, seed=1, holdout_prop_family=None,
                          holdout_session={"S99"})


def test_holdout_session_and_prop_family_combine():
    rows = _rows([
        ("c1", "S00", "jar"), ("c2", "S01", "slab"), ("c3", "S02", "jar"),
    ])
    train, val = split_by_session(rows, val_fraction=0.0, seed=1, holdout_prop_family="slab",
                                   holdout_session={"S02"})
    val_sessions = {r["session_id"] for r in val}
    # Both explicit holdouts must land in val; S00 may or may not join them
    # (pre-existing max(1, ...) behavior forces at least one val session
    # from whatever's left even at val_fraction=0.0 -- unrelated to this
    # change, not asserting on it either way).
    assert {"S01", "S02"} <= val_sessions
