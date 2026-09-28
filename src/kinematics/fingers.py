"""Grasp and reach from hand landmarks (MediaPipe's 21-point hand model).
Pure functions + small debounced trackers: unit-testable with synthetic
landmark tracks, no video.

Why landmarks and not the detector's hand box: from the top-down camera a
hand box is ~2.4x the jar and overlaps it in every frame the jar is
visible (measured 2026-09-28), so "near the jar" says nothing. Fingertips
inside the jar's box, and the palm closing in on it, do.

Everything is measured in HAND SCALES (wrist -> middle-finger knuckle), so
the thresholds hold at any camera distance or resolution, and in any
orientation (no up/down assumed: microgravity).

Landmark indices (MediaPipe): 0 wrist, 4 thumb tip, 8 index tip, 12 middle
tip, 16 ring tip, 20 pinky tip; 5/9/13/17 the finger knuckles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.protocol.debounce import Debouncer

Point = tuple[float, float]
Box = tuple[float, float, float, float]  # x0, y0, x1, y1

WRIST, THUMB_TIP, INDEX_TIP = 0, 4, 8
TIPS = (4, 8, 12, 16, 20)
PALM = (0, 5, 9, 13, 17)


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def hand_scale(lm: list[Point]) -> float:
    """Wrist to middle-finger knuckle: stable while the fingers move."""
    return max(_dist(lm[WRIST], lm[9]), 1e-6)


def palm_centre(lm: list[Point]) -> Point:
    xs = [lm[i][0] for i in PALM]
    ys = [lm[i][1] for i in PALM]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def aperture(lm: list[Point]) -> float:
    """Thumb tip to index tip, in hand scales: opens while reaching,
    closes on the object."""
    return _dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hand_scale(lm)


def grow(box: Box, frac: float) -> Box:
    gx, gy = (box[2] - box[0]) * frac, (box[3] - box[1]) * frac
    return (box[0] - gx, box[1] - gy, box[2] + gx, box[3] + gy)


def inside(p: Point, box: Box) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def contact(lm: list[Point], box: Box, grow_frac: float = 0.1) -> bool:
    """Thumb tip AND at least one other fingertip on the object: a pinch
    or a wrap. A palm merely hovering above the object does not count."""
    b = grow(box, grow_frac)
    return inside(lm[THUMB_TIP], b) and any(inside(lm[i], b) for i in TIPS[1:])


def distance_scales(lm: list[Point], box: Box) -> float:
    """Palm centre to the object's box edge (0 inside), in hand scales."""
    p = palm_centre(lm)
    dx = max(box[0] - p[0], 0.0, p[0] - box[2])
    dy = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.hypot(dx, dy) / hand_scale(lm)


def approach_speed(track: list[tuple[float, float]]) -> float | None:
    """Closing speed in hand scales per second (positive = approaching),
    least-squares over the track; None with fewer than 3 samples."""
    if len(track) < 3:
        return None
    t0 = track[0][0]
    ts = [t - t0 for t, _ in track]
    ds = [d for _, d in track]
    n = len(ts)
    mt, md = sum(ts) / n, sum(ds) / n
    var = sum((t - mt) ** 2 for t in ts)
    if var <= 0:
        return None
    return -sum((t - mt) * (d - md) for t, d in zip(ts, ds)) / var


def time_to_contact(track: list[tuple[float, float]]) -> float | None:
    """track: (t, distance in hand scales) samples, oldest first. Linear fit
    of the approach; seconds until the distance reaches 0, or None if the
    hand is not closing in."""
    if len(track) < 3:
        return None
    t0 = track[0][0]
    ts = [t - t0 for t, _ in track]
    ds = [d for _, d in track]
    n = len(ts)
    mt, md = sum(ts) / n, sum(ds) / n
    var = sum((t - mt) ** 2 for t in ts)
    if var <= 0:
        return None
    slope = sum((t - mt) * (d - md) for t, d in zip(ts, ds)) / var  # scales per second
    if slope >= 0:
        return None
    return max(0.0, ds[-1] / -slope)


@dataclass
class HandObjectState:
    grasping: bool = False
    reaching: bool = False
    eta_s: float | None = None  # predicted time to contact while reaching


class FingerGrasp:
    """Per (hand, object) pair: debounced contact = grasp, and a debounced
    reach prediction: the palm closing in on the object with contact due
    within `horizon_s`, from further than `min_distance` hand scales away
    (closer than that, 'reaching' and 'already there' are the same)."""

    def __init__(self, grasp_k: int = 2, grasp_n: int = 3, reach_k: int = 2, reach_n: int = 3,
                 horizon_s: float = 1.5, window_s: float = 0.6, min_distance: float = 0.3,
                 max_distance: float = 6.0, min_speed: float = 0.0) -> None:
        self.horizon_s = horizon_s
        self.min_speed = min_speed
        self.window_s = window_s
        self.min_distance = min_distance
        self.max_distance = max_distance
        self._grasp = Debouncer(k=grasp_k, n=grasp_n)
        self._reach = Debouncer(k=reach_k, n=reach_n)
        self._track: dict[object, list[tuple[float, float]]] = {}

    def update(self, key: object, ts: float, lm: list[Point] | None, box: Box | None) -> HandObjectState:
        if lm is None or box is None:
            self._track.pop(key, None)
            g, _ = self._grasp.update(key, False)
            r, _ = self._reach.update(key, False)
            return HandObjectState(grasping=g, reaching=False)
        d = distance_scales(lm, box)
        tr = self._track.setdefault(key, [])
        tr.append((ts, d))
        while tr and ts - tr[0][0] > self.window_s:
            tr.pop(0)
        touching = contact(lm, box)
        g, _ = self._grasp.update(key, touching)
        eta = None if touching else time_to_contact(tr)
        speed = approach_speed(tr) if eta is not None else None
        raw = (eta is not None and eta <= self.horizon_s and self.min_distance < d <= self.max_distance
               and speed is not None and speed >= self.min_speed)
        r, _ = self._reach.update(key, raw)
        return HandObjectState(grasping=g, reaching=r and not g, eta_s=eta if r and not g else None)
