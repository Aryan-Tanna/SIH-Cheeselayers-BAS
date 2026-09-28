import json
from pathlib import Path

import pytest

from src.runtime.config import load_runtime_config
from src.runtime.voice_control import WAKE, WakeCommandParser

REPO = Path(__file__).resolve().parent.parent
COMMANDS = {
    "pause": ["pause"],
    "resume": ["resume", "continue"],
    "quiet": ["quiet mode", "quiet"],
    "voice": ["voice mode", "voice prompts"],
    "repeat": ["repeat", "next step"],
}


def _parser(window=5.0):
    return WakeCommandParser("hey bass", COMMANDS, window)


def _cmd(parsed):
    return None if parsed is None else parsed.command


def test_wake_and_command_in_one_utterance():
    p = _parser()
    assert _cmd(p.feed("hey bass pause", 0.0)) == "pause"
    assert _cmd(p.feed("Hey bass, quiet mode.", 1.0)) == "quiet"


def test_wake_then_command_within_window():
    p = _parser(window=5.0)
    assert _cmd(p.feed("hey bass", 0.0)) == WAKE
    assert p.armed
    assert _cmd(p.feed("resume", 3.0)) == "resume"
    assert not p.armed


def test_command_after_window_is_ignored():
    p = _parser(window=5.0)
    p.feed("hey bass", 0.0)
    assert p.feed("pause", 6.0) is None


def test_bare_command_without_wake_is_ignored():
    assert _parser().feed("pause", 0.0) is None


def test_speech_without_wake_phrase_is_ignored():
    p = _parser()
    for text in ["pause [unk]", "[unk]", "hey [unk]", "bass [unk]", "", "[unk] hey [unk]",
                 "pause", "quiet mode", "hey pause", "bass pause"]:
        assert p.feed(text, 0.0) is None, text


def test_wake_phrase_with_unintelligible_command_arms_the_window():
    p = _parser()
    assert _cmd(p.feed("hey bass [unk]", 0.0)) == WAKE
    assert _cmd(p.feed("quiet mode", 2.0)) == "quiet"


# Utterances exactly as Vosk finalised them in a live-mic session
# (2026-09-24). The first strict whole-utterance rule accepted 4 of 12
# that contained the wake phrase; these must keep working.
@pytest.mark.parametrize("heard,expected", [
    ("hey bass pause", "pause"),
    ("[unk] hey bass pause", "pause"),
    ("[unk] hey hey bass resume", "resume"),
    ("hey bass resume hey resume", "resume"),
    ("hey bass [unk]", WAKE),
    ("[unk] hey bass bass", WAKE),
    ("hey bass step [unk]", WAKE),
    ("[unk] [unk] [unk]", None),
    ("[unk] hey [unk]", None),
    # round 2, after the relaxed rule
    ("hey bass quiet mode", "quiet"),
    ("hey bass resume resume [unk]", "resume"),
    ("[unk] [unk] hey bass", WAKE),
    ("bass [unk] hey bass", WAKE),
    ("hey [unk]", None),
])
def test_live_session_utterances(heard, expected):
    assert _cmd(_parser().feed(heard, 0.0)) == expected


@pytest.mark.parametrize("wake_heard,command_heard,expected", [
    # live round 2: wake, chime, then the command alone 1.7-3 s later
    ("hey bass", "voice mode", "voice"),
    ("[unk] hey bass", "repeat", "repeat"),
    ("[unk] [unk] hey bass", "pause", "pause"),
    ("bass [unk] hey bass", "repeat [unk]", "repeat"),
])
def test_live_two_step_flow(wake_heard, command_heard, expected):
    p = _parser()
    assert _cmd(p.feed(wake_heard, 0.0)) == WAKE
    assert _cmd(p.feed(command_heard, 2.5)) == expected


def test_last_wake_phrase_wins_and_trailing_words_ignored():
    p = _parser()
    assert _cmd(p.feed("hey bass quiet hey bass voice mode please", 0.0)) == "voice"
    assert _cmd(p.feed("hey bass quiet mode now", 1.0)) == "quiet"


def test_armed_window_tolerates_leading_noise():
    p = _parser()
    p.feed("hey bass", 0.0)
    assert _cmd(p.feed("[unk] repeat", 1.0)) == "repeat"


def test_unknown_speech_after_wake_does_not_consume_window():
    p = _parser()
    p.feed("hey bass", 0.0)
    assert p.feed("[unk]", 1.0) is None
    assert _cmd(p.feed("pause", 2.0)) == "pause"


def test_grammar_has_catch_all_and_every_phrase():
    g = _parser().grammar()
    assert "[unk]" in g
    assert "hey bass" in g and "hey bass next step" in g and "next step" in g


def test_phrase_mapped_to_two_commands_rejected():
    with pytest.raises(ValueError):
        WakeCommandParser("hey bass", {"pause": ["stop"], "resume": ["stop"]})


def test_shipped_config_commands_parse():
    vc = load_runtime_config()["voice_control"]
    p = WakeCommandParser(vc["wake_phrase"], vc["commands"], vc["command_window_s"])
    for cmd, phrases in vc["commands"].items():
        for phrase in phrases:
            assert _cmd(p.feed(f"{vc['wake_phrase']} {phrase}", 0.0)) == cmd


# --- real recognizer, fed Piper-synthesized speech (no microphone) ------------

def _recognize(text):
    np = pytest.importorskip("numpy")
    pytest.importorskip("vosk")
    pytest.importorskip("piper")
    from vosk import KaldiRecognizer, Model, SetLogLevel

    from src.runtime.audio_out import resample_linear
    from src.runtime.tts import PiperTTS

    vc = load_runtime_config()["voice_control"]
    model_dir = REPO / vc["model"]
    voice = REPO / "models" / "tts" / "en_US-lessac-medium.onnx"
    if not model_dir.is_dir() or not voice.is_file():
        pytest.skip("vendored ASR/TTS models not present")
    global _MODELS
    if "_MODELS" not in globals():
        SetLogLevel(-1)
        _MODELS = (Model(str(model_dir)), PiperTTS(voice))
    model, tts = _MODELS
    parser = WakeCommandParser(vc["wake_phrase"], vc["commands"], vc["command_window_s"])
    audio = resample_linear(tts.synthesize(text), tts.sample_rate, 16000)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    rec = KaldiRecognizer(model, 16000, json.dumps(parser.grammar()))
    for i in range(0, len(pcm), 3200):
        rec.AcceptWaveform(pcm[i:i + 3200])
    return parser.feed(json.loads(rec.FinalResult()).get("text", ""), 0.0)


@pytest.mark.parametrize("spoken,expected", [
    ("Hey BAS, pause.", "pause"),
    ("Hey BAS, resume.", "resume"),
    ("Hey BAS, quiet mode.", "quiet"),
    ("Hey BAS, voice mode.", "voice"),
    ("Hey BAS, repeat.", "repeat"),
    ("Hey BAS, next step.", "next"),
    ("Hey BAS.", WAKE),
])
def test_recognizer_hears_commands(spoken, expected):
    assert _cmd(_recognize(spoken)) == expected


@pytest.mark.parametrize("spoken", [
    "Pause the music.",
    "The bass guitar is loud.",
    "Remove the second specimen module.",
    "Hey, what is the time?",
])
def test_recognizer_ignores_ordinary_speech(spoken):
    assert _recognize(spoken) is None


# --- mic health (2026-09-24: DroidCam's virtual mic became the default) ------

def _bare_listener():
    from src.runtime.voice_control import VoiceCommandListener

    lst = object.__new__(VoiceCommandListener)  # no Vosk model needed
    lst._started_at = 100.0
    return lst


def test_dither_only_input_counts_as_silent():
    np = pytest.importorskip("numpy")
    lst = _bare_listener()
    # the measured DroidCam virtual mic: only -1/0/+1
    lst.note_audio(np.array([0, 1, -1, 0] * 400, dtype=np.int16).tobytes())
    assert lst.mic_silent_for(now=109.0) == 9.0


def test_real_room_noise_counts_as_live():
    np = pytest.importorskip("numpy")
    lst = _bare_listener()
    lst.note_audio(np.array([0, 3, -32, 5] * 400, dtype=np.int16).tobytes())
    assert lst.mic_silent_for(now=109.0) == 0.0


class _FakeSD:
    DEVICES = [
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Microphone (DroidCam Audio)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Microphone Array (2- Intel Sma", "max_input_channels": 2, "hostapi": 0},
        {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
        {"name": "Microphone Array (2- Intel Smart Sound)", "max_input_channels": 2, "hostapi": 2},
    ]

    def query_devices(self, device=None, kind=None):
        if device is None and kind == "input":
            return self.DEVICES[1]
        if device is None:
            return self.DEVICES
        return self.DEVICES[device]


def test_device_name_resolves_to_default_host_api_match():
    from src.runtime.voice_control import resolve_input_device

    assert resolve_input_device(_FakeSD(), "microphone array") == 2
    assert resolve_input_device(_FakeSD(), None) is None
    assert resolve_input_device(_FakeSD(), 4) == 4
    with pytest.raises(ValueError):
        resolve_input_device(_FakeSD(), "no such mic")


def test_shipped_config_restart_phrases_parse_and_need_the_wake_phrase():
    vc = load_runtime_config()["voice_control"]
    p = WakeCommandParser(vc["wake_phrase"], vc["commands"], vc["command_window_s"])
    assert _cmd(p.feed("hey bass restart experiment", 0.0)) == "restart"
    assert _cmd(p.feed("hey bass start over", 1.0)) == "restart"
    assert _cmd(p.feed("hey bass resume", 2.0)) == "resume"
    assert p.feed("start over", 20.0) is None  # no wake phrase, no window: ignored
