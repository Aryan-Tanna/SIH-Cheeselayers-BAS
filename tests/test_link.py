"""Space-to-ground downlink over real loopback TCP: delivery, byte-identical
archive, image attestation, loss of signal + resend, ground restart,
tamper detection, simulated light-time."""

import json
import threading
import time

import numpy as np
import pytest

from src.link.receiver import GroundReceiver, GroundSession
from src.link.sender import Downlink, DownlinkConfig
from src.logging.session_log import SessionLogger, verify_chain
from src.protocol.events import EngineEvent


def _wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Onboard:
    """A session log wired to a downlink the way the app wires it."""

    def __init__(self, tmp_path, port, sid="session_test", **cfg):
        self.lock = threading.Lock()
        self.cfg = DownlinkConfig(enabled=True, host="127.0.0.1", port=port, reconnect_s=0.2, **cfg)
        self.link = Downlink(self.cfg, attest=self._attest, printer=lambda _m: None)
        self.log_path = tmp_path / f"{sid}.jsonl"
        self.sid = sid
        self.logger = SessionLogger(self.log_path, sid, on_line=self.link.on_log_line)
        self.link.begin_session(sid, {"protocol_id": "bas_specimen_v1", "title": "test"})
        self.link.start()

    def _attest(self, sid, ts, extra):
        with self.lock:
            self.logger.log_event(EngineEvent(ts_monotonic=ts, event_type="snapshot",
                                              message=f"image for seq {extra['for_seq']}", extra=extra))

    def log(self, ts, event_type, **kw):
        with self.lock:
            return self.logger.log_event(EngineEvent(ts_monotonic=ts, event_type=event_type, **kw))

    def frame(self, ts):
        img = np.random.default_rng(int(ts * 10)).integers(0, 255, (480, 640, 3), dtype=np.uint8)
        self.link.offer_frame(ts, img)

    def close(self):
        self.link.stop()
        self.logger.close()


def _ground(tmp_path, port=0):
    g = GroundReceiver(tmp_path / "ground", host="127.0.0.1", port=port, printer=lambda _m: None)
    g.start()
    return g


def _run_steps(ob, t0, n):
    for i in range(n):
        t = t0 + i
        ob.frame(t)
        ob.log(t, "step_complete", step_id=f"s{i}", status="complete", confidence=0.9)


def test_log_and_images_arrive_verified_and_byte_identical(tmp_path):
    g = _ground(tmp_path)
    ob = Onboard(tmp_path, g.port)
    ob.log(0.0, "session_start", message="session start")
    _run_steps(ob, 1.0, 3)
    ob.frame(5.0)
    ob.log(5.0, "violation", violation_type="skip", target="module_a", severity="warning")
    ob.link.send_report(ob.sid, "REPORT TEXT")
    ob.close()
    sess = g.sessions[ob.sid]
    assert _wait(lambda: sess.report == "REPORT TEXT")
    local = ob.log_path.read_text(encoding="utf-8")
    assert (sess.dir / "session.jsonl").read_text(encoding="utf-8") == local
    assert verify_chain(ob.log_path).ok and sess.chain_ok
    assert len(sess.snapshots) == 4  # 3 steps + 1 violation
    assert all(s["intact"] and s["attested"] for s in sess.snapshots)
    assert all((sess.dir / "snapshots").glob("*.jpg"))
    st = ob.link.status()
    assert st["snapshots"] == 4 and st["bytes_sent"] == st["log_bytes"] + st["snapshot_bytes"] + ob.link.stats.other_bytes
    g.stop()


def test_loss_of_signal_resends_nothing_lost_nothing_duplicated(tmp_path):
    g = _ground(tmp_path)
    ob = Onboard(tmp_path, g.port)
    ob.log(0.0, "session_start")
    _run_steps(ob, 1.0, 3)
    assert _wait(lambda: len(g.sessions.get(ob.sid, GroundSession("x", tmp_path / "x")).events) >= 4)
    g.drop_link()  # loss of signal
    _run_steps(ob, 10.0, 3)  # the crew keeps working
    assert _wait(lambda: ob.link.status()["connects"] >= 2)
    ob.close()
    sess = g.sessions[ob.sid]
    assert _wait(lambda: len(sess.events) == len(ob.log_path.read_text().splitlines()))
    assert (sess.dir / "session.jsonl").read_text(encoding="utf-8") == ob.log_path.read_text(encoding="utf-8")
    assert sess.chain_ok
    g.stop()


def test_ground_down_at_start_then_everything_arrives(tmp_path):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ob = Onboard(tmp_path, port)
    ob.log(0.0, "session_start")
    _run_steps(ob, 1.0, 2)
    time.sleep(0.5)
    assert ob.link.status()["connected"] is False
    g = _ground(tmp_path, port=port)  # ground comes up later
    ob.close()
    sess = g.sessions[ob.sid]
    assert _wait(lambda: len(sess.events) == len(ob.log_path.read_text().splitlines()))
    assert sess.chain_ok
    g.stop()


def test_ground_restart_resumes_the_same_archive(tmp_path):
    g = _ground(tmp_path)
    port = g.port
    ob = Onboard(tmp_path, port)
    ob.log(0.0, "session_start")
    _run_steps(ob, 1.0, 2)
    assert _wait(lambda: ob.sid in g.sessions and len(g.sessions[ob.sid].events) >= 3)
    time.sleep(0.7)  # let an ack land
    g.stop()
    _run_steps(ob, 5.0, 2)
    g2 = _ground(tmp_path, port=port)
    ob.close()
    sess = g2.sessions[ob.sid]
    assert _wait(lambda: len(sess.events) == len(ob.log_path.read_text().splitlines()))
    assert (sess.dir / "session.jsonl").read_text(encoding="utf-8") == ob.log_path.read_text(encoding="utf-8")
    assert sess.chain_ok
    g2.stop()


def test_an_altered_line_is_flagged_at_the_ground(tmp_path):
    log = tmp_path / "s.jsonl"
    with SessionLogger(log, "s") as lg:
        for i in range(3):
            lg.log_event(EngineEvent(ts_monotonic=float(i), event_type="step_complete", step_id=f"s{i}"))
    lines = log.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["step_id"] = "forged"
    lines[1] = json.dumps(rec, sort_keys=True)
    sess = GroundSession("s", tmp_path / "ground")
    for line in lines:
        sess.add_line(line)
    assert not sess.chain_ok and "seq=1" in sess.chain_error
    sess.close()


def test_an_unattested_or_corrupted_image_is_not_verified(tmp_path):
    sess = GroundSession("s", tmp_path / "ground")
    snap = sess.add_snapshot({"label": "x", "for_seq": 3, "sha256": "0" * 64}, b"\xff\xd8not-the-image")
    assert snap["intact"] is False and snap["attested"] is False
    sess.close()


def test_simulated_light_time_holds_messages_back(tmp_path):
    g = _ground(tmp_path)
    ob = Onboard(tmp_path, g.port, simulate_delay_s=1.0)
    ob.log(0.0, "session_start")
    time.sleep(0.5)
    assert ob.sid not in g.sessions or not g.sessions[ob.sid].events
    assert _wait(lambda: ob.sid in g.sessions and g.sessions[ob.sid].events, timeout=5.0)
    ob.close()
    g.stop()


@pytest.mark.parametrize("target,host,port", [("10.0.0.5:6000", "10.0.0.5", 6000), ("10.0.0.5", "10.0.0.5", 5055)])
def test_target_parsing(target, host, port):
    c = DownlinkConfig().with_target(target)
    assert c.enabled and c.host == host and c.port == port
