"""Ground side of the downlink: receives, verifies, archives. No Tk here
(the Mission Control window, scripts/ground_station.py, only reads the
state this keeps), so all of it is unit-testable.

Per session it keeps ground_archive/<session_id>/:
    session.jsonl   the log, byte-identical to the one on board
    snapshots/      one JPEG per step / violation
    report.txt      the readable report, when the session ends

Verification, as data arrives:
* every log line is checked against the hash chain (check_line): the
  first altered, missing or reordered line marks the session TAMPERED;
* every image is checked twice: its bytes against the sha256 in its own
  header (transfer integrity), and that sha256 against a `snapshot` line
  IN the chain (the on-board system attested this exact image).
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.link.wire import encode, read_message, snapshot_name
from src.logging.session_log import GENESIS_HASH, check_line

ACK_EVERY_S = 0.5


class GroundSession:
    def __init__(self, session_id: str, root: Path) -> None:
        self.session_id = session_id
        self.dir = root / session_id
        (self.dir / "snapshots").mkdir(parents=True, exist_ok=True)
        self.info: dict[str, Any] = {}
        self.steps: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.attested: dict[str, int] = {}  # image sha256 -> log seq that attests it
        self.prev_hash = GENESIS_HASH
        self.chain_ok = True
        self.chain_error = ""
        self.report: str | None = None
        self.last_delay_s: float | None = None
        self.bytes = {"log": 0, "snapshot": 0, "other": 0}
        self.first_rx = time.time()
        self.last_rx = self.first_rx
        for name, attr in (("info.json", "info"), ("steps.json", "steps")):
            f = self.dir / name  # a restarted ground must not lose the title / checklist
            if f.is_file():
                try:
                    setattr(self, attr, json.loads(f.read_text(encoding="utf-8")))
                except ValueError:
                    pass
        if (self.dir / "report.txt").is_file():
            self.report = (self.dir / "report.txt").read_text(encoding="utf-8")
        snap_dir = self.dir / "snapshots"
        log = self.dir / "session.jsonl"
        if log.is_file():  # ground restarted mid-session: rebuild state, don't rewrite
            for raw in log.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    self._take_line(raw)
            for f in sorted(snap_dir.glob("*.jpg")):  # images already received
                data = f.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                seq = int(f.stem.split("_", 1)[0]) if f.stem[:5].isdigit() else 0
                self.snapshots.append({"file": str(f), "label": f.stem.split("_", 1)[-1], "event_type": None,
                                       "for_seq": seq, "sha256": sha, "bytes": len(data), "intact": True,
                                       "attested": sha in self.attested, "dropped": False, "rx": f.stat().st_mtime})
        self._log = open(log, "a", encoding="utf-8")

    def set_info(self, info: dict[str, Any]) -> None:
        self.info = info
        (self.dir / "info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")

    def set_steps(self, steps: list[dict[str, Any]]) -> None:
        self.steps = steps
        (self.dir / "steps.json").write_text(json.dumps(steps, indent=1), encoding="utf-8")

    def close(self) -> None:
        self._log.close()

    def add_line(self, text: str) -> None:
        self._log.write(text + "\n")
        self._log.flush()
        self._take_line(text)

    def _take_line(self, text: str) -> None:
        rec = json.loads(text)
        if self.chain_ok:
            err = check_line(self.prev_hash, rec)
            if err:
                self.chain_ok, self.chain_error = False, err
            else:
                self.prev_hash = rec["hash"]
        self.events.append(rec)
        if rec.get("event_type") == "snapshot":
            sha = (rec.get("extra") or {}).get("sha256")
            if sha:
                self.attested[sha] = rec["seq"]
                for s in self.snapshots:
                    if s["sha256"] == sha:
                        s["attested"] = True
        try:
            sent = datetime.fromisoformat(rec["ts_utc"])
            self.last_delay_s = (datetime.now(timezone.utc) - sent).total_seconds()
        except (KeyError, ValueError):
            pass

    def add_snapshot(self, header: dict[str, Any], jpeg: bytes) -> dict[str, Any]:
        sha = hashlib.sha256(jpeg).hexdigest()
        name = snapshot_name(header.get("for_seq"), header.get("label"))
        if jpeg:
            (self.dir / "snapshots" / name).write_bytes(jpeg)
        snap = {"file": str(self.dir / "snapshots" / name) if jpeg else None, "label": header.get("label"),
                "event_type": header.get("event_type"), "for_seq": header.get("for_seq"),
                "sha256": header.get("sha256"), "bytes": len(jpeg),
                "intact": bool(jpeg) and sha == header.get("sha256"),
                "attested": header.get("sha256") in self.attested,
                "dropped": bool(header.get("dropped")), "rx": time.time()}
        self.snapshots.append(snap)
        return snap


class GroundReceiver:
    def __init__(self, archive_dir: Path, host: str = "0.0.0.0", port: int = 5055,
                 printer: Callable[[str], None] = print) -> None:
        self.archive = Path(archive_dir)
        self.archive.mkdir(parents=True, exist_ok=True)
        self.host, self.port = host, port
        self.printer = printer
        self.lock = threading.RLock()
        self.sessions: dict[str, GroundSession] = {}
        self.order: list[str] = []  # session ids, newest last
        self.connected = False
        self.peer = ""
        self.last_rx = 0.0  # time.monotonic() of the last message
        self.bytes_rx = 0
        self.messages = 0
        self.duplicates = 0
        self._links_path = self.archive / "_links.json"
        try:
            self._links: dict[str, int] = json.loads(self._links_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._links = {}
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self.listeners: list[Callable[[str, dict[str, Any]], None]] = []

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows: SO_REUSEADDR would let a SECOND ground station bind the
            # same port silently and steal the link; exclusive fails loudly.
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(2)
        srv.settimeout(0.5)
        self.port = srv.getsockname()[1]  # port 0 = any free port (tests)
        self._server = srv
        t = threading.Thread(target=self._accept_loop, name="ground_accept", daemon=True)
        t.start()
        self._threads.append(t)
        self.printer(f"ground station listening on {self.host}:{self.port}, archive {self.archive}")

    def stop(self) -> None:
        with self.lock:  # no message is half-stored while we stop
            self._stop.set()
        for s in (self._conn, self._server):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        for t in self._threads:
            t.join(2.0)
        with self.lock:
            for s in self.sessions.values():
                s.close()
            self._save_links()

    def drop_link(self) -> None:
        """Cut the current connection (demo / test: a loss of signal)."""
        c = self._conn
        if c is not None:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    # --- network --------------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            old = self._conn
            if old is not None:  # a new connection replaces a stale one
                try:
                    old.close()
                except OSError:
                    pass
            t = threading.Thread(target=self._serve, args=(conn, addr), name="ground_link", daemon=True)
            t.start()
            self._threads.append(t)

    def _serve(self, conn: socket.socket, addr: Any) -> None:
        conn.settimeout(None)
        self._conn = conn
        link_id = ""
        try:
            header, _ = read_message(conn)
            if header.get("kind") != "link":
                return
            link_id = str(header.get("link_id"))
            with self.lock:
                last = self._links.get(link_id, 0)
                self.connected, self.peer = True, f"{addr[0]}:{addr[1]}"
            conn.sendall(encode({"kind": "resume", "last_msg_id": last}))
            self.printer(f"ground: link {link_id} from {addr[0]} (resuming after msg {last})")
            self._notify("link", {"connected": True, "peer": self.peer})
            # Reads block (a timeout mid-message would desync the stream);
            # acks go out from their own thread.
            done = threading.Event()
            threading.Thread(target=self._ack_loop, args=(conn, link_id, done),
                             name="ground_acks", daemon=True).start()
            try:
                while not self._stop.is_set():
                    header, payload = read_message(conn)
                    self._handle(link_id, header, payload)
            finally:
                done.set()
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            with self.lock:
                if self._conn is conn:
                    self._conn = None
                    self.connected = False
                self._save_links()
            try:
                conn.close()
            except OSError:
                pass
            self._notify("link", {"connected": False})

    def _ack_loop(self, conn: socket.socket, link_id: str, done: threading.Event) -> None:
        while not done.wait(ACK_EVERY_S):
            with self.lock:
                self._save_links()
                ack = self._links.get(link_id, 0)
            try:
                conn.sendall(encode({"kind": "ack", "last_msg_id": ack}))
            except OSError:
                return

    def _handle(self, link_id: str, header: dict[str, Any], payload: bytes) -> None:
        mid = int(header.get("msg_id", 0))
        kind = header.get("kind")
        size = len(payload) + len(json.dumps(header))
        with self.lock:
            self.last_rx = time.monotonic()
            self.bytes_rx += size
            self.messages += 1
            if mid <= self._links.get(link_id, 0):
                self.duplicates += 1
                return
            if self._stop.is_set():
                raise ConnectionError("ground stopping")  # not stored -> not acknowledged
            sid = str(header.get("session_id") or "unknown")
            sess = self._session(sid)
            sess.last_rx = time.time()
            if kind == "hello":
                sess.set_info(dict(header.get("info") or {}))
                sess.bytes["other"] += size
            elif kind == "steps":
                sess.set_steps(list(header.get("steps") or []))
                sess.bytes["other"] += size
            elif kind == "log":
                sess.add_line(str(header["line"]))
                sess.bytes["log"] += size
            elif kind == "snapshot":
                sess.add_snapshot(header, payload)
                sess.bytes["snapshot"] += size
            elif kind == "report":
                sess.report = payload.decode("utf-8", errors="replace")
                (sess.dir / "report.txt").write_text(sess.report, encoding="utf-8")
                sess.bytes["other"] += size
            # Only now is it stored: advance the resume point. If anything
            # above raised, the sender will resend this message.
            self._links[link_id] = mid
        self._notify(str(kind), {"session_id": sid, "msg_id": mid})

    def _session(self, sid: str) -> GroundSession:
        s = self.sessions.get(sid)
        if s is None:
            s = GroundSession(sid, self.archive)
            self.sessions[sid] = s
            self.order.append(sid)
        return s

    def _save_links(self) -> None:
        try:
            self._links_path.write_text(json.dumps(self._links), encoding="utf-8")
        except OSError:
            pass

    def _notify(self, kind: str, data: dict[str, Any]) -> None:
        for cb in list(self.listeners):
            try:
                cb(kind, data)
            except Exception:  # noqa: BLE001
                pass

    # --- views ------------------------------------------------------------

    def latest(self) -> GroundSession | None:
        with self.lock:
            return self.sessions[self.order[-1]] if self.order else None

    def signal_age_s(self) -> float | None:
        with self.lock:
            return None if not self.last_rx else time.monotonic() - self.last_rx


def ground_steps(sess: GroundSession) -> list[dict[str, Any]]:
    """The checklist as the ground sees it, from the step list sent at
    session start and the log lines received since -- same statuses as the
    co-pilot's own GUI (done / confirmed / missed / not_applicable / open /
    pending), plus which step is current."""
    done: dict[str, str] = {}
    missed: set[str] = set()
    suggested: list[str] = []
    for e in sess.events:
        et, sid = e.get("event_type"), e.get("step_id")
        if et == "step_complete" and sid:
            done[sid] = "confirmed" if e.get("status") == "operator_confirmed" else "done"
        elif et == "violation" and e.get("violation_type") == "skip" and sid:
            missed.add(sid)
        elif et == "next_step_suggested" and sid:
            suggested.append(sid)
    out = []
    for s in sess.steps:
        sid = s["id"]
        if s.get("status") == "not_applicable":
            status = "not_applicable"
        elif sid in done:
            status = done[sid]
        elif sid in missed:
            status = "missed"
        elif sid in suggested:
            status = "open"
        else:
            status = "pending"
        out.append({**s, "status": status})
    current = next((sid for sid in reversed(suggested)
                    if any(x["id"] == sid and x["status"] == "open" and not x.get("optional") for x in out)),
                   None)
    return [{**x, "is_current": x["id"] == current} for x in out]


def feed_record(rec: dict[str, Any]) -> dict[str, Any]:
    """A log record in the shape src/runtime/gui.event_line() formats."""
    return {"ts": rec.get("ts_monotonic") or 0.0, "type": rec.get("event_type"), "step": rec.get("step_id"),
            "code": rec.get("violation_type"), "severity": rec.get("severity"), "target": rec.get("target"),
            "message": rec.get("message"), "status": rec.get("status")}
