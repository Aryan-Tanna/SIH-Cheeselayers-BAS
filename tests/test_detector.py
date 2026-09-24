from pathlib import Path

import pytest

from src.perception.detector import Detection, DetectorConfig, required_classes
from src.protocol.loader import REPO_ROOT, load_yaml

PROFILES = ["profile_jar.yaml", "profile_rect.yaml", "profile_mixed.yaml"]


def test_required_classes_from_profiles():
    jar = required_classes(load_yaml(REPO_ROOT / "configs/objects/profile_jar.yaml"))
    assert {"case_open", "case_closed", "red_module", "yellow_module",
            "red_lid", "yellow_lid", "hand_bare", "hand_gloved"} == jar
    rect = required_classes(load_yaml(REPO_ROOT / "configs/objects/profile_rect.yaml"))
    assert "red_lid" not in rect and {"red_module", "yellow_module"} <= rect
    mixed = required_classes(load_yaml(REPO_ROOT / "configs/objects/profile_mixed.yaml"))
    assert "red_lid" in mixed and "yellow_lid" not in mixed
    assert required_classes(None) == set()


def test_detection_geometry():
    d = Detection("red_module", 0.9, 10, 20, 6, 8, 0.0,
                  ((7, 16), (13, 16), (13, 24), (7, 24)))
    assert d.radius == pytest.approx(5.0)
    assert d.aabb == (7, 16, 13, 24)


def test_config_from_runtime_yaml():
    from src.runtime.config import load_runtime_config

    c = DetectorConfig.from_config(load_runtime_config())
    assert c.weights.endswith(".pt") and 0 < c.conf < 1 and c.imgsz == 640


# --- real weights ------------------------------------------------------------------

def _weights():
    pytest.importorskip("ultralytics")
    from src.runtime.config import load_runtime_config

    c = DetectorConfig.from_config(load_runtime_config())
    if not (REPO_ROOT / c.weights).is_file():
        pytest.skip("weights not present")
    return c


@pytest.mark.parametrize("profile", PROFILES)
def test_committed_weights_cover_every_profile(profile):
    from src.perception.detector import Detector

    req = required_classes(load_yaml(REPO_ROOT / "configs/objects" / profile))
    det = Detector(_weights(), REPO_ROOT, required=req)
    assert req <= set(det.names.values())


def test_model_missing_a_profile_class_fails_loudly():
    from src.perception.detector import Detector, DetectorClassMismatch

    with pytest.raises(DetectorClassMismatch, match="blue_module"):
        Detector(_weights(), REPO_ROOT, required={"red_module", "blue_module"})


def test_missing_weights_file_fails_loudly(tmp_path):
    pytest.importorskip("ultralytics")
    from src.perception.detector import Detector

    with pytest.raises(FileNotFoundError):
        Detector(DetectorConfig(weights=str(tmp_path / "nope.pt")), REPO_ROOT)


def test_detect_returns_named_oriented_boxes_on_a_blank_frame():
    np = pytest.importorskip("numpy")
    from src.perception.detector import Detector

    det = Detector(_weights(), REPO_ROOT)
    out = det.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert isinstance(out, list)
    assert all(isinstance(d.cls, str) for d in out)
    assert det.last_inference_ms > 0
