"""On-board side of the downlink.

Sends the session log line by line (the exact hash-chained text, so the
ground verifies the same chain) and one JPEG per step completion and per
violation -- never raw video. Everything is kept until the ground
acknowledges it and re-sent after a drop (store-and-forward), so a link
outage loses nothing but time.

Rules it keeps, like every runtime stage:
* It never blocks the session: callers only enqueue; one worker thread
  connects, encodes JPEGs and sends.
* Frames are only referenced (capture hands out a fresh array per
  frame), 4 per second for the last few seconds; resizing and JPEG
  encoding happen on the worker, never on the capture path.
* Images are authenticated: after encoding, the JPEG's sha256 is logged
  as a `snapshot` line through the session, so the hash chain attests
  each image the ground receives.

Link simulation (off by default): a one-way delay (Moon ~1.3 s) and a
bandwidth cap, to demonstrate the degraded path honestly.
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from src.link.wire import encode, read_message, snapshot_name


@dataclass(frozen=True)
class DownlinkConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 5055
    snapshot_on: tuple[str, ...] = ("step_complete", "violation")
    snapshot_width: int = 640
    jpeg_quality: int = 70
    ring_s: float = 3.0  # how far back a snapshot may reach for its frame
    ring_hz: float = 4.0  # frames kept per second
    max_buffer_mb: float = 32.0  # unacknowledged data kept; oldest images dropped beyond
    simulate_delay_s: float = 0.0  # one-way light-time, e.g. 1.3 for the Moon
    max_kbps: float = 0.0  # 0 = unlimited
    reconnect_s: float = 2.0
    flush_s: float = 3.0  # at stop, how long to wait for the ground to take everything

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "DownlinkConfig":
        d = dict(cfg.get("downlink") or {})
        if "snapshot_on" in d:
            d["snapshot_on"] = tuple(d["snapshot_on"])
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def with_target(self, target: str) -> "DownlinkConfig":
        """'host' or 'host:port' -> enabled config aimed there."""
        host, _, port = target.rpartition(":") if ":" in target else (target, "", "")
        return replace(self, enabled=True, host=host or target, port=int(port) if port else self.port)


@dataclass
class DownlinkStats:
    connected: bool = False
    bytes_sent: int = 0
    log_bytes: int = 0
    snapshot_bytes: int = 0
    other_bytes: int = 0
    log_lines: int = 0
    snapshots: int = 0
    dropped_snapshots: int = 0
    resent: int = 0
    connects: int = 0
    unacked: int = 0
    last_error: str = ""
    by_session: dict[str, int] = field(default_factory=dict)


class Downlink:
    def __init__(self, cfg: DownlinkConfig,
                 attest: Callable[[str, float, dict[str, Any]], None] | None = None,
                 printer: Callable[[str], None] = print, *, send: bool = True,
                 save_root: Path | None = None, link_id: str | None = None) -> None:
        """send=False: never connects -- the fully offline mode. Event images
        are still taken, attested in the log and, with save_root, kept on
        disk (<save_root>/<session>/snapshots/) so the session can be sent to
        Earth later (src/link/upload.py). link_id: fixed for an upload, so a
        re-send after a drop resumes where the ground stopped."""
        self.cfg = cfg
        self.attest = attest
        self.printer = printer
        self.send = send
        self.save_root = Path(save_root) if save_root is not None else None
        self.link_id = link_id or uuid.uuid4().hex[:12]
        self.stats = DownlinkStats()
        self._lock = threading.Condition()
        self._outbox: list[dict[str, Any]] = []  # unacknowledged, msg_id order
        self._next_id = 1
        self._sent_upto = 0  # on the current connection
        self._acked = 0
        self._ring: deque[tuple[float, Any]] = deque(maxlen=max(1, int(cfg.ring_s * cfg.ring_hz) + 1))
        self._last_ring_ts = -1e9
        self._jobs: deque[dict[str, Any]] = deque()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Producers (other threads -- enqueue only)
    # ------------------------------------------------------------------

    def offer_frame(self, ts: float, image: Any) -> None:
        if ts - self._last_ring_ts >= 1.0 / self.cfg.ring_hz:
            self._last_ring_ts = ts
            self._ring.append((ts, image))

    def begin_session(self, session_id: str, info: dict[str, Any]) -> None:
        self._save_json(session_id, "info.json", info)
        self._enqueue({"kind": "hello", "session_id": session_id, "info": info})

    def send_steps(self, session_id: str, steps: list[dict[str, Any]]) -> None:
        self._save_json(session_id, "steps.json", steps)
        self._enqueue({"kind": "steps", "session_id": session_id, "steps": steps})

    def send_log_line(self, session_id: str, text: str) -> None:
        self._enqueue({"kind": "log", "session_id": session_id, "line": text})

    def send_snapshot(self, session_id: str, for_seq: int, label: str, jpeg: bytes,
                      event_type: str | None = None) -> None:
        self._enqueue({"kind": "snapshot", "session_id": session_id, "for_seq": for_seq, "label": label,
                       "event_type": event_type, "sha256": hashlib.sha256(jpeg).hexdigest()}, jpeg)

    def wait_delivered(self, timeout_s: float) -> bool:
        """Every message enqueued so far acknowledged by the ground."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if not self._jobs and not self._pending():
                return True
            time.sleep(0.05)
        return False

    def session_dir(self, session_id: str) -> Path | None:
        return None if self.save_root is None else self.save_root / session_id

    def _save_json(self, session_id: str, name: str, data: Any) -> None:
        d = self.session_dir(session_id)
        if d is None:
            return
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError as exc:
            self.stats.last_error = f"could not save {name}: {exc}"

    def send_report(self, session_id: str, text: str) -> None:
        self._enqueue({"kind": "report", "session_id": session_id}, text.encode("utf-8"))

    def on_log_line(self, text: str, rec: dict[str, Any]) -> None:
        """SessionLogger hook: the exact line as written."""
        self._enqueue({"kind": "log", "session_id": rec.get("session_id"), "line": text})
        if rec.get("event_type") in self.cfg.snapshot_on:
            frame = self._frame_near(float(rec.get("ts_monotonic") or 0.0))
            if frame is not None:
                label = rec.get("step_id") or rec.get("violation_type") or rec.get("event_type")
                if rec.get("event_type") == "violation":
                    label = f"{rec.get('violation_type')} {rec.get('target') or ''}".strip()
                with self._lock:
                    self._jobs.append({"session_id": rec.get("session_id"), "seq": rec.get("seq"),
                                       "event_type": rec.get("event_type"), "label": label,
                                       "frame_ts": frame[0], "image": frame[1]})
                    self._lock.notify_all()

    def _frame_near(self, ts: float) -> tuple[float, Any] | None:
        ring = list(self._ring)
        if not ring:
            return None
        best = min(ring, key=lambda f: abs(f[0] - ts))
        return best if abs(best[0] - ts) <= self.cfg.ring_s else None

    def _enqueue(self, header: dict[str, Any], payload: bytes = b"") -> None:
        if not self.send:
            return  # fully offline: nothing is queued for a link
        with self._lock:
            header = {**header, "msg_id": self._next_id, "link_id": self.link_id}
            self._next_id += 1
            self._outbox.append({"header": header, "payload": payload,
                                 "due": time.monotonic() + self.cfg.simulate_delay_s})
            self._trim_locked()
            self._lock.notify_all()

    def _trim_locked(self) -> None:
        """Keep unacknowledged data under max_buffer_mb: drop the payload of
        the OLDEST images first. Log lines are never dropped (tiny, and the
        record of truth)."""
        cap = self.cfg.max_buffer_mb * 1e6
        total = sum(len(m["payload"]) for m in self._outbox)
        for m in self._outbox:
            if total <= cap:
                break
            if m["header"]["kind"] == "snapshot" and m["payload"]:
                total -= len(m["payload"])
                m["payload"] = b""
                m["header"] = {**m["header"], "dropped": True}
                self.stats.dropped_snapshots += 1

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="downlink", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        deadline = time.monotonic() + self.cfg.flush_s + self.cfg.simulate_delay_s
        while time.monotonic() < deadline and (self._jobs or (self.send and self._pending())):
            time.sleep(0.05)
        self._stop.set()
        with self._lock:
            self._lock.notify_all()
        if self._thread is not None:
            self._thread.join(3.0)
        self._close()

    def _pending(self) -> bool:
        """Delivered = ACKNOWLEDGED by the ground, not merely written to the
        socket: bytes still in flight are lost if the connection resets."""
        with self._lock:
            return self._acked < self._next_id - 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = self.stats
            return {"target": f"{self.cfg.host}:{self.cfg.port}", "sending": self.send, "connected": s.connected,
                    "bytes_sent": s.bytes_sent, "log_bytes": s.log_bytes,
                    "snapshot_bytes": s.snapshot_bytes, "log_lines": s.log_lines,
                    "snapshots": s.snapshots, "dropped_snapshots": s.dropped_snapshots,
                    "resent": s.resent, "connects": s.connects,
                    "queued": max(0, self._next_id - 1 - self._sent_upto),
                    "unacked": len(self._outbox), "acked": self._acked, "last_error": s.last_error,
                    "delay_s": self.cfg.simulate_delay_s, "max_kbps": self.cfg.max_kbps}

    def _run(self) -> None:
        next_try = 0.0
        while not self._stop.is_set():
            self._encode_jobs()
            if not self.send:  # offline: only images to disk
                with self._lock:
                    self._lock.wait(0.2)
                continue
            if self._sock is None:
                if time.monotonic() >= next_try:
                    self._connect()
                    next_try = time.monotonic() + self.cfg.reconnect_s
                if self._sock is None:
                    with self._lock:
                        self._lock.wait(0.2)
                    continue
            msg = self._next_due()
            if msg is None:
                with self._lock:
                    self._lock.wait(0.05)
                continue
            try:
                self._send(msg)
            except OSError as exc:
                self._lost(f"send failed: {exc}")

    def _encode_jobs(self) -> None:
        while True:
            with self._lock:
                if not self._jobs:
                    return
                job = self._jobs.popleft()
            try:
                jpeg = self._jpeg(job["image"])
            except Exception as exc:  # noqa: BLE001 -- never let one image stop the link
                self.stats.last_error = f"snapshot encode failed: {exc}"
                continue
            sha = hashlib.sha256(jpeg).hexdigest()
            d = self.session_dir(job["session_id"])
            if d is not None:  # always kept on board: "send to Earth later" needs it
                try:
                    (d / "snapshots").mkdir(parents=True, exist_ok=True)
                    (d / "snapshots" / snapshot_name(job["seq"], job["label"])).write_bytes(jpeg)
                except OSError as exc:
                    self.stats.last_error = f"could not save snapshot: {exc}"
            header = {"kind": "snapshot", "session_id": job["session_id"], "for_seq": job["seq"],
                      "event_type": job["event_type"], "label": job["label"],
                      "frame_ts": job["frame_ts"], "sha256": sha}
            self._enqueue(header, jpeg)
            if self.attest is not None:
                try:
                    self.attest(job["session_id"], job["frame_ts"],
                                {"sha256": sha, "bytes": len(jpeg), "for_seq": job["seq"],
                                 "label": job["label"]})
                except Exception:  # noqa: BLE001
                    pass

    def _jpeg(self, image: Any) -> bytes:
        import cv2

        h, w = image.shape[:2]
        if w > self.cfg.snapshot_width:
            image = cv2.resize(image, (self.cfg.snapshot_width, int(h * self.cfg.snapshot_width / w)),
                               interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self.cfg.jpeg_quality])
        if not ok:
            raise ValueError("imencode failed")
        return buf.tobytes()

    def _next_due(self) -> dict[str, Any] | None:
        with self._lock:
            for m in self._outbox:
                if m["header"]["msg_id"] > self._sent_upto:
                    return m if m["due"] <= time.monotonic() else None
        return None

    def _send(self, m: dict[str, Any]) -> None:
        data = encode(m["header"], m["payload"])
        assert self._sock is not None
        self._sock.sendall(data)
        n = len(data)
        with self._lock:
            mid = m["header"]["msg_id"]
            if m.get("sent"):
                self.stats.resent += 1
            m["sent"] = True
            self._sent_upto = max(self._sent_upto, mid)
            s = self.stats
            s.bytes_sent += n
            kind = m["header"]["kind"]
            if kind == "log":
                s.log_bytes += n
                s.log_lines += 1
            elif kind == "snapshot":
                s.snapshot_bytes += n
                s.snapshots += 1
            else:
                s.other_bytes += n
            sid = m["header"].get("session_id") or ""
            s.by_session[sid] = s.by_session.get(sid, 0) + n
        if self.cfg.max_kbps > 0:
            time.sleep(n * 8 / (self.cfg.max_kbps * 1000.0))

    def _connect(self) -> None:
        try:
            sock = socket.create_connection((self.cfg.host, self.cfg.port), timeout=3.0)
            sock.sendall(encode({"kind": "link", "link_id": self.link_id}))
            sock.settimeout(5.0)
            header, _ = read_message(sock)
            if header.get("kind") != "resume":
                raise ConnectionError(f"expected resume, got {header.get('kind')}")
            sock.settimeout(None)
        except (OSError, ValueError, ConnectionError) as exc:
            with self._lock:
                if self.stats.last_error != str(exc):
                    self.stats.last_error = f"ground not reachable: {exc}"
            return
        with self._lock:
            self._sock = sock
            last = int(header.get("last_msg_id", 0))
            self._ack_locked(last)
            self._sent_upto = last  # resend everything after what the ground holds
            self.stats.connected = True
            self.stats.connects += 1
            self.stats.last_error = ""
        self.printer(f"downlink: connected to ground {self.cfg.host}:{self.cfg.port} "
                     f"(ground holds up to msg {last})")
        threading.Thread(target=self._read_acks, args=(sock,), name="downlink_acks", daemon=True).start()

    def _read_acks(self, sock: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                header, _ = read_message(sock)
                if header.get("kind") == "ack":
                    with self._lock:
                        self._ack_locked(int(header.get("last_msg_id", 0)))
        except (OSError, ValueError, ConnectionError) as exc:
            if self._sock is sock:
                self._lost(f"link lost: {exc}")

    def _ack_locked(self, last: int) -> None:
        self._acked = max(self._acked, last)
        self._outbox = [m for m in self._outbox if m["header"]["msg_id"] > self._acked]
        self.stats.unacked = len(self._outbox)

    def _lost(self, why: str) -> None:
        with self._lock:
            was = self.stats.connected
            self.stats.connected = False
            self.stats.last_error = why
        self._close()
        if was:
            self.printer(f"downlink: {why} -- buffering, will resend on reconnect")

    def _close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)  # graceful: no reset of data in flight
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
