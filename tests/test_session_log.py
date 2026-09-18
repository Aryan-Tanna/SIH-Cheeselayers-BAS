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
