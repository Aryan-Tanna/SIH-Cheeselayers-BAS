import threading

import pytest

np = pytest.importorskip("numpy")

from src.runtime.announcer import AudioRequest  # noqa: E402
from src.runtime.audio import AudioWorker  # noqa: E402
from src.runtime.audio_out import RecordingSink  # noqa: E402
from src.runtime.earcons import EarconSpec, render_earcon  # noqa: E402
from src.runtime.tts import CachedTTS, NullTTS  # noqa: E402

SR = 16000
EARCONS = {
    "advisory": EarconSpec((660.0,), 100, 0),
    "caution": EarconSpec((660.0, 880.0), 100, 40),
    "warning": EarconSpec((988.0, 988.0, 988.0), 90, 60),
}


class FakeTTS:
    name = "fake"
    sample_rate = SR

    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        return np.full(SR // 10, 0.1, dtype=np.float32)


def _worker(sink, tts=None, **kw):
    lines = []
    w = AudioWorker(CachedTTS(tts or FakeTTS()), sink, dict(EARCONS), printer=lines.append, **kw)
    return w, lines


def _caution(text="c"):
    return AudioRequest(kind="alert", segments=(text,), severity="caution", earcon="caution")


def _warning(text="w"):
    return AudioRequest(kind="alert", segments=(text,), severity="warning", earcon="warning",
                        interrupt=True)


def _prompt(text, step):
    return AudioRequest(kind="prompt", segments=(text,), step_id=step)


# --- earcons -----------------------------------------------------------------

def test_earcon_length_and_range():
    spec = EarconSpec((660.0, 880.0), 100, 40)
    s = render_earcon(spec, SR)
    assert len(s) == int(SR * 0.1) * 2 + int(SR * 0.04)
    assert s.dtype == np.float32
    assert np.max(np.abs(s)) <= 0.6 + 1e-6


def test_earcon_edges_are_faded_no_click():
    s = render_earcon(EarconSpec((880.0,), 100, 0), SR)
    assert abs(s[0]) < 1e-3 and abs(s[-1]) < 1e-3


def test_earcon_spec_rejects_empty_notes():
    with pytest.raises(ValueError):
        EarconSpec.from_config({"notes_hz": [], "note_ms": 100})


# --- rendering ---------------------------------------------------------------

def test_render_is_earcon_gap_then_speech_scaled_by_volume():
    w, _ = _worker(RecordingSink(), volume=0.5)
    clip = w.render(_caution("hello"))
    earcon = render_earcon(EARCONS["caution"], SR)
    speech_len = SR // 10
    assert len(clip) == len(earcon) + int(SR * 0.08) + speech_len
    assert np.allclose(clip[-speech_len:], 0.05)


def test_advisory_tone_only_has_no_speech():
    w, _ = _worker(RecordingSink())
    req = AudioRequest(kind="alert", severity="advisory", earcon="advisory")
    assert len(w.render(req)) == len(render_earcon(EARCONS["advisory"], SR))


def test_multiple_segments_rendered_with_phrase_gap():
    w, _ = _worker(RecordingSink(), volume=1.0)
    req = AudioRequest(kind="alert", segments=("a", "b"), severity="caution")
    speech_len = SR // 10
    assert len(w.render(req)) == 2 * speech_len + int(SR * 0.18)


def test_step_tick_earcon_only():
    w, _ = _worker(RecordingSink())
    w.earcons["step"] = EarconSpec((1320.0,), 55, 0)
    req = AudioRequest(kind="step", earcon="step")
    assert len(w.render(req)) == int(SR * 0.055)


def test_flush_all_drops_everything_including_warnings():
    w, _ = _worker(RecordingSink())
    w.submit([_warning("w1"), _caution("c1")])
    w.submit([AudioRequest(kind="system", segments=("Paused.",), flush_all=True)])
    assert [r.text for r in w.pending()] == ["Paused."]


def test_flush_all_cuts_a_playing_warning():
    sink = RecordingSink(block=True)
    w, _ = _worker(sink)
    w.start()
    w.submit([_warning("w1")])
    assert sink.playing.wait(2.0)
    w.submit([AudioRequest(kind="system", segments=("Paused.",), flush_all=True)])
    while len(sink.played) < 2:
        threading.Event().wait(0.01)
    sink.release()
    assert w.drain(2.0)
    w.stop()
    assert sink.completed == [False, True]


def test_no_tts_prints_text_and_still_plays_earcon():
    sink = RecordingSink()
    w, lines = _worker(sink, tts=NullTTS())
    w.start()
    w.submit([_caution("Wrong object for this step.")])
    assert w.drain(2.0)
    w.stop()
    assert lines == ["[CAUTION] Wrong object for this step."]
    assert len(sink.played) == 1  # the earcon
    assert w.stats.text_only == 1


def test_no_tts_prompt_is_printed_not_played():
    sink = RecordingSink()
    w, lines = _worker(sink, tts=NullTTS())
    w.start()
    w.submit([_prompt("Open the payload container.", "open_container")])
    assert w.drain(2.0)
    w.stop()
    assert lines == ["[PROMPT] Open the payload container."]
    assert sink.played == []


def test_echo_text_prints_everything():
    w, lines = _worker(RecordingSink(), echo_text=True)
    w.start()
    w.submit([_prompt("Open the payload container.", "s1")])
    assert w.drain(2.0)
    w.stop()
    assert lines == ["[PROMPT] Open the payload container."]


def test_non_ascii_protocol_text_is_printed_as_ascii():
    w, lines = _worker(RecordingSink(), tts=NullTTS())
    w.start()
    w.submit([_prompt("Seal the container — now.", "s1")])
    assert w.drain(2.0)
    w.stop()
    assert lines[0].isascii()


# --- queue policy (no thread started: inspect pending directly) --------------

def test_newer_prompt_supersedes_pending_prompt():
    w, _ = _worker(RecordingSink())
    w.submit([_prompt("one", "a"), _caution(), _prompt("two", "b")])
    assert [r.text for r in w.pending()] == ["c", "two"]
    assert w.stats.superseded_prompts == 1


def test_warning_flushes_pending_non_warnings_but_keeps_warnings():
    w, _ = _worker(RecordingSink())
    w.submit([_caution("c1"), _warning("w1"), _prompt("p", "a")])
    w.submit([_warning("w2")])
    assert [r.text for r in w.pending()] == ["w1", "w2"]
    assert w.stats.flushed_by_warning == 2


def test_overflow_drops_oldest():
    w, _ = _worker(RecordingSink(), queue_maxsize=2)
    w.submit([_caution("1"), _caution("2"), _caution("3")])
    assert [r.text for r in w.pending()] == ["2", "3"]
    assert w.stats.dropped_overflow == 1


# --- threading: interruption --------------------------------------------------

def test_warning_cuts_off_playing_caution():
    sink = RecordingSink(block=True)
    w, _ = _worker(sink)
    w.start()
    w.submit([_caution("long caution")])
    assert sink.playing.wait(2.0)
    w.submit([_warning("warn")])
    # the warning's own clip then blocks; let it finish
    deadline = threading.Event()
    while len(sink.played) < 2 and not deadline.wait(0.01):
        pass
    sink.release()
    assert w.drain(2.0)
    w.stop()
    assert sink.completed == [False, True]
    assert w.stats.interrupted == 1 and w.stats.played == 1


def test_warning_does_not_cut_off_playing_warning():
    sink = RecordingSink(block=True)
    w, _ = _worker(sink)
    w.start()
    w.submit([_warning("w1")])
    assert sink.playing.wait(2.0)
    w.submit([_warning("w2")])
    sink.release()
    while len(sink.played) < 2:
        threading.Event().wait(0.01)
    sink.release()
    assert w.drain(2.0)
    w.stop()
    assert sink.completed == [True, True]


def test_cancel_before_playback_starts_is_not_lost():
    # A warning that lands while the current clip is still being rendered
    # (sink.play not yet entered) must still cancel it.
    gate = threading.Event()
    entered = threading.Event()

    class SlowTTS(FakeTTS):
        def synthesize(self, text):
            if text == "slow":
                entered.set()
                gate.wait(2.0)
            return super().synthesize(text)

    sink = RecordingSink()
    w, _ = _worker(sink, tts=SlowTTS())
    w.start()
    w.submit([_caution("slow")])
    assert entered.wait(2.0)
    w.submit([_warning("warn")])
    gate.set()
    assert w.drain(2.0)
    w.stop()
    assert sink.completed == [False, True]


def test_playback_exception_does_not_kill_worker():
    class BrokenSink(RecordingSink):
        def play(self, samples, sample_rate, cancel):
            if not self.played:
                self.played.append(None)
                raise RuntimeError("device vanished")
            return super().play(samples, sample_rate, cancel)

    sink = BrokenSink()
    w, lines = _worker(sink)
    w.start()
    w.submit([_caution("a")])
    assert w.drain(2.0)
    w.submit([_caution("b")])
    assert w.drain(2.0)
    w.stop()
    assert any("playback failed" in ln for ln in lines)
    assert sink.completed == [True]


def test_resample_linear_preserves_duration_and_tone():
    from src.runtime.audio_out import resample_linear

    src = np.sin(2 * np.pi * 440 * np.arange(22050) / 22050).astype(np.float32)
    out = resample_linear(src, 22050, 48000)
    assert len(out) == 48000 and out.dtype == np.float32
    # dominant frequency survives the rate change
    spectrum = np.abs(np.fft.rfft(out))
    assert abs(np.argmax(spectrum) * 48000 / len(out) - 440) < 2
    assert resample_linear(src, 22050, 22050) is src


def test_cached_tts_synthesizes_each_phrase_once():
    tts = FakeTTS()
    cache = CachedTTS(tts)
    assert cache.prewarm(["a", "b", "a"]) == 2
    cache.get("a")
    assert tts.calls == ["a", "b"]


def test_constructor_validation():
    with pytest.raises(ValueError):
        _worker(RecordingSink(), queue_maxsize=0)
    with pytest.raises(ValueError):
        _worker(RecordingSink(), volume=1.5)
