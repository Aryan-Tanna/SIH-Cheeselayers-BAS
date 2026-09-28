"""Object detector: YOLO-OBB weights -> per-frame oriented detections.

Weights come from configs/runtime.yaml (detector.weights), so a new
model (v5, ...) is a one-line swap. What makes that swap SAFE is that
nothing downstream uses class *numbers*: detections carry class NAMES,
and at load the model's names are checked against the classes the
object profile binds. A model that renamed or dropped a class fails at
startup with the missing names, instead of silently never seeing that
object mid-experiment. Confidence / IoU / image size are config too --
a new model may need them re-tuned, never code.

ultralytics/torch are imported lazily (optional `vision` extra).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

Point = tuple[float, float]


class DetectorClassMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Detection:
    cls: str
    conf: float
    cx: float  # original-image pixels
    cy: float
    w: float
    h: float
    angle_deg: float
    corners: tuple[Point, Point, Point, Point]

    @property
    def radius(self) -> float:
        """Circumscribing radius -- the single size src/kinematics uses."""
        return math.hypot(self.w / 2.0, self.h / 2.0)

    @property
    def aabb(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.corners]
        ys = [p[1] for p in self.corners]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class DetectorConfig:
    weights: str
    conf: float = 0.25
    iou: float = 0.5
    imgsz: int = 640
    device: str = "cpu"
    threads: int | None = None  # torch CPU threads; None = physical cores - 2

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "DetectorConfig":
        d = cfg.get("detector") or {}
        return cls(
            weights=str(d["weights"]),
            conf=float(d.get("conf", 0.25)),
            iou=float(d.get("iou", 0.5)),
            imgsz=int(d.get("imgsz", 640)),
            device=str(d.get("device", "cpu")),
            threads=int(d["threads"]) if d.get("threads") else None,
        )


def required_classes(profile: dict[str, Any] | None) -> set[str]:
    """Every detector class the object profile binds a role to (module
    class_id, lid_class_id, container state classes) plus the unbound
    ones it declares (hands)."""
    if not profile:
        return set()
    out: set[str] = set(profile.get("detector_classes_not_role_bound", []) or [])
    for role in (profile.get("roles") or {}).values():
        for key in ("class_id", "lid_class_id"):
            if role.get(key):
                out.add(str(role[key]))
        out |= {str(v) for v in (role.get("state_class_ids") or {}).values()}
    return out


class Detector:
    def __init__(self, cfg: DetectorConfig, repo_root: Path,
                 required: Iterable[str] = ()) -> None:
        import numpy as np

        if not hasattr(np, "trapz"):  # ultralytics 8.3.28 + numpy 2 (see RESUME gotchas)
            np.trapz = np.trapezoid  # type: ignore[attr-defined]
        from ultralytics import YOLO

        path = Path(cfg.weights)
        if not path.is_absolute():
            path = repo_root / path
        if not path.is_file():
            raise FileNotFoundError(f"detector weights not found: {path}")
        self.cfg = cfg
        self.weights_path = path
        self._set_threads(cfg.threads)
        self._model = YOLO(str(path), task="obb")
        self.names: dict[int, str] = {int(k): str(v) for k, v in self._model.names.items()}
        missing = set(required) - set(self.names.values())
        if missing:
            raise DetectorClassMismatch(
                f"{path.name} does not provide class(es) {sorted(missing)} that the object "
                f"profile binds; it has {sorted(self.names.values())}. Retrain, or fix the "
                f"profile's class names."
            )
        self.last_inference_ms = 0.0
        if path.suffix.lower() == ".onnx":
            self._limit_onnx_threads(path, cfg.threads)
        # Warm-up: the first inference pays one-off costs (graph setup,
        # allocations) -- measured ~3 s. Pay them here, at startup, not on
        # the first camera frame.
        t0 = time.perf_counter()
        self.detect(np.zeros((cfg.imgsz, cfg.imgsz, 3), dtype=np.uint8))
        self.warmup_ms = 1000.0 * (time.perf_counter() - t0)

    def _limit_onnx_threads(self, path: Path, threads: int | None) -> None:
        """ONNX weights (see models/README.md): ultralytics 8.3.28 opens the
        onnxruntime session with default options, i.e. one worker per
        physical core, spinning -- the same every-core contention with the
        speech engine that made the first detection take 5.4 s with torch.
        Build the predictor, then swap in a session capped at the same
        thread count as torch (detector.threads)."""
        import numpy as np
        import onnxruntime as ort
        import torch

        self.detect(np.zeros((self.cfg.imgsz, self.cfg.imgsz, 3), dtype=np.uint8))  # builds the predictor
        backend = self._model.predictor.model
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = torch.get_num_threads()  # set by _set_threads from `threads`
        opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        if not getattr(backend, "dynamic", True):
            # static shape: ultralytics pre-binds its output tensors to the
            # session it made; re-bind the same tensors to ours
            io = session.io_binding()
            for out, y in zip(session.get_outputs(), backend.bindings):
                io.bind_output(name=out.name, device_type="cpu", device_id=0,
                               element_type=np.float16 if backend.fp16 else np.float32,
                               shape=tuple(y.shape), buffer_ptr=y.data_ptr())
            backend.io = io
        backend.session = session

    @staticmethod
    def _set_threads(threads: int | None) -> None:
        """Leave cores for capture, recording, speech and the GUI instead of
        letting torch claim every core (see src/runtime/tts.py)."""
        import os

        import torch

        if threads is None:
            try:
                import psutil

                cores = psutil.cpu_count(logical=False) or os.cpu_count() or 4
            except ImportError:
                cores = os.cpu_count() or 4
            threads = max(1, cores - 2)
        torch.set_num_threads(max(1, int(threads)))

    def detect(self, frame_bgr: Any) -> list[Detection]:
        t0 = time.perf_counter()
        res = self._model.predict(
            frame_bgr, imgsz=self.cfg.imgsz, conf=self.cfg.conf, iou=self.cfg.iou,
            device=self.cfg.device, verbose=False,
        )[0]
        self.last_inference_ms = 1000.0 * (time.perf_counter() - t0)
        obb = res.obb
        if obb is None or len(obb) == 0:
            return []
        xywhr = obb.xywhr.cpu().numpy()
        corners = obb.xyxyxyxy.cpu().numpy()
        confs = obb.conf.cpu().numpy()
        clss = obb.cls.cpu().numpy().astype(int)
        out = []
        for i in range(len(confs)):
            cx, cy, w, h, r = (float(v) for v in xywhr[i])
            pts = tuple((float(x), float(y)) for x, y in corners[i])
            out.append(Detection(
                cls=self.names[int(clss[i])], conf=float(confs[i]),
                cx=cx, cy=cy, w=w, h=h, angle_deg=math.degrees(r) % 180.0,
                corners=pts,  # type: ignore[arg-type]
            ))
        return out
