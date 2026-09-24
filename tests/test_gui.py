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
    assert lines[0].colour == OK and "(done)" in lines[0].text
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
    assert "(operator)" in text


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
        assert "out_of_order" in gui.events_txt.get("1.0", "end")
        assert gui.badges["rec"].cget("text").startswith("● REC")
        gui._toggle_pause()
        gui._toggle_mode()
        gui.pause_btn.invoke()
        root.event_generate("<n>")
        root.update()
        assert app.commands[:2] == ["pause", "quiet"]
        app.snap = _snap(paused=True)
        gui.refresh(app.status())
        assert gui.pause_btn.cget("text").startswith("Resume")
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
