import copy
import json
import time
from pathlib import Path

import pytest

from src.logging.session_log import load_events
from src.protocol.loader import REPO_ROOT
from src.runtime.app import AppOptions, CopilotApp, ProtocolInvalid
from src.runtime.config import load_runtime_config

PROTOCOL = REPO_ROOT / "configs" / "protocols" / "bas_specimen_v1.json"

CLEAN = [
    ("open", "container", {}),
    ("remove_from", "module_a", {"source": "container"}),
    ("open", "module_a", {}),
    ("move_to_zone", "module_a.lid", {"zone": "stow_zone"}),
    ("close", "module_a", {}),
    ("place_into", "module_a", {"dest": "container"}),
    ("remove_from", "module_b", {"source": "container"}),
    ("open", "module_b", {}),
    ("move_to_zone", "module_b.lid", {"zone": "stow_zone"}),
    ("close", "module_b", {}),
    ("place_into", "module_b", {"dest": "container"}),
    ("close", "container", {}),
]


def _cfg(tmp_path):
    cfg = copy.deepcopy(load_runtime_config())
    cfg["session"]["log_dir"] = str(tmp_path / "logs")
    cfg["recording"]["out_dir"] = str(tmp_path / "rec")
    cfg["stream"]["enabled"] = False
    return cfg


def _events_file(tmp_path, steps, dt=0.03):
    ev = [{"t": 0.05 + i * dt, "action": a, "target": t, **kw} for i, (a, t, kw) in enumerate(steps)]
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"protocol_id": "bas_specimen_v1", "events": ev}), encoding="utf-8")
    return p


def _headless(tmp_path, **kw):
    opts = dict(capture=False, record=False, audio=False, voice_control=False)
    opts.update(kw)
    return CopilotApp(_cfg(tmp_path), AppOptions(**opts), printer=lambda _: None)


def test_scripted_clean_run_completes_and_log_verifies(tmp_path):
    app = _headless(tmp_path, events=_events_file(tmp_path, CLEAN))
    app.start()
    assert app.events_done.wait(10.0)
    summary = app.stop()
    assert summary["steps_done"] == summary["steps_total"] == 12
    assert summary["violations"] == 0 and summary["log_chain_ok"]
    types = [e["event_type"] for e in load_events(summary["log"])]
    assert types[0] == "session_start" and types.count("step_complete") == 12


def test_status_snapshot_for_gui(tmp_path):
    app = _headless(tmp_path)
    app.start()
    st = app.status()
    app.stop()
    assert st.protocol["protocol_id"] == "bas_specimen_v1"
    assert st.protocol["current_step"] == "open_container"
    assert {s["status"] for s in st.protocol["steps"]} == {"open", "pending"}
    assert st.recent_events and st.recent_events[0]["type"] == "session_start"


def test_gui_command_path_marks_step(tmp_path):
    app = _headless(tmp_path)
    app.start()
    app.command("next")
    snap = app.status().protocol
    app.stop()
    assert snap["steps"][0]["status"] == "confirmed"


def test_hot_reload_valid_edit_is_applied(tmp_path):
    proto = tmp_path / "p.json"
    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    proto.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    app = _headless(tmp_path, protocol=proto)
    app.start()
    raw["steps"][0]["prompt"] = "Open the payload container now."
    proto.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    assert app.reload_protocol()
    snap = app.status().protocol
    app.stop()
    assert snap["steps"][0]["prompt"] == "Open the payload container now."


def test_hot_reload_invalid_edit_is_rejected_and_old_protocol_kept(tmp_path):
    proto = tmp_path / "p.json"
    proto.write_text(PROTOCOL.read_text(encoding="utf-8"), encoding="utf-8")
    lines = []
    app = CopilotApp(_cfg(tmp_path), AppOptions(protocol=proto, capture=False, record=False,
                                                audio=False, voice_control=False),
                     printer=lines.append)
    app.start()
    proto.write_text('{"protocol_id": "broken", ', encoding="utf-8")
    assert not app.reload_protocol()
    snap = app.status().protocol
    app.stop()
    assert snap["protocol_id"] == "bas_specimen_v1"
    assert any("REJECTED" in ln for ln in lines)


def test_file_watcher_picks_up_an_edit(tmp_path):
    proto = tmp_path / "p.json"
    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    proto.write_text(json.dumps(raw), encoding="utf-8")
    app = _headless(tmp_path, protocol=proto)
    app.start()
    time.sleep(0.2)
    raw["steps"][0]["prompt"] = "Edited while running."
    proto.write_text(json.dumps(raw), encoding="utf-8")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if app.status().protocol["steps"][0]["prompt"] == "Edited while running.":
            break
        time.sleep(0.1)
    snap = app.status().protocol
    app.stop()
    assert snap["steps"][0]["prompt"] == "Edited while running."


def test_invalid_protocol_at_startup_fails_loudly(tmp_path):
    bad = REPO_ROOT / "tests" / "fixtures" / "malformed" / "cyclic_after.json"
    with pytest.raises(ProtocolInvalid):
        _headless(tmp_path, protocol=bad)


def test_video_file_source_records_with_real_ffmpeg(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from src.runtime.recorder import find_ffmpeg

    if find_ffmpeg("auto") is None:
        pytest.skip("no ffmpeg")
    clip = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (160, 120))
    if not w.isOpened():
        pytest.skip("no MJPG writer")
    rng = np.random.default_rng(0)
    for _ in range(30):
        w.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    w.release()
    app = _headless(tmp_path, capture=True, record=True, source=str(clip))
    app.start()
    time.sleep(2.0)  # 1 s clip at real-time pace
    summary = app.stop()
    assert summary["frames_captured"] == 30
    assert summary["video_frames"] >= 14 and summary["recording_error"] is None
    assert list(Path(summary["recording_dir"]).glob("seg_*.ts"))
