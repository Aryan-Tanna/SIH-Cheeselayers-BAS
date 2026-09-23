import random

import numpy as np
import pytest
import yaml

from scripts.photometric_aug import TRANSFORMS, PhotometricAugment, apply_photometric


def _img(seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (64, 96, 3), dtype=np.uint8)


def _all_on() -> dict:
    cfg = yaml.safe_load(open("configs/training/augment_v4.yaml", encoding="utf-8"))["photometric"]
    return {k: {**v, "p": 1.0} for k, v in cfg.items()}


def test_config_names_all_known():
    cfg = yaml.safe_load(open("configs/training/augment_v4.yaml", encoding="utf-8"))
    assert set(cfg["photometric"]) <= set(TRANSFORMS)


def test_config_keeps_hue_small_and_no_grayscale():
    # red vs yellow classes are colour-only; guard against someone cranking hue
    cfg = yaml.safe_load(open("configs/training/augment_v4.yaml", encoding="utf-8"))
    assert cfg["ultralytics"]["hsv_h"] <= 0.02
    assert not any("gray" in k for k in cfg["photometric"])


@pytest.mark.parametrize("name", sorted(TRANSFORMS))
def test_each_transform_preserves_shape_and_dtype(name):
    cfg = {name: _all_on()[name]}
    out = apply_photometric(_img(), cfg, random.Random(1))
    assert out.shape == (64, 96, 3) and out.dtype == np.uint8


def test_p_zero_is_identity():
    cfg = {k: {**v, "p": 0.0} for k, v in _all_on().items()}
    img = _img()
    assert np.array_equal(apply_photometric(img.copy(), cfg, random.Random(1)), img)


def test_unknown_transform_rejected():
    with pytest.raises(ValueError):
        apply_photometric(_img(), {"to_gray": {"p": 1.0}}, random.Random(1))


def test_hook_changes_image_only_not_labels():
    PhotometricAugment.cfg = _all_on()
    try:
        cls = np.array([[2.0]])
        sentinel = object()
        labels = {"img": _img(), "cls": cls, "instances": sentinel}
        out = PhotometricAugment(p=1.0)(labels)
        assert out["cls"] is cls and out["instances"] is sentinel
        assert not np.array_equal(out["img"], _img())
    finally:
        PhotometricAugment.cfg = {}
