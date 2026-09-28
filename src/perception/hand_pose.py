"""Hand skeletons (MediaPipe HandLandmarker, VIDEO mode) on bare hands, and
the grasp / reach cues computed from them (src/kinematics/fingers.py).

VIDEO mode, not IMAGE: it tracks each hand from frame to frame instead of
re-detecting it. Measured 2026-09-28 on 4 clips (v5 hand_bare boxes, the
live detector's frame rate): a skeleton on 92-98% of bare hands, against
19-64% for per-frame IMAGE mode -- the mode every earlier test used.

Every hand gets a skeleton attempt; a skeleton is then REMOVED if it lies
on a hand the detector calls gloved (MediaPipe finds 14% of gloved hands,
and a skeleton on a glove is usually wrong). The display says "gloved"
instead of drawing it.

Frames are downscaled to `input_width` before MediaPipe: its landmarks are
normalised, and the full 1080p frame cost ~53 ms per call.

Cues are SOFT (CLAUDE.md: intent is never a hard alert): "reaching for the
yellow module (0.8 s)", "holding the red module". They drive the display
and the log's hand lines, never an engine violation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.kinematics.fingers import Box, FingerGrasp, Point


@dataclass(frozen=True)
class HandPoseConfig:
    model: str = "models/hand_landmarker.task"
    input_width: int = 640
    min_confidence: float = 0.5
    num_hands: int = 2
    bare_only: bool = True
    gloved_classes: tuple[str, ...] = ("hand_gloved",)
    reach_horizon_s: float = 1.0
    reach_window_s: float = 0.6
    reach_min_distance: float = 0.3  # hand scales: closer than this, reaching == already there
    reach_min_speed: float = 0.0  # hand scales per second
    reach_k: int = 2
    reach_n: int = 4

    @classmethod
    def from_config(cls, runtime_cfg: dict[str, Any]) -> "HandPoseConfig | None":
        h = (runtime_cfg.get("perception") or {}).get("hand_pose") or {}
        if not h.get("enabled", False):
            return None
        return cls(
            model=str(h.get("model", cls.model)),
            input_width=int(h.get("input_width", 640)),
            min_confidence=float(h.get("min_confidence", 0.5)),
            num_hands=int(h.get("num_hands", 2)),
            bare_only=bool(h.get("bare_only", True)),
            gloved_classes=tuple(h.get("gloved_classes", ["hand_gloved"])),
            reach_horizon_s=float(h.get("reach_horizon_s", 1.0)),
            reach_window_s=float(h.get("reach_window_s", 0.6)),
            reach_min_distance=float(h.get("reach_min_distance", 0.3)),
            reach_min_speed=float(h.get("reach_min_speed", 0.0)),
            reach_k=int(h.get("reach_k", 2)),
            reach_n=int(h.get("reach_n", 4)),
        )


@dataclass
class HandPose:
    landmarks: list[Point]  # 21 points, full-frame pixels
    handedness: str  # MediaPipe's "Left"/"Right" (image-relative; used as a track key only)
    score: float


@dataclass
class HandCue:
    obj: str  # "module_a", "module_a.lid"
    state: str  # "holding" | "reaching"
    eta_s: float | None = None


@dataclass
class HandFrame:
    poses: list[HandPose] = field(default_factory=list)
    cues: list[HandCue] = field(default_factory=list)
    gloved_hands: int = 0  # hands with no skeleton because they are gloved
    ms: float = 0.0


def _aabb(corners: Any) -> Box:
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _share_inside(lm: list[Point], box: Box, grow: float = 0.15) -> float:
    gx, gy = (box[2] - box[0]) * grow, (box[3] - box[1]) * grow
    n = sum(box[0] - gx <= x <= box[2] + gx and box[1] - gy <= y <= box[3] + gy for x, y in lm)
    return n / max(len(lm), 1)


class HandPoseEstimator:
    def __init__(self, cfg: HandPoseConfig, repo_root: Path, hand_classes: set[str],
                 objects: dict[str, set[str]]) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        path = Path(cfg.model)
        if not path.is_absolute():
            path = Path(repo_root) / path
        if not path.is_file():
            raise FileNotFoundError(f"hand landmark model not found: {path}")
        self.cfg = cfg
        self.hand_classes = hand_classes
        self.objects = objects  # name -> detector classes, e.g. {"module_a": {"red_module"}}
        self._mp = mp
        self._lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO, num_hands=cfg.num_hands,
            min_hand_detection_confidence=cfg.min_confidence,
            min_hand_presence_confidence=cfg.min_confidence,
            min_tracking_confidence=cfg.min_confidence))
        self._last_ms = -1
        self._grasp = FingerGrasp(horizon_s=cfg.reach_horizon_s, window_s=cfg.reach_window_s,
                                  min_distance=cfg.reach_min_distance, min_speed=cfg.reach_min_speed,
                                  reach_k=cfg.reach_k, reach_n=cfg.reach_n)

    def process(self, frame_bgr: Any, ts: float, dets: list[Any]) -> HandFrame:
        """ts: capture time (s). dets: this frame's detections."""
        import cv2
        import numpy as np

        out = HandFrame()
        hands = [d for d in dets if d.cls in self.hand_classes]
        gloved = [d for d in hands if d.cls in self.cfg.gloved_classes]
        bare = [d for d in hands if d not in gloved]
        poses: list[HandPose] = []
        # MediaPipe runs on EVERY frame, whatever the detector thinks of the
        # hands; a skeleton is only REMOVED afterwards when it lies on a hand
        # the detector calls gloved (more than on a bare one). A hand the
        # detector missed keeps its skeleton.
        t0 = time.perf_counter()
        h, w = frame_bgr.shape[:2]
        small = frame_bgr
        if self.cfg.input_width and w > self.cfg.input_width:
            small = cv2.resize(frame_bgr, (self.cfg.input_width, int(self.cfg.input_width * h / w)),
                               interpolation=cv2.INTER_AREA)
        ms = max(int(ts * 1000), self._last_ms + 1)  # VIDEO mode needs strictly increasing times
        self._last_ms = ms
        rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        res = self._lm.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ms)
        bare_boxes = [_aabb(d.corners) for d in bare]
        glove_boxes = [_aabb(d.corners) for d in gloved]
        for i, hand in enumerate(res.hand_landmarks):
            lm = [(p.x * w, p.y * h) for p in hand]
            on_glove = max((_share_inside(lm, b) for b in glove_boxes), default=0.0)
            on_bare = max((_share_inside(lm, b) for b in bare_boxes), default=0.0)
            if self.cfg.bare_only and on_glove >= 0.5 and on_glove > on_bare:
                out.gloved_hands += 1
                continue
            cat = res.handedness[i][0] if i < len(res.handedness) and res.handedness[i] else None
            poses.append(HandPose(lm, cat.category_name if cat else "?", float(cat.score) if cat else 0.0))
        out.ms = (time.perf_counter() - t0) * 1000
        out.poses = poses
        out.cues = self._cues(ts, poses, dets)
        return out

    def _cues(self, ts: float, poses: list[HandPose], dets: list[Any]) -> list[HandCue]:
        # every (object, hand) pair updates every frame (the trackers need
        # continuity); then a hand already holding something is not
        # "reaching" for anything, and a hand reaches for one object at a time
        states: dict[tuple[str, str], Any] = {}
        for name, classes in self.objects.items():
            cands = [d for d in dets if d.cls in classes]
            box = _aabb(max(cands, key=lambda d: d.conf).corners) if cands else None
            for side in ("Left", "Right"):
                pose = next((p for p in poses if p.handedness == side), None)
                states[(name, side)] = self._grasp.update((name, side), ts, pose.landmarks if pose else None, box)
        best: dict[str, HandCue] = {}
        for side in ("Left", "Right"):
            mine = {n: st for (n, sd), st in states.items() if sd == side}
            held = [n for n, st in mine.items() if st.grasping]
            for n in held:
                best[n] = HandCue(n, "holding")
            if held:
                continue
            reach = [(st.eta_s if st.eta_s is not None else 9.0, n) for n, st in mine.items() if st.reaching]
            if reach:
                eta, n = min(reach)
                if n not in best or (best[n].state == "reaching" and eta < (best[n].eta_s or 9.0)):
                    best[n] = HandCue(n, "reaching", eta)
        return list(best.values())

    def close(self) -> None:
        self._lm.close()
