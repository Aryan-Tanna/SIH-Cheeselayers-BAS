"""Offline text-to-speech backends.

Piper (onnxruntime, neural voice) is the product backend: offline, CPU,
and the same wheel + voice file work on Windows, macOS and Linux.
NullTTS is the degraded path -- no voice, the text is printed instead --
so a missing voice model on demo day costs speech, never the session.

Everything is rendered to mono float32 samples at the backend's own
sample rate and cached by text. Callers pre-warm the cache with every
phrase the loaded protocol can speak (announcer.speakable_phrases), so
an alert never waits on synthesis at the moment it fires.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol


class TTSBackend(Protocol):
    name: str
    sample_rate: int

    def synthesize(self, text: str) -> Any | None:
        """Mono float32 samples, or None if this backend cannot speak."""
        ...


class NullTTS:
    """No voice. Returning None tells the audio worker to print the text
    and play the earcon alone."""

    name = "none"
    sample_rate = 22050

    def synthesize(self, text: str) -> Any | None:
        return None


class PiperTTS:
    name = "piper"

    def __init__(self, voice_model: str | Path, length_scale: float = 1.0,
                 threads: int = 2) -> None:
        # Imported here, not at module scope: piper is an optional extra.
        import json

        import onnxruntime
        from piper import PiperVoice, SynthesisConfig
        from piper.config import PiperConfig

        model = Path(voice_model)
        if not model.is_file():
            raise FileNotFoundError(f"Piper voice model not found: {model}")
        if not Path(str(model) + ".json").is_file():
            raise FileNotFoundError(f"Piper voice config not found: {model}.json")
        # Thread cap. onnxruntime defaults to one thread per core, and so
        # does torch (the detector): started together they oversubscribed
        # the CPU and the detector's first frame took 5.4 s instead of
        # ~80 ms (measured 2026-09-25), so a 14 s session saw no detection
        # at all. Speech is pre-rendered once and cached, so it can be slow;
        # the detector cannot.
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = max(1, int(threads))
        opts.inter_op_num_threads = 1
        self._voice = PiperVoice(
            config=PiperConfig.from_dict(json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))),
            session=onnxruntime.InferenceSession(str(model), sess_options=opts,
                                                 providers=["CPUExecutionProvider"]),
        )
        self._syn_config = SynthesisConfig(length_scale=length_scale)
        self.sample_rate = int(self._voice.config.sample_rate)

    def synthesize(self, text: str) -> Any | None:
        import numpy as np

        chunks = [
            chunk.audio_float_array
            for chunk in self._voice.synthesize(text, syn_config=self._syn_config)
        ]
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.float32)


class CachedTTS:
    """Text -> samples cache in front of any backend. Thread-safe: the
    pre-warm may run on the loader's thread while the audio worker reads."""

    def __init__(self, backend: TTSBackend) -> None:
        self.backend = backend
        self._cache: dict[str, Any | None] = {}
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        return self.backend.sample_rate

    def get(self, text: str) -> Any | None:
        with self._lock:
            if text in self._cache:
                return self._cache[text]
        samples = self.backend.synthesize(text)
        with self._lock:
            self._cache[text] = samples
        return samples

    def prewarm(self, phrases: list[str]) -> int:
        """Render every phrase not already cached. Returns how many were
        rendered."""
        rendered = 0
        for text in phrases:
            with self._lock:
                if text in self._cache:
                    continue
            self.get(text)
            rendered += 1
        return rendered


def build_tts(tts_cfg: dict[str, Any], repo_root: Path) -> tuple[TTSBackend, str | None]:
    """Build the configured backend, degrading to NullTTS rather than
    failing. Returns (backend, warning-or-None) so the caller can print
    why speech is unavailable at startup, where someone will see it."""
    backend = tts_cfg.get("backend", "piper")
    if backend == "none":
        return NullTTS(), None
    if backend != "piper":
        raise ValueError(f"audio.tts.backend must be 'piper' or 'none', got {backend!r}")
    model = Path(tts_cfg["voice_model"])
    if not model.is_absolute():
        model = repo_root / model
    try:
        return PiperTTS(model, length_scale=float(tts_cfg.get("length_scale", 1.0)),
                        threads=int(tts_cfg.get("threads", 2))), None
    except (ImportError, FileNotFoundError, OSError) as exc:
        return NullTTS(), f"TTS unavailable, falling back to earcons + printed text: {exc}"
