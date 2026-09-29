"""Object detector: YOLO-OBB weights -> per-frame oriented detections.

Weights come from configs/runtime.yaml (detector.weights), so a new
model (v5, ...) is a one-line swap. What makes that swap SAFE is that
nothing downstream uses class *numbers*: detections carry class NAMES,
and at load the model's names are checked against the classes the
object profile binds. A model that renamed or dropped a class fails at
startup with the missing names, instead of silently never seeing that
object mid-experiment. Confidence / IoU / image size are config too --
a new model may need them re-tuned, never code.

Two backends, picked by the weights file's suffix:
* .pt   -- ultralytics + torch (the training environment).
* .onnx -- onnxruntime + numpy only (_OnnxObb). Its pre/post-processing
  reproduces ultralytics 8.3.28's OBB predict (letterbox, best-class
  filter, class-offset probiou fast-NMS, regularize_rboxes, scale_boxes +
  clip_boxes): identical detections to ultralytics running the same .onnx
  on 351 test_clips frames (conf and corner difference 0). It keeps torch
  and ultralytics (~1 GB) out of the packaged app (scripts/build_app.py);
  onnxruntime is already there for the speech engine.

ultralytics/torch/onnxruntime are imported lazily (optional extras).
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
    threads: int | None = None  # detector CPU threads; None = physical cores - 2

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


def _default_threads() -> int:
    """Physical cores - 2: leave cores for capture, recording, speech and
    the GUI (see src/runtime/tts.py)."""
    import os

    try:
        import psutil

        cores = psutil.cpu_count(logical=False) or os.cpu_count() or 4
    except ImportError:
        cores = os.cpu_count() or 4
    return max(1, cores - 2)


class Detector:
    def __init__(self, cfg: DetectorConfig, repo_root: Path,
                 required: Iterable[str] = ()) -> None:
        import numpy as np

        path = Path(cfg.weights)
        if not path.is_absolute():
            path = repo_root / path
        if not path.is_file():
            raise FileNotFoundError(f"detector weights not found: {path}")
        self.cfg = cfg
        self.weights_path = path
        self.backend = "onnx" if path.suffix.lower() == ".onnx" else "torch"
        if self.backend == "onnx":
            self._onnx = _OnnxObb(path, cfg.threads or _default_threads())
            self.names: dict[int, str] = dict(self._onnx.names)
        else:
            if not hasattr(np, "trapz"):  # ultralytics 8.3.28 + numpy 2 (see RESUME gotchas)
                np.trapz = np.trapezoid  # type: ignore[attr-defined]
            from ultralytics import YOLO

            self._set_threads(cfg.threads)
            self._model = YOLO(str(path), task="obb")
            self.names = {int(k): str(v) for k, v in self._model.names.items()}
        missing = set(required) - set(self.names.values())
        if missing:
            raise DetectorClassMismatch(
                f"{path.name} does not provide class(es) {sorted(missing)} that the object "
                f"profile binds; it has {sorted(self.names.values())}. Retrain, or fix the "
                f"profile's class names."
            )
        self.last_inference_ms = 0.0
        # Warm-up: the first inference pays one-off costs (graph setup,
        # allocations) -- measured ~3 s. Pay them here, at startup, not on
        # the first camera frame.
        t0 = time.perf_counter()
        self.detect(np.zeros((cfg.imgsz, cfg.imgsz, 3), dtype=np.uint8))
        self.warmup_ms = 1000.0 * (time.perf_counter() - t0)

    @staticmethod
    def _set_threads(threads: int | None) -> None:
        """Leave cores for capture, recording, speech and the GUI instead of
        letting torch claim every core (see src/runtime/tts.py)."""
        import torch

        torch.set_num_threads(max(1, int(threads or _default_threads())))

    def detect(self, frame_bgr: Any) -> list[Detection]:
        t0 = time.perf_counter()
        if self.backend == "onnx":
            rows = self._onnx.predict(frame_bgr, self.cfg.imgsz, self.cfg.conf, self.cfg.iou)
            self.last_inference_ms = 1000.0 * (time.perf_counter() - t0)
            return [Detection(cls=self.names[c], conf=conf, cx=cx, cy=cy, w=w, h=h,
                              angle_deg=math.degrees(r) % 180.0, corners=pts)
                    for cx, cy, w, h, r, conf, c, pts in rows]
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


class _OnnxObb:
    """YOLO-OBB ONNX export on onnxruntime, numpy-only post-processing
    mirroring ultralytics 8.3.28 (ops.non_max_suppression(rotated=True),
    nms_rotated, batch_probiou, regularize_rboxes, scale_boxes)."""

    MAX_NMS, MAX_DET, MAX_WH = 30000, 300, 7680

    def __init__(self, path: Path, threads: int) -> None:
        import ast

        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(threads))
        opts.inter_op_num_threads = 1
        # idle workers sleep instead of spinning: spinning between frames
        # starves capture, recording, speech and the GUI (a torch detector
        # beside a spinning session went 56 -> 295 ms/frame)
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        if meta.get("task", "obb") != "obb" or "names" not in meta:
            raise ValueError(f"{path.name} is not an ultralytics OBB export (task={meta.get('task')})")
        self.names = {int(k): str(v) for k, v in ast.literal_eval(meta["names"]).items()}
        self.stride = int(meta.get("stride", 32))
        shape = self.session.get_inputs()[0].shape
        # dynamic export -> rect letterbox like the .pt path; fixed -> square
        self.dynamic = not all(isinstance(d, int) for d in shape[2:])
        self.input = self.session.get_inputs()[0].name

    def letterbox(self, img: Any, imgsz: int) -> Any:
        import cv2
        import numpy as np

        h, w = img.shape[:2]
        r = min(imgsz / h, imgsz / w)
        new_w, new_h = int(round(w * r)), int(round(h * r))
        dw, dh = imgsz - new_w, imgsz - new_h
        if self.dynamic:
            dw, dh = np.mod(dw, self.stride), np.mod(dh, self.stride)
        dw, dh = dw / 2, dh / 2
        if (w, h) != (new_w, new_h):
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        return cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT,
                                  value=(114, 114, 114))

    def predict(self, frame_bgr: Any, imgsz: int, conf: float, iou: float) -> list[tuple]:
        """-> [(cx, cy, w, h, r_rad, conf, class_index, corners)] in frame pixels."""
        import numpy as np

        img = self.letterbox(frame_bgr, imgsz)
        x = np.ascontiguousarray(img[..., ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        pred = self.session.run(None, {self.input: x})[0][0].T  # (anchors, 4 + nc + 1)
        nc = len(self.names)
        scores = pred[:, 4:4 + nc]
        best = scores.max(1)
        keep = best > conf
        pred, scores, best = pred[keep], scores[keep], best[keep]
        if not len(pred):
            return []
        cls = scores.argmax(1)
        if len(pred) > self.MAX_NMS:
            top = np.argsort(-best, kind="stable")[:self.MAX_NMS]
            pred, best, cls = pred[top], best[top], cls[top]
        # batched NMS: offset centres by class so classes never suppress each other
        boxes = np.concatenate([pred[:, :2] + cls[:, None] * self.MAX_WH, pred[:, 2:4], pred[:, -1:]], 1)
        order = np.argsort(-best, kind="stable")
        ious = np.triu(batch_probiou(boxes[order], boxes[order]), 1)
        picked = order[ious.max(0) < iou][:self.MAX_DET]
        h0, w0 = frame_bgr.shape[:2]
        h1, w1 = img.shape[:2]
        gain = min(h1 / h0, w1 / w0)
        padx = round((w1 - w0 * gain) / 2 - 0.1)
        pady = round((h1 - h0 * gain) / 2 - 0.1)
        out = []
        for i in picked:
            cx, cy, w, h, r = (float(v) for v in (*pred[i, :4], pred[i, -1]))
            if not w > h:  # regularize_rboxes
                w, h, r = h, w, r + math.pi / 2
            r %= math.pi
            cx, cy, w, h = (cx - padx) / gain, (cy - pady) / gain, w / gain, h / gain
            # clip_boxes on xywh, exactly as ultralytics applies it
            cx, w = min(max(cx, 0.0), w0), min(max(w, 0.0), w0)
            cy, h = min(max(cy, 0.0), h0), min(max(h, 0.0), h0)
            c, s = math.cos(r), math.sin(r)
            v1x, v1y = w / 2 * c, w / 2 * s
            v2x, v2y = -h / 2 * s, h / 2 * c
            pts = ((cx + v1x + v2x, cy + v1y + v2y), (cx + v1x - v2x, cy + v1y - v2y),
                   (cx - v1x - v2x, cy - v1y - v2y), (cx - v1x + v2x, cy - v1y + v2y))
            out.append((cx, cy, w, h, r, float(best[i]), int(cls[i]), pts))
        return out


def batch_probiou(obb1: Any, obb2: Any, eps: float = 1e-7) -> Any:
    """Probabilistic IoU between (N,5) and (M,5) xywhr boxes -> (N,M);
    ultralytics.utils.metrics.batch_probiou in numpy."""
    import numpy as np

    def cov(b):
        a, bb, t = b[:, 2] ** 2 / 12, b[:, 3] ** 2 / 12, b[:, 4]
        cs, sn = np.cos(t), np.sin(t)
        return a * cs ** 2 + bb * sn ** 2, a * sn ** 2 + bb * cs ** 2, (a - bb) * cs * sn

    x1, y1 = obb1[:, 0:1], obb1[:, 1:2]
    x2, y2 = obb2[None, :, 0], obb2[None, :, 1]
    a1, b1, c1 = (v[:, None] for v in cov(obb1))
    a2, b2, c2 = (v[None] for v in cov(obb2))
    den = (a1 + a2) * (b1 + b2) - (c1 + c2) ** 2 + eps
    t1 = ((a1 + a2) * (y1 - y2) ** 2 + (b1 + b2) * (x1 - x2) ** 2) / den * 0.25
    t2 = ((c1 + c2) * (x2 - x1) * (y1 - y2)) / den * 0.5
    t3 = np.log(((a1 + a2) * (b1 + b2) - (c1 + c2) ** 2)
                / (4 * np.sqrt(np.clip(a1 * b1 - c1 ** 2, 0, None) * np.clip(a2 * b2 - c2 ** 2, 0, None)) + eps)
                + eps) * 0.5
    bd = np.clip(t1 + t2 + t3, eps, 100.0)
    hd = np.sqrt(1.0 - np.exp(-bd) + eps)
    return 1 - hd
