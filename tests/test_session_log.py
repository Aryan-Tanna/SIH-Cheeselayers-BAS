import json

from src.logging.session_log import SessionLogger, verify_chain
from src.protocol.events import EngineEvent


def make_event(i: int) -> EngineEvent:
    return EngineEvent(
        ts_monotonic=float(i),
        event_type="step_complete",
        step_id=f"step_{i}",
        status="complete",
        confidence=0.9,
    )


def test_log_round_trip_and_verify(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        for i in range(5):
            logger.log_event(make_event(i))

    result = verify_chain(path)
    assert result.ok is True
    assert result.lines_checked == 5


def test_tampering_a_line_breaks_the_chain(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        for i in range(5):
            logger.log_event(make_event(i))

    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    rec["step_id"] = "tampered"
    lines[2] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.ok is False
    assert result.first_bad_seq == 2


def test_deleting_a_line_breaks_the_chain(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        for i in range(5):
            logger.log_event(make_event(i))

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[2]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.ok is False


def test_reopening_logger_continues_the_chain(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        logger.log_event(make_event(0))
        logger.log_event(make_event(1))

    with SessionLogger(path, session_id="s1") as logger:
        logger.log_event(make_event(2))

    result = verify_chain(path)
    assert result.ok is True
    assert result.lines_checked == 3

    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert [rec["seq"] for rec in lines] == [0, 1, 2]


def test_ts_monotonic_is_preserved_not_processing_time(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        line = logger.log_event(make_event(0))
    assert line.ts_monotonic == 0.0


# --- audit fields: target / severity / message / extra (2026-09-24) -----------

def test_violation_and_command_details_are_logged_and_hash_covered(tmp_path):
    from src.logging.session_log import load_events, load_events_for_resume

    path = tmp_path / "s.jsonl"
    with SessionLogger(path, session_id="s1") as logger:
        logger.log_event(EngineEvent(ts_monotonic=1.0, event_type="violation",
                                     violation_type="out_of_order", severity="caution",
                                     target="module_a", root_cause_id="close_a_lid",
                                     message="attempted early", extra={"unmet": ["stow_a_lid"]}))
        logger.log_event(EngineEvent(ts_monotonic=2.0, event_type="operator_command",
                                     message="quiet_mode"))
    recs = load_events(path)
    assert (recs[0]["target"], recs[0]["severity"], recs[0]["extra"]) == (
        "module_a", "caution", {"unmet": ["stow_a_lid"]})
    assert recs[1]["message"] == "quiet_mode"
    assert verify_chain(path).ok
    back = load_events_for_resume(path)
    assert back[0].extra == {"unmet": ["stow_a_lid"]} and back[1].message == "quiet_mode"

    # tampering with a new field breaks the chain like any other
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["message"] = "voice_mode"
    lines[1] = json.dumps(rec, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not verify_chain(path).ok


def test_log_written_before_the_new_fields_still_verifies(tmp_path):
    from src.logging.session_log import GENESIS_HASH, _line_hash, load_events_for_resume

    path = tmp_path / "old.jsonl"
    prev, out = GENESIS_HASH, []
    for i in range(3):
        payload = {"seq": i, "session_id": "old", "ts_utc": "2026-09-20T00:00:00+00:00",
                   "ts_monotonic": float(i), "step_id": f"s{i}", "event_type": "step_complete",
                   "status": "complete", "confidence": 1.0, "violation_type": None,
                   "root_cause_id": None, "operator": None, "geometry_status": None,
                   "prev_hash": prev}
        h = _line_hash(prev, payload)
        out.append(json.dumps({**payload, "hash": h}, sort_keys=True))
        prev = h
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    assert verify_chain(path).ok
    events = load_events_for_resume(path)
    assert events[0].message is None and events[0].extra == {}
