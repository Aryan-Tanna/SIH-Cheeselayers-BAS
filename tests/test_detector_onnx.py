"""Torch-free ONNX detector backend (the packaged app has no torch):
numpy pre/post-processing mirrors ultralytics 8.3.28, so it returns what
ultralytics returns for the same .onnx (351 test_clips frames: identical)."""

import math
from pathlib import Path

import numpy as np
import pytest

from src.perception.detector import Detector, DetectorConfig, batch_probiou
from src.protocol.loader import REPO_ROOT

ONNX = REPO_ROOT / "models" / "bootstrap_v5_best.onnx"


def test_probiou_identity_and_disjoint():
    a = np.array([[100, 100, 40, 20, 0.3]], dtype=float)
    far = np.array([[400, 400, 40, 20, 0.3]], dtype=float)
    assert batch_probiou(a, a)[0, 0] == pytest.approx(1.0, abs=1e-3)
    assert batch_probiou(a, far)[0, 0] < 1e-3


def test_probiou_is_rotation_aware():
    long_x = np.array([[0, 0, 100, 10, 0.0]], dtype=float)
    long_y = np.array([[0, 0, 100, 10, math.pi / 2]], dtype=float)
    same = np.array([[0, 0, 10, 100, 0.0]], dtype=float)  # long_y written the other way
    assert batch_probiou(long_x, long_y)[0, 0] < 0.5
    assert batch_probiou(long_y, same)[0, 0] == pytest.approx(1.0, abs=1e-3)


def test_probiou_matches_ultralytics():
    metrics = pytest.importorskip("ultralytics.utils.metrics")
    rng = np.random.default_rng(0)
    boxes = np.column_stack([rng.uniform(0, 300, 20), rng.uniform(0, 300, 20),
                             rng.uniform(5, 80, 20), rng.uniform(5, 80, 20), rng.uniform(0, 3, 20)])
    ref = metrics.batch_probiou(boxes.astype(np.float32), boxes.astype(np.float32)).numpy()
    assert np.allclose(batch_probiou(boxes, boxes), ref, atol=1e-4)


@pytest.fixture(scope="module")
def onnx_det():
    pytest.importorskip("onnxruntime")
    pytest.importorskip("cv2")
    if not ONNX.is_file():
        pytest.skip("no exported .onnx")
    return Detector(DetectorConfig(str(ONNX.relative_to(REPO_ROOT))), REPO_ROOT)


def test_onnx_backend_loads_names_from_metadata(onnx_det):
    assert onnx_det.backend == "onnx"
    assert set(onnx_det.names.values()) >= {"case_open", "case_closed", "red_module", "red_lid",
                                              "yellow_module", "hand_bare"}
    assert onnx_det.warmup_ms < 2000


def test_letterbox_matches_the_export(onnx_det):
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    # static export: square 640 input; dynamic export: ultralytics' minimal
    # stride-32 rectangle (what the .pt path uses)
    want = (384, 640, 3) if onnx_det._onnx.dynamic else (640, 640, 3)
    assert onnx_det._onnx.letterbox(img, 640).shape == want


def test_blank_frame_has_no_detections(onnx_det):
    assert onnx_det.detect(np.full((720, 1280, 3), 114, np.uint8)) == []


def test_onnx_backend_matches_ultralytics_on_a_clip_frame(onnx_det):
    ultralytics = pytest.importorskip("ultralytics")
    import cv2

    clip = REPO_ROOT / "test_clips" / "train2.mp4"
    if not clip.is_file():
        pytest.skip("needs test_clips/train2.mp4")
    cap = cv2.VideoCapture(str(clip))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 270)  # ~9 s: jar open, lid in hand
    ok, img = cap.read()
    cap.release()
    assert ok
    if not hasattr(np, "trapz"):
        np.trapz = np.trapezoid
    res = ultralytics.YOLO(str(ONNX), task="obb").predict(img, imgsz=640, conf=0.25, iou=0.5,
                                                        verbose=False)[0].obb
    ref = sorted(zip(res.cls.numpy().astype(int), res.conf.numpy(), res.xyxyxyxy.numpy()),
                 key=lambda r: (int(r[0]), float(r[2][:, 0].mean())))
    got = sorted(onnx_det.detect(img), key=lambda d: (next(k for k, v in onnx_det.names.items()
                                                           if v == d.cls), d.cx))
    assert ref and [onnx_det.names[int(c)] for c, _, _ in ref] == [d.cls for d in got]
    pinned = ultralytics.__version__ == "8.3.28"  # other versions write w/h/angle differently
    for (_, conf, corners), d in zip(ref, got):
        assert abs(float(conf) - d.conf) < 1e-4
        # same physical box: corner sets agree whatever the w/h/angle convention
        assert np.allclose(sorted(map(tuple, corners)), sorted(d.corners), atol=0.5)
    if pinned:
        assert all(d.w >= d.h for d in got)  # regularize_rboxes: w is the long side


def test_weights_suffix_selects_backend(tmp_path):
    with pytest.raises(FileNotFoundError):
        Detector(DetectorConfig(str(tmp_path / "missing.onnx")), Path("."))
