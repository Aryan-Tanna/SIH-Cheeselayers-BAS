"""OBB -> point-kinematics reduction.

src/kinematics/ never consumes a raw detector box — every function there
was written against an already-reduced centroid point plus, in grasp.py,
a single circumscribing radius (src/kinematics/grasp.py:76-77). This
module is that reduction: a Label-Studio-style oriented box becomes
(centroid, radius, rotation_deg), computed once here so grasp/tracker/
lid_state never have to know a box was ever rotated.

Label Studio export format: x, y, width, height, rotation (degrees).
(x, y) is the box's TOP-LEFT corner *before* rotation is applied — the
box rotates about that corner, not about its own center. Computing
centroid as (x + width/2, y + height/2) ignores this pivot and is only
correct at rotation == 0; for any rotated box it silently returns the
wrong point. Always rotate the four corners about (x, y) first, then
average — never shortcut to the naive formula.

Rotation direction: Label Studio rotates clockwise, in image coordinates
(x right, y down). The textbook counter-clockwise rotation matrix,
applied in an x-right/y-down frame, produces a visually clockwise turn —
so the "CCW" formula below is the one that matches LS's convention. This
has not yet been cross-checked against a real Label Studio export; do
that once the friends' packs come back before trusting it past the unit
tests here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ReducedBox:
    """Centroid + circumscribing radius for src/kinematics, plus the
    source rotation. grasp.py and lid_state.py don't consume
    rotation_deg today — it's kept on the output as a free input for a
    future geometric wrong_orientation check, not thrown away here.
    """

    centroid: Point
    radius: float
    rotation_deg: float


def _rotate_cw(dx: float, dy: float, theta_rad: float) -> Point:
    """Rotate (dx, dy) about the origin by theta_rad, clockwise, in
    image coordinates (x right, y down)."""
    cos_t, sin_t = math.cos(theta_rad), math.sin(theta_rad)
    return (dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t)


def obb_to_reduced(
    x: float, y: float, width: float, height: float, rotation_deg: float
) -> ReducedBox:
    """Reduce one oriented box to the centroid/radius pair
    src/kinematics expects.

    x, y, width, height: caller's units in, same units out (px or
    rack-space mm) — this function does no unit conversion.
    rotation_deg: clockwise degrees, box rotates about (x, y).
    """
    theta = math.radians(rotation_deg)
    corners_rel = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
    rotated = [_rotate_cw(dx, dy, theta) for dx, dy in corners_rel]
    cx = x + sum(p[0] for p in rotated) / 4.0
    cy = y + sum(p[1] for p in rotated) / 4.0
    radius = math.hypot(width / 2.0, height / 2.0)
    return ReducedBox(centroid=(cx, cy), radius=radius, rotation_deg=rotation_deg % 360.0)
