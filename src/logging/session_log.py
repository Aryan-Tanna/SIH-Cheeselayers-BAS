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
from typing import Any, TextIO

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
    prev_hash: str
    hash: str


class SessionLogger:
    """Append-only writer. One instance per session, one file handle held
    open for the session's duration."""

    def __init__(self, path: str | Path, session_id: str) -> None:
        self.path = Path(path)
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
            "prev_hash": self._prev_hash,
        }
        h = _line_hash(self._prev_hash, payload)
        line = LogLine(**payload, hash=h)  # type: ignore[arg-type]

        self._fh.write(json.dumps(asdict(line), sort_keys=True) + "\n")
        self._fh.flush()

        self._prev_hash = h
        self._seq += 1
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
    Only the fields the JSONL schema actually carries are populated; a
    resumed engine only needs event_type + step_id to reconstruct
    `complete`, so the rest (violation_type, target, message, ...) are
    intentionally left None rather than guessed.
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
        )
        for rec in load_events(path)
    ]
