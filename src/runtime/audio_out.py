"""Audio output sinks.

A sink plays one mono float32 clip, blocking until it finishes or until
the caller's `cancel` event is set from ANOTHER thread -- that is how a
warning cuts off whatever is currently being said. The cancel event is
per clip and owned by the caller, so a cancel issued before playback has
even started is still honoured (a sink-owned "stop" flag reset at the
start of play() would silently lose it).

SoundDeviceSink is the real one (PortAudio: WASAPI/CoreAudio/ALSA, so
the same code runs on Windows, macOS and Linux). RecordingSink is for
tests and headless runs: it records what would have played.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Protocol


def resample_linear(samples: Any, src_rate: int, dst_rate: int | None) -> Any:
    """Linear-interpolation resample. Adequate for speech and pure tones
    (the only two things this sink plays); avoids a scipy dependency."""
    import numpy as np

    if dst_rate is None or src_rate == dst_rate or len(samples) == 0:
        return samples
    n_out = max(1, int(round(len(samples) * dst_rate / src_rate)))
    x_out = np.arange(n_out, dtype=np.float64) * (src_rate / dst_rate)
    return np.interp(x_out, np.arange(len(samples)), samples).astype(np.float32)


def _wasapi_default_output(sd: Any) -> int | None:
    for api in sd.query_hostapis():
        if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
            return int(api["default_output_device"])
    return None


class AudioSink(Protocol):
    def play(self, samples: Any, sample_rate: int, cancel: threading.Event) -> bool:
        """Blocking. True if the clip played to the end, False if
        `cancel` cut it short (or was already set)."""
        ...


class SoundDeviceSink:
    """One output stream held open for the session, emitting silence when
    idle; play() hands a clip to its callback.

    Opening a stream per clip was measured at 105-121 ms from open to the
    first audio callback (Windows laptop, default device) -- most of the
    150 ms glass-to-alert budget spent before a sample is heard. With a
    persistent stream, handing a clip over measured under ~1 ms after
    warm-up, plus the device's own output latency (22 ms on WASAPI).
    The stream runs at the device's native rate; clips are resampled.
    """

    def __init__(self, device: int | str | None = None) -> None:
        import sounddevice  # noqa: F401  -- fail at construction, not first alert

        self.device = device
        self._lock = threading.Lock()
        self._stream: Any = None
        self._rate: int | None = None  # the STREAM's rate; clips are resampled to it
        # Current clip state, touched by play() and the audio callback.
        self._data: Any = None
        self._pos = 0
        self._cancel: threading.Event | None = None
        self._done: threading.Event | None = None

    def open(self) -> None:
        """Open once, at the device's native rate. On Windows with no
        explicit device, prefer WASAPI: measured 22 ms output latency vs
        91 ms for the MME default (and 120 ms DirectSound). WASAPI only
        accepts the device's native rate, which is why clips are
        resampled rather than the stream opened at the voice's rate.
        Falls back to the default device if WASAPI will not open."""
        import sounddevice as sd

        if self._stream is not None:
            return
        candidates: list[int | str | None] = []
        if self.device is None and sys.platform == "win32":
            wasapi = _wasapi_default_output(sd)
            if wasapi is not None:
                candidates.append(wasapi)
        candidates.append(self.device)

        last_exc: Exception | None = None
        for dev in candidates:
            try:
                rate = int(sd.query_devices(dev, kind="output")["default_samplerate"])
                stream = sd.OutputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    device=dev,
                    latency="low",
                    callback=self._callback,
                )
                stream.start()
            except Exception as exc:  # noqa: BLE001 -- PortAudioError, try next
                last_exc = exc
                continue
            self._stream, self._rate = stream, rate
            return
        raise RuntimeError(f"could not open any audio output: {last_exc}")

    @property
    def output_latency_ms(self) -> float | None:
        return None if self._stream is None else 1000.0 * float(self._stream.latency)

    def _callback(self, outdata: Any, frames: int, _time: Any, _status: Any) -> None:
        with self._lock:
            data, done, cancel = self._data, self._done, self._cancel
            if data is None:
                outdata.fill(0)
                return
            if cancel is not None and cancel.is_set():
                outdata.fill(0)
                self._data = None
                done.set()  # type: ignore[union-attr]
                return
            chunk = data[self._pos:self._pos + frames]
            outdata[:len(chunk), 0] = chunk
            if len(chunk) < frames:
                outdata[len(chunk):, 0] = 0
                self._data = None
                done.set()  # type: ignore[union-attr]
            self._pos += frames

    def play(self, samples: Any, sample_rate: int, cancel: threading.Event) -> bool:
        import numpy as np

        if cancel.is_set():
            return False
        self.open()
        data = resample_linear(np.asarray(samples, dtype=np.float32).reshape(-1), sample_rate, self._rate)
        done = threading.Event()
        with self._lock:
            self._data = data
            self._pos = 0
            self._cancel = cancel
            self._done = done
        # Also wake on cancel directly: the callback only runs once per
        # audio block, and the worker should be free immediately.
        while not done.wait(0.02):
            if cancel.is_set():
                with self._lock:
                    self._data = None
                break
        return not cancel.is_set()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
                self._rate = None


class RecordingSink:
    """Records clips instead of playing them. With block=True a clip stays
    "playing" until release() or its cancel event, so tests can exercise
    interruption deterministically."""

    def __init__(self, block: bool = False) -> None:
        self.played: list[tuple[Any, int]] = []
        self.completed: list[bool] = []
        self._block = block
        self._release = threading.Event()
        self.playing = threading.Event()

    def play(self, samples: Any, sample_rate: int, cancel: threading.Event) -> bool:
        self.played.append((samples, sample_rate))
        self.playing.set()
        if self._block:
            while not (cancel.is_set() or self._release.is_set()):
                cancel.wait(0.005)
            self._release.clear()
        self.playing.clear()
        ok = not cancel.is_set()
        self.completed.append(ok)
        return ok

    def release(self) -> None:
        """Let the currently blocked clip finish normally."""
        self._release.set()
