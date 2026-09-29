"""Past sessions for the start screen: on the station, the local logs
(logs/*.jsonl); on Earth, what the ground station received
(ground_archive/<session>/). Every row is read from the log itself and
its hash chain re-verified, so the list can never claim more than the
record shows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging.session_log import load_events, verify_chain


def summarize_log(log: Path, title: str | None = None) -> dict[str, Any]:
    events = load_events(log)
    chain = verify_chain(log)
    start = next((e for e in events if e.get("event_type") == "session_start"), events[0] if events else {})
    protocol = str(start.get("message") or "").removeprefix("session start: ")
    try:
        when = datetime.fromisoformat(start["ts_utc"]).astimezone().strftime("%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        when = ""
    span = (events[-1]["ts_monotonic"] - events[0]["ts_monotonic"]) if len(events) > 1 else 0.0
    return {
        "session_id": start.get("session_id") or log.stem,
        "when": when,
        "experiment": title or protocol,
        "duration_s": round(span, 1),
        "steps_done": len({e.get("step_id") for e in events if e.get("event_type") == "step_complete"}),
        "violations": sum(1 for e in events if e.get("event_type") == "violation"),
        "chain_ok": chain.ok,
        "lines": chain.lines_checked,
        "log": str(log),
    }


def list_local_sessions(log_dir: Path, limit: int = 40) -> list[dict[str, Any]]:
    """Newest first. The report sits next to its log (<session>.report.txt)."""
    logs = sorted(Path(log_dir).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for log in logs:
        try:
            row = summarize_log(log)
        except (OSError, ValueError, KeyError):
            continue
        rep = log.with_suffix(".report.txt")
        row["report"] = str(rep) if rep.is_file() else None
        row["folder"] = str(log.parent / log.stem) if (log.parent / log.stem).is_dir() else str(log.parent)
        from src.link.upload import sent_info

        sent = sent_info(log)
        row["sent"] = sent
        row["images"] = len(list((log.parent / log.stem / "snapshots").glob("*.jpg")))
        out.append(row)
    return out


def list_ground_sessions(archive: Path, limit: int = 40) -> list[dict[str, Any]]:
    """What reached Earth, newest first, with how many images arrived."""
    dirs = [d for d in Path(archive).glob("*") if (d / "session.jsonl").is_file()]
    dirs.sort(key=lambda d: (d / "session.jsonl").stat().st_mtime, reverse=True)
    out = []
    for d in dirs[:limit]:
        title = None
        try:
            title = json.loads((d / "info.json").read_text(encoding="utf-8")).get("title")
        except (OSError, ValueError):
            pass
        try:
            row = summarize_log(d / "session.jsonl", title)
        except (OSError, ValueError, KeyError):
            continue
        row["images"] = len(list((d / "snapshots").glob("*.jpg")))
        row["report"] = str(d / "report.txt") if (d / "report.txt").is_file() else None
        row["folder"] = str(d)
        out.append(row)
    return out
