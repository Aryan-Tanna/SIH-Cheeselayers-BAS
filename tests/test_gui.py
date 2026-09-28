import pytest

from src.runtime.app import AppStatus
from src.runtime.gui import (
    BAD,
    CONFIRMED,
    OK,
    current_step_text,
    event_line,
    fit_size,
    step_lines,
)


def _snap(**kw):
    base = {
        "protocol_id": "p", "title": "T", "current_step": "b", "mode": "voice",
        "paused": False, "violations": 0,
        "steps": [
            {"id": "a", "prompt": "Unseal the module.", "status": "done", "object": "red module"},
            {"id": "b", "prompt": "Unseal the module.", "status": "open", "object": "yellow module"},
            {"id": "c", "prompt": "Seal it.", "status": "pending", "object": "payload container"},
        ],
    }
    base.update(kw)
    return base


# --- pure helpers ---------------------------------------------------------------

def test_fit_size_keeps_aspect_ratio():
    assert fit_size(848, 478, 1200, 1200) == (1200, 676)
    assert fit_size(640, 480, 320, 1000) == (320, 240)
    assert fit_size(0, 480, 100, 100) == (0, 0)


def test_step_lines_name_the_object_so_repeated_prompts_are_distinct():
    lines = step_lines(_snap())
    assert lines[0].text.startswith("red module:") and lines[1].text.startswith("yellow module:")
    assert lines[0].text != lines[1].text


def test_step_lines_mark_current_and_status():
    lines = step_lines(_snap())
    assert [ln.is_current for ln in lines] == [False, True, False]
    assert lines[0].colour == OK and lines[0].glyph == "✓" and "(done)" not in lines[0].text
    confirmed = step_lines(_snap(steps=[{"id": "a", "prompt": "x", "status": "confirmed"}]))[0]
    assert confirmed.colour == CONFIRMED and "operator" in confirmed.text
    missed = step_lines(_snap(steps=[{"id": "a", "prompt": "x", "status": "missed"}]))[0]
    assert missed.colour == BAD


def test_current_step_text():
    assert current_step_text(_snap()) == "NOW:  Unseal the module.   (yellow module)"
    assert "PAUSED" in current_step_text(_snap(paused=True))
    done = _snap(current_step=None, steps=[{"id": "a", "prompt": "x", "status": "done"}])
    assert current_step_text(done) == "Experiment complete."


def test_event_line_filters_internal_noise_and_colours_severity():
    assert event_line({"ts": 1.0, "type": "next_step_suggested"}, 0.0) is None
    assert event_line({"ts": 1.0, "type": "unmatched_action"}, 0.0) is None
    text, colour = event_line({"ts": 3.5, "type": "violation", "severity": "warning",
                               "code": "skip", "target": "module_b"}, 1.0)
    assert "2.5s" in text and "WARNING" in text and colour == BAD
    text, _ = event_line({"ts": 2.0, "type": "step_complete", "step": "s1",
                          "status": "operator_confirmed"}, 0.0)
    assert "confirmed by operator" in text


# --- window smoke test (needs a display) -------------------------------------------

class FakeApp:
    def __init__(self):
        self.commands = []
        self.reloads = 0
        self.snap = _snap()

    def status(self):
        return AppStatus(
            session_id="s1", protocol=self.snap, capture_fps=30.0, frame_size=(64, 48),
            recording=True, stream_url="udp://127.0.0.1:5000?pkt_size=1316",
            voice_control=True, listening_armed=False,
            recent_events=[{"ts": 0.0, "type": "session_start"},
                           {"ts": 1.0, "type": "violation", "severity": "caution",
                            "code": "out_of_order", "target": "module_a"}],
            recent_speech=[{"ts": 1.0, "kind": "alert", "severity": "caution",
                            "text": "That step is out of sequence."}],
            warnings=["TTS unavailable, falling back"],
        )

    def latest_frame(self):
        np = pytest.importorskip("numpy")
        from src.runtime.pipeline import Frame

        return Frame(seq=1, ts_monotonic=0.0, payload=np.zeros((48, 64, 3), dtype=np.uint8))

    def command(self, c):
        self.commands.append(c)

    def reload_protocol(self):
        self.reloads += 1
        return True


def test_window_builds_refreshes_and_buttons_map_to_commands():
    tk = pytest.importorskip("tkinter")
    pytest.importorskip("PIL.ImageTk")
    pytest.importorskip("cv2")
    from src.runtime.gui import CopilotGUI

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = FakeApp()
    gui = CopilotGUI(root, app)
    try:
        root.update()
        gui.refresh(app.status())
        gui._draw_frame()
        assert "yellow module" in gui.now_lbl.cget("text")
        assert "Unseal" in gui.steps_txt.get("1.0", "end")
        assert "Out of order" in gui.events_txt.get("1.0", "end")
        assert gui.badges["rec"].cget("text").startswith("● REC")
        gui._toggle_pause()
        gui._toggle_mode()
        gui.pause_btn.invoke()
        root.event_generate("<n>")
        root.update()
        assert app.commands[:2] == ["pause", "quiet"]
        app.snap = _snap(paused=True)
        gui.refresh(app.status())
        assert "Resume" in gui.pause_btn.cget("text")
        assert "PAUSED" in gui.now_lbl.cget("text")
    finally:
        gui.close()


def test_mic_badge_names_device_and_flags_silence():
    from src.runtime.gui import mic_badge

    def st(**kw):
        base = dict(voice_control=True, listening_armed=False,
                    mic_name="Microphone (DroidCam Audio)", mic_silent=False)
        base.update(kw)
        return type("S", (), base)()

    text, bg = mic_badge(st())
    assert "DroidCam Audio" in text and bg != BAD
    text, bg = mic_badge(st(mic_silent=True))
    assert text.startswith("MIC SILENT") and bg == BAD
    assert mic_badge(st(voice_control=False))[0] == "MIC off"


# --- rack setup ------------------------------------------------------------------

def test_rack_badge_states():
    from types import SimpleNamespace

    from src.runtime.gui import PANEL_2, WARN, rack_badge

    ok = rack_badge(SimpleNamespace(rack_status="ok", rack_markers_seen=(1, 3), rack_reproj_px=0.84))
    assert ok == ("RACK ok  [1,3]  0.8px  [K]", OK)
    assert rack_badge(SimpleNamespace(rack_status="held", rack_markers_seen=()))[1] == WARN
    assert rack_badge(SimpleNamespace(rack_status="none"))[1] == BAD
    assert rack_badge(SimpleNamespace(rack_status="uncalibrated"))[1] == WARN
    assert rack_badge(SimpleNamespace())[1] == PANEL_2  # older app without rack fields


def test_rack_form_parsing():
    from src.runtime.gui import parse_rack_form

    assert parse_rack_form("DICT_4X4_50", " 49 mm", "1,2, 3 4") == ("DICT_4X4_50", 49.0, (1, 2, 3, 4))
    for args in (("DICT_X", "49", "1"), ("DICT_4X4_50", "abc", "1"), ("DICT_4X4_50", "0", "1"),
                 ("DICT_4X4_50", "49", "")):
        with pytest.raises(ValueError):
            parse_rack_form(*args)


def test_attend_badge_timer():
    from src.runtime.gui import PANEL_2, WARN, attend_badge

    base = {"enabled": True, "open_modules": ["module_a"], "grace_s": 5.0, "alerted": False}
    assert attend_badge({"attendance": {**base, "open_modules": []}}) is None
    assert attend_badge({"attendance": {**base, "hands_in_view": True, "away_s": None}})[1] == PANEL_2
    assert attend_badge({"attendance": {**base, "hands_in_view": False, "away_s": 3.2}}) == (
        "OPEN module_a  hands away 3.2/5 s", WARN)
    assert attend_badge({"attendance": {**base, "hands_in_view": False, "away_s": 6.0, "alerted": True}})[1] == BAD
    assert attend_badge({}) is None


def test_session_screen_follows_a_restart_and_hands_back_on_end(tmp_path):
    tk = pytest.importorskip("tkinter")
    pytest.importorskip("PIL.ImageTk")
    from src.runtime.gui import CopilotGUI
    from tests.test_app import _headless

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    app = _headless(tmp_path, session_id="first")
    app.start()
    ended = []
    try:
        gui = CopilotGUI(root, app, on_end=lambda: ended.append(True))
        app.command("next")
        gui.refresh(app.status())
        assert "1 of 12" in gui.progress_lbl.cget("text")
        app.restart_session()
        gui.refresh(app.status())
        assert app.session_id in gui.title_lbl.cget("text")
        assert "0 of 12" in gui.progress_lbl.cget("text")
        gui.close()  # what End session does after its confirmation
        assert ended == [True] and not gui.frame.winfo_exists() and root.winfo_exists()
    finally:
        app.stop()
        root.destroy()


def test_hand_cue_line_names_objects_and_says_maybe_for_prediction():
    from src.runtime.gui import hand_cue_text, object_names

    snap = {"steps": [{"id": "r", "target": "module_a", "object": "red module", "prompt": "x", "status": "open"},
                      {"id": "l", "target": "module_a.lid", "object": "red module", "prompt": "y", "status": "pending"}]}
    names = object_names(snap)
    assert names == {"module_a": "red module", "module_a.lid": "red module cap"}
    text = hand_cue_text([{"obj": "module_a", "state": "holding", "eta_s": None},
                          {"obj": "module_a.lid", "state": "reaching", "eta_s": 0.62}], names, gloved=2)
    assert "Holding: red module" in text and "Maybe reaching for: red module cap (0.6 s)" in text
    assert "2 gloved hands (no skeleton)" in text
    assert hand_cue_text([], names) == ""
