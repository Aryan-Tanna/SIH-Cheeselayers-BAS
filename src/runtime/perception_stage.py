"""Live perception stage: newest camera frame -> detector -> fusion ->
Session.on_event().

The detector is the slowest stage (~95-105 ms per 1080p frame on a
laptop CPU, measured), so this stage never queues: it holds only the
NEWEST frame and processes that, skipping whatever arrived meanwhile --
the pipeline rule that stale frames are dropped, not worked through.
Capture and recording keep their own full rate regardless.

Every event carries the frame's CAPTURE timestamp (acquisition time), so
the log and the recording stay aligned however long inference took.
Latency is measured, not assumed:
  frame latency  = time the detections for a frame are ready - capture ts
  event latency  = time a step event reaches the session  - capture ts of
                   the frame that confirmed it (includes nothing of the
                   debounce wait before it; that is k frames by design)
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from src.perception.detector import Detection, Detector
from src.perception.fusion import SceneFusion
from src.protocol.events import SemanticEvent
from src.runtime.pipeline import Frame


@dataclass
class PerceptionStats:
    frames_processed: int = 0
    frames_skipped: int = 0  # newer frame arrived before this one was picked up
    detector_fps: float = 0.0
    inference_ms: float = 0.0
    frame_latency_ms: float = 0.0  # rolling mean
    events: int = 0


class PerceptionStage:
    def __init__(self, detector: Detector, fusion: SceneFusion,
                 emit: Callable[[SemanticEvent], None],
                 clock: Callable[[], float] = time.monotonic,
                 printer: Callable[[str], None] = print) -> None:
        self.detector = detector
        self.fusion = fusion
        self.emit = emit
        self.clock = clock
        self.printer = printer
        self.stats = PerceptionStats()
        self._slot: Frame | None = None
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: tuple[int, list[Detection]] = (-1, [])
        self._times: deque[float] = deque(maxlen=30)
        self._lat: deque[float] = deque(maxlen=30)

    def submit(self, frame: Frame) -> None:
        """From the capture thread: replace whatever is waiting."""
        with self._cond:
            if self._slot is not None:
                self.stats.frames_skipped += 1
            self._slot = frame
            self._cond.notify()

    def latest_detections(self) -> tuple[int, list[Detection]]:
        """(frame seq, detections) of the most recent processed frame."""
        with self._cond:
            return self._latest

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="perception", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait_for(lambda: self._slot is not None or self._stop.is_set(), 0.5)
                frame, self._slot = self._slot, None
            if frame is None:
                continue
            try:
                dets = self.detector.detect(frame.payload)
            except Exception as exc:  # noqa: BLE001 -- one bad frame must not stop perception
                self.printer(f"WARNING: detector failed on a frame: {exc!r}")
                continue
            ready = self.clock()
            self._lat.append(1000.0 * (ready - frame.ts_monotonic))
            self._times.append(ready)
            s = self.stats
            s.frames_processed += 1
            s.inference_ms = self.detector.last_inference_ms
            s.frame_latency_ms = sum(self._lat) / len(self._lat)
            if len(self._times) >= 2 and self._times[-1] > self._times[0]:
                s.detector_fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])
            with self._cond:
                self._latest = (frame.seq, dets)
            for event in self.fusion.update(frame.ts_monotonic, dets):
                s.events += 1
                try:
                    self.emit(event)
                except Exception as exc:  # noqa: BLE001
                    self.printer(f"WARNING: event handling failed: {exc!r}")


def build_perception(runtime_cfg: dict[str, Any], resolved: Any, repo_root: Any,
                     emit: Callable[[SemanticEvent], None],
                     printer: Callable[[str], None] = print) -> tuple[PerceptionStage | None, str | None]:
    """None + a reason when perception is switched off or its packages are
    missing (the session still runs, driven by voice / GUI). A wrong
    weights path or a model that lacks the profile's classes RAISES:
    those are configuration errors and must fail at startup."""
    if not (runtime_cfg.get("perception") or {}).get("enabled", True):
        return None, "perception disabled in configs/runtime.yaml"
    from src.perception.detector import DetectorConfig, required_classes
    from src.perception.fusion import FusionConfig, binding_for

    try:
        detector = Detector(DetectorConfig.from_config(runtime_cfg), repo_root,
                            required=required_classes(resolved.parsed.object_profile))
    except ImportError as exc:
        return None, f"perception unavailable (install the vision extra): {exc}"
    fusion = SceneFusion(binding_for(resolved), FusionConfig.from_config(runtime_cfg, resolved.timing))
    return PerceptionStage(detector, fusion, emit, printer=printer), None
