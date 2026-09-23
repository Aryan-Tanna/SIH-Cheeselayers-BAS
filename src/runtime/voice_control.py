"""Hands-free operator commands: "Hey BAS, pause".

Two parts:

* WakeCommandParser -- pure. Turns recognized utterance text into a
  command, enforcing the wake phrase. Unit-tested without audio.
* VoiceCommandListener -- microphone -> Vosk -> parser, on its own
  thread. Vosk runs offline on CPU on Windows, macOS and Linux.

Recognition is restricted to a fixed grammar (the wake phrase, the
command phrases, and Vosk's "[unk]" catch-all). Without "[unk]" the
recognizer would force ANY speech onto the nearest command, which is
exactly how a system pauses itself mid-experiment. With it, ordinary
speech comes back as "[unk]".

Accepted forms (see WakeCommandParser.feed for the exact rule):
  "hey bass pause"            -- wake + command in one breath
  "[unk] hey hey bass pause"  -- noise / stutter before the wake phrase
  "hey bass" ... "pause"      -- wake, chime, command within the window
A command without the wake phrase, outside the window, is ignored.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

WAKE = "wake"  # parser result: wake phrase alone, now listening


@dataclass
class ParsedCommand:
    command: str  # a key of the commands table, or WAKE
    text: str


class WakeCommandParser:
    def __init__(
        self,
        wake_phrase: str,
        commands: dict[str, list[str]],
        window_s: float = 5.0,
    ) -> None:
        self.wake_phrase = _norm(wake_phrase)
        if not self.wake_phrase:
            raise ValueError("wake_phrase must not be empty")
        self.window_s = window_s
        self._phrase_to_command: dict[str, str] = {}
        for cmd, phrases in commands.items():
            for phrase in phrases:
                key = _norm(phrase)
                if key in self._phrase_to_command and self._phrase_to_command[key] != cmd:
                    raise ValueError(f"phrase {phrase!r} maps to two commands")
                self._phrase_to_command[key] = cmd
        self._armed_at: float | None = None

    def grammar(self) -> list[str]:
        phrases = list(self._phrase_to_command)
        return (
            [self.wake_phrase]
            + [f"{self.wake_phrase} {p}" for p in phrases]
            + phrases
            + ["[unk]"]
        )

    @property
    def armed(self) -> bool:
        return self._armed_at is not None

    def _command_at_start(self, tokens: list[str]) -> str | None:
        """Longest command phrase that the token list STARTS with."""
        best: tuple[int, str] | None = None
        for phrase, cmd in self._phrase_to_command.items():
            words = phrase.split()
            if tokens[: len(words)] == words and (best is None or len(words) > best[0]):
                best = (len(words), cmd)
        return best[1] if best else None

    def feed(self, text: str, now: float) -> ParsedCommand | None:
        """Tuned on a live-mic session (2026-09-24), where an exact
        whole-utterance rule accepted only 4 of 12 utterances that
        contained the wake phrase. Real speech carries a breath or noise
        before the wake phrase ("[unk] hey bass pause"), stutters ("hey
        hey bass resume") and repeats ("hey bass resume hey resume").
        So: the wake phrase may appear anywhere -- the LAST occurrence
        counts -- and the command must START right after it; trailing
        words are ignored. The wake phrase is what makes speech a
        command, so without it (and outside the wake window) nothing is
        ever accepted: "pause the video" still does nothing.

        Wake phrase heard but no command understood ("hey bass [unk]")
        counts as the wake phrase alone: chime, then the operator has the
        window to say just the command.
        """
        t = _norm(text)
        if not t:
            return None
        if self._armed_at is not None and now - self._armed_at > self.window_s:
            self._armed_at = None

        tokens = t.split()
        wake = self.wake_phrase.split()
        n = len(wake)
        last = max(
            (i for i in range(len(tokens) - n + 1) if tokens[i:i + n] == wake),
            default=None,
        )
        if last is not None:
            rest = tokens[last + n:]
            cmd = self._command_at_start(rest)
            if cmd is not None:
                self._armed_at = None
                return ParsedCommand(cmd, t)
            self._armed_at = now
            return ParsedCommand(WAKE, t)

        if self._armed_at is not None:
            while tokens and tokens[0] == "[unk]":
                tokens = tokens[1:]
            cmd = self._command_at_start(tokens)
            if cmd is not None:
                self._armed_at = None
                return ParsedCommand(cmd, t)
        return None


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(",", " ").replace(".", " ").split())


class VoiceCommandListener:
    """Mic -> Vosk (grammar-restricted) -> parser -> on_command(cmd).

    Callbacks run on the listener thread; the session serialises them
    against the perception thread with its own lock.
    """

    SAMPLE_RATE = 16000

    def __init__(
        self,
        model_path: str | Path,
        parser: WakeCommandParser,
        on_command: Callable[[ParsedCommand], None],
        device: int | str | None = None,
    ) -> None:
        # Imported here: optional extra, never at module scope under src/.
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model_path = Path(model_path)
        if not model_path.is_dir():
            raise FileNotFoundError(f"Vosk model not found: {model_path}")
        self._model = Model(str(model_path))
        self._recognizer_cls = KaldiRecognizer
        self.parser = parser
        self.on_command = on_command
        self.device = device
        self._audio: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: Any = None

    def new_recognizer(self) -> Any:
        return self._recognizer_cls(self._model, self.SAMPLE_RATE, json.dumps(self.parser.grammar()))

    def feed_text(self, text: str) -> ParsedCommand | None:
        """Route one recognized utterance through the parser. Split out so
        tests (and a keyboard fallback) can drive it without a mic."""
        parsed = self.parser.feed(text, time.monotonic())
        if parsed is not None:
            self.on_command(parsed)
        return parsed

    def start(self) -> None:
        import sounddevice as sd

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            try:
                self._audio.put_nowait(bytes(indata))
            except queue.Full:
                pass  # recognizer fell behind: drop audio, never block the mic

        self._stream = sd.RawInputStream(
            samplerate=self.SAMPLE_RATE, blocksize=1600, dtype="int16", channels=1,
            device=self.device, callback=callback,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._run, name="voice_control", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        rec = self.new_recognizer()
        while not self._stop.is_set():
            try:
                chunk = self._audio.get(timeout=0.1)
            except queue.Empty:
                continue
            if rec.AcceptWaveform(chunk):
                text = json.loads(rec.Result()).get("text", "")
                try:
                    self.feed_text(text)
                except Exception:  # noqa: BLE001 -- a bad command must not kill listening
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def build_listener(
    cfg: dict[str, Any],
    repo_root: Path,
    on_command: Callable[[ParsedCommand], None],
) -> tuple[VoiceCommandListener | None, str | None]:
    """Build from configs/runtime.yaml's voice_control section. Returns
    (None, warning) rather than raising when voice control cannot run --
    the session works without it (GUI/keyboard commands remain)."""
    vc = cfg.get("voice_control") or {}
    if not vc.get("enabled", False):
        return None, None
    parser = WakeCommandParser(
        vc["wake_phrase"], vc["commands"], float(vc.get("command_window_s", 5.0))
    )
    model = Path(vc["model"])
    if not model.is_absolute():
        model = repo_root / model
    try:
        listener = VoiceCommandListener(model, parser, on_command, vc.get("input_device"))
    except (ImportError, FileNotFoundError, OSError) as exc:
        return None, f"voice control unavailable: {exc}"
    return listener, None
