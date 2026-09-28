"""Hand-skeleton thread: MediaPipe on the newest camera frame, beside the
detector, never in front of it.

Measured: MediaPipe costs ~23-27 ms per 640-wide frame. Run inside the
perception loop it would take the detector from ~20 to ~13 det-fps (and
so delay every step event); in its own thread the detector keeps its rate
and the skeletons come at whatever rate is left. Same queue rule as every
runtime stage: one slot, the newest frame replaces a waiting one.

It reads the detector's LATEST detections (bare vs gloved hands, jar and
cap boxes). They can be one detector frame older than the image: fine for
"which hands are bare" and "where are the jars", which barely move in
50 ms.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from src.perception.hand_pose import HandFrame, HandPoseEstimator
from src.runtime.pipeline import Frame


class HandStage:
    def __init__(self, estimator: HandPoseEstimator, latest_detections: Callable[[], tuple[int, list]],
                 printer: Callable[[str], None] = print) -> None:
        self.estimator = estimator
        self.latest_detections = latest_detections
        self.printer = printer
        self._slot: Frame | None = None
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest = HandFrame()
        self._times: deque[float] = deque(maxlen=30)
        self.fps = 0.0
        self.frames = 0

    def submit(self, frame: Frame) -> None:
        with self._cond:
            self._slot = frame
            self._cond.notify()

    def latest(self) -> HandFrame:
        with self._cond:
            return self._latest

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hand_pose", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
        try:
            self.estimator.close()
        except Exception:  # noqa: BLE001 -- shutting down
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait_for(lambda: self._slot is not None or self._stop.is_set(), 0.5)
                frame, self._slot = self._slot, None
            if frame is None:
                continue
            _, dets = self.latest_detections()
            try:
                hf = self.estimator.process(frame.payload, frame.ts_monotonic, dets)
            except Exception as exc:  # noqa: BLE001 -- the skeleton is optional, never fatal
                self.printer(f"WARNING: hand pose failed on a frame: {exc!r}")
                continue
            with self._cond:
                self._latest = hf
            self.frames += 1
            now = time.monotonic()
            self._times.append(now)
            if len(self._times) >= 2 and self._times[-1] > self._times[0]:
                self.fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])


def build_hand_stage(runtime_cfg: dict[str, Any], repo_root: Any, perception: Any,
                     printer: Callable[[str], None] = print) -> tuple[HandStage | None, str | None]:
    """None + why when off or unavailable. Needs the detector (perception):
    it decides which hands are bare and where the jars are."""
    from src.perception.hand_pose import HandPoseConfig

    cfg = HandPoseConfig.from_config(runtime_cfg)
    if cfg is None:
        return None, None
    if perception is None:
        return None, "hand skeletons need the detector (perception is off)"
    b = perception.fusion.binding
    objects = {role: {c} for role, c in b.modules.items()}
    objects.update({f"{role}.lid": {c} for role, c in b.lids.items()})
    hands = set(b.hand_classes) or {"hand_bare", "hand_gloved"}
    try:
        est = HandPoseEstimator(cfg, repo_root, hands, objects)
    except (ImportError, FileNotFoundError) as exc:
        return None, f"hand skeletons unavailable: {exc}"
    return HandStage(est, perception.latest_detections, printer), None
