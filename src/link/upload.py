"""Send a finished session to Earth later -- the fully offline mode.

The station works with no link at all: every session keeps, on board,
    logs/<session>.jsonl              the hash-chained log
    logs/<session>/snapshots/*.jpg    one image per step / alert (sha256 in the log)
    logs/<session>/info.json, steps.json
    logs/<session>.report.txt         the readable report
When a link window opens, upload_session() sends exactly those files over
the same wire as the live downlink, so Mission Control verifies them the
same way (chain line by line, each image against its attestation) and
archives the same byte-identical log. The link id is fixed per session,
so a re-send after a drop resumes where the ground stopped and a second
send of a complete session transfers nothing new.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.link.sender import Downlink, DownlinkConfig

SENT_MARKER = "sent_to_earth.json"


def session_files(log: Path) -> dict[str, Any]:
    d = log.parent / log.stem
    return {"log": log, "dir": d, "report": log.with_suffix(".report.txt"),
            "snapshots": sorted((d / "snapshots").glob("*.jpg")) if (d / "snapshots").is_dir() else []}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def upload_session(log: Path, host: str, port: int, timeout_s: float = 60.0,
                   cfg: DownlinkConfig | None = None) -> dict[str, Any]:
    """Send one stored session; returns what happened. Blocks (call it from
    a worker thread in a GUI)."""
    log = Path(log)
    f = session_files(log)
    sid = log.stem
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    base = cfg or DownlinkConfig()
    link = Downlink(replace(base, enabled=True, host=host, port=port, simulate_delay_s=0.0, max_kbps=0.0),
                    printer=lambda _m: None, link_id=f"upload-{sid}")
    info = _read_json(f["dir"] / "info.json", {})
    if not info:  # a session recorded before info.json existed
        first = json.loads(lines[0]) if lines else {}
        info = {"protocol_id": str(first.get("message") or "").removeprefix("session start: ")}
    link.begin_session(sid, {**info, "sent_later": True})
    steps = _read_json(f["dir"] / "steps.json", None)
    if steps:
        link.send_steps(sid, steps)
    for ln in lines:
        link.send_log_line(sid, ln)
    for img in f["snapshots"]:
        seq, _, label = img.stem.partition("_")
        link.send_snapshot(sid, int(seq) if seq.isdigit() else 0, label, img.read_bytes())
    if f["report"].is_file():
        link.send_report(sid, f["report"].read_text(encoding="utf-8"))
    link.start()
    ok = link.wait_delivered(timeout_s)
    st = link.status()
    link.stop()
    result = {"ok": ok, "session_id": sid, "target": f"{host}:{port}", "log_lines": len(lines),
              "images": len(f["snapshots"]), "report": f["report"].is_file(), "bytes_sent": st["bytes_sent"],
              "error": "" if ok else (st["last_error"] or "the ground did not confirm everything in time")}
    if ok:
        f["dir"].mkdir(parents=True, exist_ok=True)
        (f["dir"] / SENT_MARKER).write_text(json.dumps(
            {**result, "sent_utc": datetime.now(timezone.utc).isoformat()}, indent=1), encoding="utf-8")
    return result


def sent_info(log: Path) -> dict[str, Any] | None:
    """When / where this session was last sent in full, or None."""
    return _read_json(Path(log).parent / Path(log).stem / SENT_MARKER, None)
