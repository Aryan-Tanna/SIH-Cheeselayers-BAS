"""Audio worker: the runtime's audio stage, on its own thread.

Takes AudioRequests (src/runtime/announcer.py) and turns each into one
clip -- earcon, a short gap, then each spoken phrase -- played as a
single unit so an interruption cuts all of it.

Queue rules, in the spirit of src/runtime/pipeline.py (stale output is
worse than none):

  * Bounded. Past `queue_maxsize` pending items, the oldest is dropped.
  * A new next-step prompt supersedes any prompt still waiting: the
    operator only needs to hear what to do NOW.
  * A warning interrupts: it cuts off a non-warning clip mid-playback and
    flushes every pending non-warning item, then plays next. A warning
    already playing is not cut by another warning -- the second queues
    behind it (the alert policy's rate cap keeps that rare).
  * flush_all (operator pause) silences everything, warnings included,
    before its own acknowledgement plays.

Nothing here decides WHETHER to alert -- that already happened in
AlertManager via the Announcer. This only decides what reaches the
speaker and when.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from src.runtime.announcer import AudioRequest
from src.runtime.audio_out import AudioSink
from src.runtime.earcons import EarconSpec, render_earcon
from src.runtime.tts import CachedTTS

_TONE_TO_SPEECH_GAP_MS = 80
_PHRASE_GAP_MS = 180


def _ascii(text: str) -> str:
    # Protocol text may carry non-ASCII (an author's em-dash); printing it
    # raw breaks a cp1252 Windows console. See tests/test_no_nonascii_output.py.
    return text.encode("ascii", "replace").decode("ascii")


def console_printer(line: str) -> None:
    print(line, file=sys.stdout, flush=True)


@dataclass
class AudioStats:
    played: int = 0
    interrupted: int = 0
    dropped_overflow: int = 0
    superseded_prompts: int = 0
    flushed_by_warning: int = 0
    text_only: int = 0  # speech wanted, no TTS available -> printed


class AudioWorker:
    def __init__(
        self,
        tts: CachedTTS,
        sink: AudioSink,
        earcons: dict[str, EarconSpec],
        volume: float = 0.8,
        queue_maxsize: int = 4,
        printer: Callable[[str], None] = console_printer,
        echo_text: bool = False,
    ) -> None:
        if queue_maxsize < 1:
            raise ValueError("queue_maxsize must be >= 1")
        if not 0.0 <= volume <= 1.0:
            raise ValueError("volume must be within 0..1")
        self.tts = tts
        self.sink = sink
        self.earcons = earcons
        self.volume = volume
        self.queue_maxsize = queue_maxsize
        self.printer = printer
        # Print every spoken line, not only those TTS could not render --
        # set when there is no audio device, so the session is still
        # followable from the console.
        self.echo_text = echo_text
        self.stats = AudioStats()

        self._pending: deque[AudioRequest] = deque()
        self._cond = threading.Condition()
        self._current: AudioRequest | None = None
        # Replaced (under _cond) each time a request becomes current, so a
        # cancel set while the clip is still rendering is not lost.
        self._current_cancel = threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._earcon_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Producer side (called from the fusion / state-machine thread)
    # ------------------------------------------------------------------

    def submit(self, requests: list[AudioRequest]) -> None:
        with self._cond:
            for req in requests:
                self._enqueue_locked(req)
            self._cond.notify_all()

    def _enqueue_locked(self, req: AudioRequest) -> None:
        if req.flush_all:
            self.stats.flushed_by_warning += len(self._pending)
            self._pending.clear()
            if self._current is not None:
                self._current_cancel.set()
        elif req.interrupt:
            kept = deque(r for r in self._pending if r.interrupt)
            self.stats.flushed_by_warning += len(self._pending) - len(kept)
            self._pending = kept
            if self._current is not None and not self._current.interrupt:
                self._current_cancel.set()
        elif req.kind == "prompt":
            kept = deque(r for r in self._pending if r.kind != "prompt")
            self.stats.superseded_prompts += len(self._pending) - len(kept)
            self._pending = kept

        self._pending.append(req)
        while len(self._pending) > self.queue_maxsize:
            self._pending.popleft()
            self.stats.dropped_overflow += 1

    def flush(self) -> None:
        """Drop everything pending and cut what is playing."""
        with self._cond:
            self._pending.clear()
            if self._current is not None:
                self._current_cancel.set()
            self._cond.notify_all()

    def pending(self) -> list[AudioRequest]:
        with self._cond:
            return list(self._pending)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="audio", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        with self._cond:
            self._stopping = True
            self._pending.clear()
            self._current_cancel.set()
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        close = getattr(self.sink, "close", None)
        if close is not None:
            close()

    def drain(self, timeout: float = 5.0) -> bool:
        """Block until nothing is pending or playing. For tests and for a
        clean end-of-session ("Experiment complete") before shutdown."""
        with self._cond:
            return self._cond.wait_for(
                lambda: not self._pending and self._current is None, timeout=timeout
            )

    # ------------------------------------------------------------------
    # Consumer side (audio thread)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending or self._stopping)
                if self._stopping:
                    return
                req = self._pending.popleft()
                self._current = req
                cancel = threading.Event()
                self._current_cancel = cancel
            try:
                self._play(req, cancel)
            except Exception as exc:  # noqa: BLE001 -- audio must never kill the session
                self.printer(f"[audio] playback failed: {_ascii(repr(exc))}")
            finally:
                with self._cond:
                    self._current = None
                    self._cond.notify_all()

    def render(self, req: AudioRequest) -> Any | None:
        """The exact clip `req` plays: earcon, gap, phrases. None if there
        is nothing audible (e.g. a prompt with TTS unavailable)."""
        import numpy as np

        sr = self.tts.sample_rate
        parts: list[Any] = []
        if req.earcon and req.earcon in self.earcons:
            parts.append(self._earcon(req.earcon, sr))
        for i, phrase in enumerate(req.segments):
            speech = self.tts.get(phrase)
            if speech is None:
                continue
            if parts:
                gap_ms = _TONE_TO_SPEECH_GAP_MS if i == 0 else _PHRASE_GAP_MS
                parts.append(np.zeros(int(sr * gap_ms / 1000), dtype=np.float32))
            parts.append(speech)
        if not parts:
            return None
        return (np.concatenate(parts) * self.volume).astype(np.float32)

    def _earcon(self, name: str, sample_rate: int) -> Any:
        key = f"{name}@{sample_rate}"
        if key not in self._earcon_cache:
            self._earcon_cache[key] = render_earcon(self.earcons[name], sample_rate)
        return self._earcon_cache[key]

    def _play(self, req: AudioRequest, cancel: threading.Event) -> None:
        if req.segments:
            no_voice = any(self.tts.get(p) is None for p in req.segments)
            if no_voice:
                self.stats.text_only += 1
            if no_voice or self.echo_text:
                label = req.severity.upper() if req.severity else req.kind.upper()
                self.printer(f"[{label}] {_ascii(req.text)}")
        clip = self.render(req)
        if clip is None:
            return
        finished = self.sink.play(clip, self.tts.sample_rate, cancel)
        if finished:
            self.stats.played += 1
        else:
            self.stats.interrupted += 1
