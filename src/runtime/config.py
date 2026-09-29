"""configs/runtime.yaml loading, and assembly of the audio stage from it.

Every "this part is unavailable" case (no piper package, no voice file,
no audio device) degrades and returns a human-readable warning instead
of raising: the caller prints those at startup. Only a malformed config
raises -- that is an authoring error and should fail loudly at load.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.protocol.loader import load_yaml
from src.runtime.audio import AudioWorker, console_printer
from src.runtime.audio_out import AudioSink, SoundDeviceSink
from src.runtime.earcons import EarconSpec
from src.runtime.tts import CachedTTS, build_tts

from src.protocol.loader import REPO_ROOT  # noqa: E402  (frozen-aware)
DEFAULT_RUNTIME_CONFIG = REPO_ROOT / "configs" / "runtime.yaml"


def load_runtime_config(path: str | Path = DEFAULT_RUNTIME_CONFIG) -> dict[str, Any]:
    cfg = load_yaml(path)
    for key in ("detector", "audio"):
        if key not in cfg:
            raise ValueError(f"{path}: missing top-level '{key}' section")
    return cfg


def resolve_repo_path(p: str | Path, repo_root: Path = REPO_ROOT) -> Path:
    path = Path(p)
    return path if path.is_absolute() else repo_root / path


def detector_weights_path(cfg: dict[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    """The one place the runtime learns which weights to load, so a new
    detector is a one-line change in configs/runtime.yaml."""
    return resolve_repo_path(cfg["detector"]["weights"], repo_root)


class SilentSink:
    """No audio device: 'plays' instantly. The worker echoes text to the
    console so the session is still followable."""

    def play(self, samples: Any, sample_rate: int, cancel: threading.Event) -> bool:
        return not cancel.is_set()


@dataclass
class AudioStage:
    worker: AudioWorker | None  # None = audio disabled in config
    tts_backend: str
    sink_name: str
    warnings: list[str] = field(default_factory=list)
    _prewarm_thread: threading.Thread | None = None

    def prewarm_async(self, phrases: list[str]) -> None:
        """Render phrases on a background thread (measured ~0.4-0.9 s per
        phrase with Piper medium on a laptop CPU -- too slow to do at
        alert time, too slow to block startup on). A phrase requested
        before its pre-render finishes is synthesized on demand."""
        if self.worker is None:
            return
        tts = self.worker.tts
        self._prewarm_thread = threading.Thread(
            target=tts.prewarm, args=(phrases,), name="tts_prewarm", daemon=True
        )
        self._prewarm_thread.start()

    def wait_prewarm(self, timeout: float | None = None) -> None:
        if self._prewarm_thread is not None:
            self._prewarm_thread.join(timeout)


def build_audio_stage(
    cfg: dict[str, Any],
    repo_root: Path = REPO_ROOT,
    sink: AudioSink | None = None,
    printer: Callable[[str], None] = console_printer,
) -> AudioStage:
    audio_cfg = cfg["audio"]
    if not audio_cfg.get("enabled", True):
        return AudioStage(worker=None, tts_backend="disabled", sink_name="disabled")

    warnings: list[str] = []
    backend, warn = build_tts(audio_cfg["tts"], repo_root)
    if warn:
        warnings.append(warn)

    echo_text = False
    sink_name = type(sink).__name__ if sink is not None else ""
    if sink is None:
        device = audio_cfg.get("output", {}).get("device")
        try:
            sd_sink = SoundDeviceSink(device=device)
            # Open now: the first alert must not pay stream start-up, and
            # a missing device should surface here, not mid-session.
            sd_sink.open()
            sink = sd_sink
            latency = sd_sink.output_latency_ms
            sink_name = f"sounddevice ({latency:.0f} ms output latency)" if latency else "sounddevice"
        except Exception as exc:  # noqa: BLE001 -- ImportError, PortAudioError, no device
            sink = SilentSink()
            sink_name = "silent"
            echo_text = True
            warnings.append(f"no audio output, alerts will be printed only: {exc}")

    earcons = {
        severity: EarconSpec.from_config(spec)
        for severity, spec in audio_cfg.get("earcons", {}).items()
    }
    worker = AudioWorker(
        tts=CachedTTS(backend),
        sink=sink,
        earcons=earcons,
        volume=float(audio_cfg.get("output", {}).get("volume", 0.8)),
        queue_maxsize=int(audio_cfg.get("queue_maxsize", 4)),
        printer=printer,
        echo_text=echo_text,
        # A wake chime holds speech for the voice-command window.
        hold_s=float(cfg.get("voice_control", {}).get("command_window_s", 5.0)),
    )
    return AudioStage(worker=worker, tts_backend=backend.name, sink_name=sink_name, warnings=warnings)
