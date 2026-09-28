"""Start screen: which experiments can start, props, camera field."""

import json
from pathlib import Path

import pytest

from src.protocol.editing import PLACEHOLDER_PROMPT
from src.runtime.dashboard import (
    EditorHost,
    experiment_info,
    list_experiments,
    list_profiles,
    parse_source,
    summary_text,
)
from src.runtime.gui import event_line, progress_text

REPO = Path(__file__).resolve().parent.parent
V1 = REPO / "configs" / "protocols" / "bas_specimen_v1.json"


def _copy(tmp_path, name, mutate=None):
    raw = json.loads(V1.read_text(encoding="utf-8"))
    raw["protocol_id"] = name
    if mutate:
        mutate(raw)
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(raw, indent=4), encoding="utf-8")
    return p


def test_reference_protocol_is_ready_and_marked_reference():
    info = experiment_info(V1)
    assert info.ready and info.reference
    assert len(info.steps) == 12 and info.steps[0] == "Open the payload container."


def test_placeholder_and_invalid_experiments_cannot_start(tmp_path):
    def placeholder(raw):
        raw["steps"][0]["prompt"] = PLACEHOLDER_PROMPT

    def dangling(raw):
        raw["steps"][0]["after"] = ["nope"]

    _copy(tmp_path, "good")
    _copy(tmp_path, "unfinished", placeholder)
    _copy(tmp_path, "broken", dangling)
    (tmp_path / "good.editing.json").write_text("{}", encoding="utf-8")  # editor scratch: hidden
    infos = {i.protocol_id: i for i in list_experiments(tmp_path)}
    assert set(infos) == {"good", "unfinished", "broken"}
    assert infos["good"].ready
    assert any("placeholder" in p for p in infos["unfinished"].problems)
    assert any("nope" in p for p in infos["broken"].problems)
    assert [i.protocol_id for i in list_experiments(tmp_path)][0] == "good"  # ready first


def test_profiles_hide_the_synthetic_one_and_start_with_the_protocol_default():
    profiles = list_profiles()
    assert profiles[0] == ("As the experiment specifies", None)
    paths = [p for _, p in profiles]
    assert "configs/objects/profile_jar.yaml" in paths
    assert not any("repeatable_test" in (p or "") for p in paths)


def test_camera_field_parsing():
    assert parse_source("") is None
    assert parse_source("0  (webcam)") == 0
    assert parse_source("1") == 1
    assert parse_source("http://192.168.1.5:4747/video") == "http://192.168.1.5:4747/video"
    assert parse_source(r"C:\clips\run 1.mp4") == r"C:\clips\run 1.mp4"


def test_editor_host_saves_only_valid_protocols(tmp_path):
    host = EditorHost(V1, None)
    assert host.resolved.parsed.protocol_id == "bas_specimen_v1"
    assert host.use_protocol(_copy(tmp_path, "mine")) and host.saved.name == "mine.json"
    bad = _copy(tmp_path, "bad", lambda raw: raw["steps"][0].update(after=["nope"]))
    assert not host.use_protocol(bad) and host.saved.name == "mine.json"


def test_progress_and_event_text_are_plain_words():
    snap = {"steps": [{"id": "a", "status": "done"}, {"id": "b", "status": "missed"},
                      {"id": "c", "status": "not_applicable"}, {"id": "d", "status": "open"}]}
    assert progress_text(snap) == "1 of 3 steps done,  1 missed"
    text, _ = event_line({"ts": 2.0, "type": "violation", "severity": "caution",
                          "code": "mutual_exclusion_breach", "step": "b", "target": "module_b"},
                         0.0, {"b": "yellow module: Remove the second module."})
    assert "Two modules out at once" in text and "yellow module" in text
    assert "3/12 steps" in summary_text({"session_id": "s", "steps_done": 3, "steps_total": 12,
                                         "violations": 0, "log_chain_ok": True, "log": "x"})


def test_dashboard_window_starts_only_a_ready_experiment():
    tk = pytest.importorskip("tkinter")
    from src.runtime.config import load_runtime_config
    from src.runtime.dashboard import Dashboard

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    started = []
    try:
        dash = Dashboard(root, load_runtime_config(), on_start=started.append)
        root.update()
        info = dash.selected()
        assert info is not None and info.path.name == "bas_specimen_v1.json"
        assert str(dash.start_btn.cget("state")) == "normal"
        assert "Copy &" in dash.edit_btn.cget("text")  # the reference is never edited in place
        dash.source_var.set("1")
        dash.start()
        assert started and started[0].protocol == info.path and started[0].source == 1
        dash.destroy()
    finally:
        root.destroy()
