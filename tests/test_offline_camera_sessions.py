"""Offline guard, network-camera setup, past-session lists, and the start
screen's SPACE / EARTH role switch."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.logging.session_log import SessionLogger
from src.protocol.events import EngineEvent
from src.runtime.camera_setup import build_camera_url, check_local, probe_source
from src.runtime.offline import is_local_ip
from src.runtime.sessions import list_ground_sessions, list_local_sessions

REPO = Path(__file__).resolve().parent.parent

GUARD_PROBE = r"""
import json, socket, sys
sys.path.insert(0, sys.argv[1])
from src.runtime.offline import install_offline_guard, blocked_attempts
install_offline_guard({"203.0.113.7"}, printer=None)
out = {}
def attempt(name, fn):
    try:
        fn(); out[name] = "ok"
    except PermissionError:
        out[name] = "blocked"
    except OSError as e:
        out[name] = "network-error"
attempt("internet_ip", lambda: socket.create_connection(("8.8.8.8", 53), timeout=1))
attempt("dns_name", lambda: socket.getaddrinfo("example.com", 80))
attempt("loopback", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1))
attempt("lan", lambda: socket.create_connection(("192.168.255.254", 9), timeout=0.3))
attempt("earth_ip_allowed", lambda: socket.create_connection(("203.0.113.7", 9), timeout=0.3))
out["blocked"] = len(blocked_attempts())
print(json.dumps(out))
"""


def test_offline_guard_blocks_the_internet_but_not_the_local_network_or_earth():
    r = subprocess.run([sys.executable, "-c", GUARD_PROBE, str(REPO)], capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["internet_ip"] == "blocked" and out["dns_name"] == "blocked"
    assert out["loopback"] != "blocked" and out["lan"] != "blocked"
    assert out["earth_ip_allowed"] != "blocked"  # the one configured link
    assert out["blocked"] == 2


@pytest.mark.parametrize("ip,local", [("127.0.0.1", True), ("192.168.1.23", True), ("10.0.0.5", True),
                                      ("172.20.1.1", True), ("169.254.3.3", True), ("8.8.8.8", False),
                                      ("phone.local", False)])
def test_is_local_ip(ip, local):
    assert is_local_ip(ip) is local


def test_camera_url_presets_and_local_check():
    assert build_camera_url("DroidCam (phone app)", "192.168.1.23") == "http://192.168.1.23:4747/video"
    assert build_camera_url("IP Webcam (Android app)", "10.0.0.9", "8081") == "http://10.0.0.9:8081/video"
    assert build_camera_url("RTSP camera", "192.168.0.50", None, "live") == "rtsp://192.168.0.50:554/live"
    with pytest.raises(ValueError):
        build_camera_url("DroidCam (phone app)", "")
    assert check_local("http://192.168.1.23:4747/video") is None
    assert "internet address" in check_local("http://8.8.8.8:4747/video")
    assert "not the name" in check_local("http://myphone.lan:4747/video")


def test_probe_reports_an_unreachable_camera_quickly():
    res = probe_source("http://127.0.0.1:9/video", timeout_s=2.0)
    assert res.ok is False and res.message


def test_probe_opens_a_video_file(tmp_path):
    import cv2
    import numpy as np

    path = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for _ in range(5):
        w.write(np.zeros((48, 64, 3), np.uint8))
    w.release()
    res = probe_source(str(path))
    assert res.ok and "64x48" in res.message


def test_app_refuses_an_internet_camera(tmp_path):
    from tests.test_app import _headless

    with pytest.raises(ValueError, match="refused"):
        _headless(tmp_path, capture=True, source="http://8.8.8.8:4747/video")


def _log(path: Path, sid: str, n_steps: int) -> None:
    with SessionLogger(path, sid) as lg:
        lg.log_event(EngineEvent(ts_monotonic=0.0, event_type="session_start", message="session start: bas_specimen_v1"))
        for i in range(n_steps):
            lg.log_event(EngineEvent(ts_monotonic=1.0 + i, event_type="step_complete", step_id=f"s{i}"))
        lg.log_event(EngineEvent(ts_monotonic=9.0, event_type="violation", violation_type="skip"))


def test_local_sessions_are_read_from_the_logs_and_reverified(tmp_path):
    _log(tmp_path / "session_a.jsonl", "session_a", 3)
    _log(tmp_path / "session_b.jsonl", "session_b", 5)
    (tmp_path / "session_b.report.txt").write_text("R", encoding="utf-8")
    rows = {r["session_id"]: r for r in list_local_sessions(tmp_path)}
    assert rows["session_b"]["steps_done"] == 5 and rows["session_b"]["violations"] == 1
    assert rows["session_b"]["chain_ok"] and rows["session_b"]["report"].endswith("session_b.report.txt")
    assert rows["session_a"]["report"] is None and rows["session_a"]["experiment"] == "bas_specimen_v1"
    lines = (tmp_path / "session_a.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["step_id"] = "forged"
    lines[1] = json.dumps(rec, sort_keys=True)
    (tmp_path / "session_a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = {r["session_id"]: r for r in list_local_sessions(tmp_path)}
    assert rows["session_a"]["chain_ok"] is False


def test_ground_sessions_show_title_and_images(tmp_path):
    d = tmp_path / "session_x"
    (d / "snapshots").mkdir(parents=True)
    _log(d / "session.jsonl", "session_x", 2)
    (d / "info.json").write_text(json.dumps({"title": "Dual specimen module inspection"}), encoding="utf-8")
    (d / "snapshots" / "00001_open_container.jpg").write_bytes(b"x")
    rows = list_ground_sessions(tmp_path)
    assert rows[0]["experiment"] == "Dual specimen module inspection" and rows[0]["images"] == 1


# --- start screen role switch (needs a display) --------------------------------

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def test_role_switch_and_start_receiving(root):
    from src.runtime.config import load_runtime_config
    from src.runtime.dashboard import Dashboard

    got = []
    d = Dashboard(root, load_runtime_config(), on_start=lambda c: None, role="earth", on_receive=got.append)
    assert d.earth_view.winfo_manager() and not d.space_view.winfo_manager()
    assert ":5055" in d.ip_lbl.cget("text")
    d.port_var.set("6001")
    d._start_receiving()
    assert got == [6001]
    d.set_role("space")
    assert d.space_view.winfo_manager() and not d.earth_view.winfo_manager()
    d.source_var.set("http://8.8.8.8:4747/video")
    d.start()
    assert "refused" in d.msg.cget("text")
    d.destroy()
