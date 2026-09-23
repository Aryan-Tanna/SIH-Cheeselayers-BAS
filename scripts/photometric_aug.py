#!/usr/bin/env python3
"""Pixel-only training augmentations (blur, contrast, sharpness, noise,
JPEG) for YOLOv8-OBB, done with cv2/numpy only.

Stands in for Ultralytics' Albumentations hook: that hook's defaults are
p=0.01 (effectively off) and the albumentations package depends on
opencv-python-headless, which clobbers opencv-contrib and breaks
cv2.aruco (see pyproject.toml). Every transform here changes pixels
only, never geometry, so OBB labels pass through untouched.

Probabilities and ranges come from configs/training/*.yaml -> photometric.
"""

from __future__ import annotations

import os
import random
from typing import Any

import cv2
import numpy as np


def _odd(lo: int, hi: int, rng: random.Random) -> int:
    k = rng.randint(lo, hi)
    return k if k % 2 else k + 1


def motion_blur(img: np.ndarray, kernel: list[int], rng: random.Random) -> np.ndarray:
    k = _odd(*kernel, rng)
    kern = np.zeros((k, k), np.float32)
    kern[k // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((k / 2 - 0.5, k / 2 - 0.5), rng.uniform(0, 180), 1.0)
    kern = cv2.warpAffine(kern, rot, (k, k))
    kern /= max(kern.sum(), 1e-6)
    return cv2.filter2D(img, -1, kern)


def gaussian_blur(img: np.ndarray, kernel: list[int], rng: random.Random) -> np.ndarray:
    k = _odd(*kernel, rng)
    return cv2.GaussianBlur(img, (k, k), 0)


def brightness_contrast(img: np.ndarray, brightness: float, contrast: float,
                        rng: random.Random) -> np.ndarray:
    alpha = 1.0 + rng.uniform(-contrast, contrast)
    beta = 255.0 * rng.uniform(-brightness, brightness)
    return cv2.convertScaleAbs(img, alpha=alpha, beta=beta)


def clahe(img: np.ndarray, clip_limit: list[float], rng: random.Random) -> np.ndarray:
    # Luminance only, so hue (our class signal) is untouched.
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    op = cv2.createCLAHE(clipLimit=rng.uniform(*clip_limit), tileGridSize=(8, 8))
    lab[..., 0] = op.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def sharpen(img: np.ndarray, alpha: list[float], rng: random.Random) -> np.ndarray:
    a = rng.uniform(*alpha)
    blurred = cv2.GaussianBlur(img, (0, 0), 3)
    return cv2.addWeighted(img, 1 + a, blurred, -a, 0)


def gaussian_noise(img: np.ndarray, sigma: list[float], rng: random.Random) -> np.ndarray:
    s = rng.uniform(*sigma)
    noise = np.random.default_rng(rng.getrandbits(32)).normal(0, s, img.shape)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, quality: list[int], rng: random.Random) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(*quality)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img


TRANSFORMS = {
    "motion_blur": motion_blur,
    "gaussian_blur": gaussian_blur,
    "brightness_contrast": brightness_contrast,
    "clahe": clahe,
    "sharpen": sharpen,
    "gaussian_noise": gaussian_noise,
    "jpeg": jpeg,
}


def apply_photometric(img: np.ndarray, cfg: dict[str, dict[str, Any]],
                      rng: random.Random) -> np.ndarray:
    """Apply each configured transform independently with its own p."""
    for name, params in cfg.items():
        if name not in TRANSFORMS:
            raise ValueError(f"unknown photometric transform '{name}' "
                             f"(known: {sorted(TRANSFORMS)})")
        params = dict(params)
        p = params.pop("p")
        if rng.random() < p:
            img = TRANSFORMS[name](img, rng=rng, **params)
    return img


class PhotometricAugment:
    """Drop-in for ultralytics.data.augment.Albumentations: same
    (labels dict -> labels dict) call contract, image only."""

    cfg: dict[str, dict[str, Any]] = {}

    def __init__(self, p: float = 1.0) -> None:
        self.p = p
        # Copied onto the instance so it survives pickling into dataloader
        # worker processes (Windows spawns them; class attrs set by
        # install() would be empty there).
        self.cfg = dict(PhotometricAugment.cfg)
        self.rng = random.Random()
        self._pid = os.getpid()

    def __call__(self, labels: dict) -> dict:
        if os.getpid() != self._pid:
            # Pickled into a worker: reseed, or every worker replays the
            # same random stream.
            self.rng, self._pid = random.Random(), os.getpid()
        if self.cfg and self.rng.random() <= self.p:
            labels["img"] = apply_photometric(labels["img"], self.cfg, self.rng)
        return labels


def install(cfg: dict[str, dict[str, Any]]) -> None:
    """Swap Ultralytics' Albumentations hook for PhotometricAugment.
    v8_transforms() looks the class up by module global at call time, so
    this must run before model.train() builds the dataset (and with
    workers=0, or before workers fork)."""
    for name in cfg:
        if name not in TRANSFORMS:
            raise ValueError(f"unknown photometric transform '{name}'")
    import ultralytics.data.augment as ua
    PhotometricAugment.cfg = cfg
    ua.Albumentations = PhotometricAugment
