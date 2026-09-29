"""Fully offline mode: a session with NO link keeps its log, event images
and report on board; "Send to Earth" later delivers them, verified, and a
second send transfers nothing new."""

import json
import threading
import time

import numpy as np

from src.link.receiver import GroundReceiver
from src.link.sender import Downlink, DownlinkConfig
from src.link.upload import sent_info, upload_session
from src.logging.session_log import SessionLogger
from src.protocol.events import EngineEvent


def _offline_session(logs, sid="session_off"):
    lock = threading.Lock()
    holder = {}

    def attest(s, ts, extra):
        with lock:
            holder["lg"].log_event(EngineEvent(ts_monotonic=ts, event_type="snapshot", message="image", extra=extra))

    link = Downlink(DownlinkConfig(), attest=attest, printer=lambda _m: None, send=False, save_root=logs)
    lg = SessionLogger(logs / f"{sid}.jsonl", sid, on_line=link.on_log_line)
    holder["lg"] = lg
    link.begin_session(sid, {"protocol_id": "bas_specimen_v1", "title": "Dual specimen module inspection"})
    link.send_steps(sid, [{"id": "s0", "prompt": "Open.", "status": "open"},
                          {"id": "s1", "prompt": "Close.", "status": "pending"}])
    link.start()
    with lock:
        lg.log_event(EngineEvent(ts_monotonic=0.0, event_type="session_start", message="session start: bas_specimen_v1"))
    for i in range(2):
        img = np.random.default_rng(i).integers(0, 255, (240, 320, 3), dtype=np.uint8)
        link.offer_frame(1.0 + i, img)
        with lock:
            lg.log_event(EngineEvent(ts_monotonic=1.0 + i, event_type="step_complete", step_id=f"s{i}"))
    link.stop()
    lg.close()
    (logs / f"{sid}.report.txt").write_text("REPORT", encoding="utf-8")
    return logs / f"{sid}.jsonl", link


def test_offline_session_keeps_everything_on_board_and_sends_nothing(tmp_path):
    log, link = _offline_session(tmp_path)
    d = tmp_path / "session_off"
    assert sorted(p.stem.split("_", 1)[1] for p in (d / "snapshots").glob("*.jpg")) == ["s0", "s1"]
    assert json.loads((d / "info.json").read_text())["title"] == "Dual specimen module inspection"
    assert (d / "steps.json").is_file()
    assert link.status()["bytes_sent"] == 0 and link.status()["sending"] is False
    kinds = [json.loads(ln)["event_type"] for ln in log.read_text().splitlines()]
    assert kinds.count("snapshot") == 2  # images attested in the chain even offline


def test_send_later_delivers_verified_and_resend_adds_nothing(tmp_path):
    log, _ = _offline_session(tmp_path / "logs")
    g = GroundReceiver(tmp_path / "ground", host="127.0.0.1", port=0, printer=lambda _m: None)
    g.start()
    res = upload_session(log, "127.0.0.1", g.port, timeout_s=20)
    assert res["ok"] and res["images"] == 2 and res["report"]
    sess = g.sessions["session_off"]
    end = time.monotonic() + 5
    while sess.report is None and time.monotonic() < end:
        time.sleep(0.05)
    assert (sess.dir / "session.jsonl").read_text(encoding="utf-8") == log.read_text(encoding="utf-8")
    assert sess.chain_ok and sess.report == "REPORT"
    assert len(sess.snapshots) == 2 and all(s["intact"] and s["attested"] for s in sess.snapshots)
    assert sess.info["sent_later"] is True and [s["id"] for s in sess.steps] == ["s0", "s1"]
    assert sent_info(log)["target"] == f"127.0.0.1:{g.port}"
    before = g.messages
    again = upload_session(log, "127.0.0.1", g.port, timeout_s=20)
    assert again["ok"] and again["bytes_sent"] == 0 and g.messages == before  # nothing re-sent
    assert len(sess.events) == len(log.read_text().splitlines())
    g.stop()


def test_send_later_with_no_ground_fails_cleanly_and_marks_nothing(tmp_path):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    log, _ = _offline_session(tmp_path)
    res = upload_session(log, "127.0.0.1", port, timeout_s=2)
    assert res["ok"] is False and res["error"]
    assert sent_info(log) is None
