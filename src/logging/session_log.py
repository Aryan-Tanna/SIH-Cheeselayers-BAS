"""JSONL, append-only session log with hash-chain tamper evidence.

One event per line. Each line's `hash` covers the previous line's hash
plus this line's own content, so altering or deleting any line breaks
every hash after it — `verify_chain()` walks the file and reports the
first broken link.

ts_monotonic must be the frame-acquisition timestamp, never a
processing-time timestamp — that is the caller's responsibility (see
src/protocol/events.py's EngineEvent, which already carries the right
value through from the source event).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from src.protocol.events import EngineEvent

GENESIS_HASH = "0" * 64


def _canonical(d: dict[str, Any]) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def _line_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(_canonical(payload).encode("utf-8"))
    return h.hexdigest()


@dataclass
class LogLine:
    seq: int
    session_id: str
    ts_utc: str
    ts_monotonic: float
    step_id: str | None
    event_type: str
    status: str | None
    confidence: float | None
    violation_type: str | None
    root_cause_id: str | None
    operator: str | None
    geometry_status: str | None
    # Added 2026-09-24: without these the log said an operator_command
    # happened but not WHICH (quiet? a refused "next step"?), and a
    # violation line had no target or severity -- an audit record that
    # can't answer "what was said and to whom". Older logs lack them and
    # still verify: verify_chain hashes whatever fields a line carries.
    target: str | None
    severity: str | None
    message: str | None
    extra: dict[str, Any]
    prev_hash: str
    hash: str


class SessionLogger:
    """Append-only writer. One instance per session, one file handle held
    open for the session's duration."""

    def __init__(self, path: str | Path, session_id: str,
                 on_line: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        """on_line(text, record) is called after each line is written and
        flushed, with the EXACT text of the line (the downlink sends it
        byte for byte, so the ground can verify the same chain)."""
        self.path = Path(path)
        self.on_line = on_line
        self.session_id = session_id
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = open(self.path, "a", encoding="utf-8")
        if self.path.stat().st_size > 0:
            self._seq, self._prev_hash = _tail_state(self.path)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def log_event(self, event: EngineEvent) -> LogLine:
        payload = {
            "seq": self._seq,
            "session_id": self.session_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ts_monotonic": event.ts_monotonic,
            "step_id": event.step_id,
            "event_type": event.event_type,
            "status": event.status,
            "confidence": event.confidence,
            "violation_type": event.violation_type,
            "root_cause_id": event.root_cause_id,
            "operator": event.operator,
            "geometry_status": event.geometry_status,
            "target": event.target,
            "severity": event.severity,
            "message": event.message,
            "extra": dict(event.extra),
            "prev_hash": self._prev_hash,
        }
        h = _line_hash(self._prev_hash, payload)
        line = LogLine(**payload, hash=h)  # type: ignore[arg-type]

        record = asdict(line)
        text = json.dumps(record, sort_keys=True)
        self._fh.write(text + "\n")
        self._fh.flush()

        self._prev_hash = h
        self._seq += 1
        if self.on_line is not None:
            try:
                self.on_line(text, record)
            except Exception:  # noqa: BLE001 -- a listener must never break the log
                pass
        return line


def _tail_state(path: Path) -> tuple[int, str]:
    last: dict[str, Any] | None = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                last = json.loads(raw)
    if last is None:
        return 0, GENESIS_HASH
    return last["seq"] + 1, last["hash"]


@dataclass
class VerifyResult:
    ok: bool
    lines_checked: int
    first_bad_seq: int | None
    reason: str | None


def check_line(prev_hash: str, rec: dict[str, Any]) -> str | None:
    """One link of the chain: None if `rec` follows `prev_hash` and its own
    hash is right, else the reason. The ground station runs this on each
    line as it arrives."""
    if rec.get("prev_hash") != prev_hash:
        return (f"prev_hash mismatch at seq={rec.get('seq')}: line claims "
                f"{rec.get('prev_hash')}, chain expects {prev_hash}")
    payload = {k: v for k, v in rec.items() if k != "hash"}
    if _line_hash(prev_hash, payload) != rec.get("hash"):
        return f"hash mismatch at seq={rec.get('seq')}: the line was altered"
    return None


def verify_chain(path: str | Path) -> VerifyResult:
    prev_hash = GENESIS_HASH
    count = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            rec = json.loads(raw)
            claimed_hash = rec["hash"]
            claimed_prev = rec["prev_hash"]
            if claimed_prev != prev_hash:
                return VerifyResult(
                    ok=False,
                    lines_checked=count,
                    first_bad_seq=rec.get("seq"),
                    reason=(
                        f"prev_hash mismatch: line claims prev={claimed_prev}, "
                        f"chain expects {prev_hash}"
                    ),
                )
            payload = {k: v for k, v in rec.items() if k != "hash"}
            recomputed = _line_hash(claimed_prev, payload)
            if recomputed != claimed_hash:
                return VerifyResult(
                    ok=False,
                    lines_checked=count,
                    first_bad_seq=rec.get("seq"),
                    reason=f"hash mismatch at seq={rec.get('seq')}",
                )
            prev_hash = claimed_hash
            count += 1
    return VerifyResult(ok=True, lines_checked=count, first_bad_seq=None, reason=None)


def load_events(path: str | Path) -> list[dict[str, Any]]:
    """Read a session log back as plain dicts."""
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
    return out


def load_events_for_resume(path: str | Path) -> list[EngineEvent]:
    """Read a session log back as the EngineEvent list ProtocolEngine.resume()
    expects — the log→resume round trip CLAUDE.md's "support session
    resume — reload a session log and pick up mid-protocol" describes.
    A resumed engine only needs event_type + step_id (+ status) to
    reconstruct `complete`; the other fields are carried through when the
    log has them (logs written before 2026-09-24 lack target, severity,
    message and extra -- those come back as None / {}).
    """
    return [
        EngineEvent(
            ts_monotonic=rec["ts_monotonic"],
            event_type=rec["event_type"],
            step_id=rec.get("step_id"),
            status=rec.get("status"),
            confidence=rec.get("confidence"),
            violation_type=rec.get("violation_type"),
            root_cause_id=rec.get("root_cause_id"),
            operator=rec.get("operator"),
            geometry_status=rec.get("geometry_status"),
            target=rec.get("target"),
            severity=rec.get("severity"),
            message=rec.get("message"),
            extra=rec.get("extra") or {},
        )
        for rec in load_events(path)
    ]
