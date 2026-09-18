"""Intent projection — a soft cue, never a hard alert on its own.

Naive linear extrapolation of hand velocity false-alarms constantly:
reaching past one module to get another is a completely normal
trajectory that a linear projection reads as "heading for the wrong
object." This module deliberately makes intent weak evidence:

  * project ~300ms ahead, not further (short enough that trajectory
    curvature hasn't had time to matter yet)
  * use an angular cone around the object, not a point/line target
  * require k-of-n agreement across frames before intent is "confirmed"
  * hysteresis so a momentary wobble doesn't cancel confirmed intent
  * a hard alert (wrong_object) only fires on actual contact, evaluated
    by src/protocol/engine.py from a real ActionEvent — this module's
    output is only ever a candidate/advisory signal for the GUI to show
    "may be reaching for X", never something the engine treats as fact.
"""

from __future__ import annotations

import math

from src.kinematics.motion import Sample, add, norm, scale, sub, velocity
from src.protocol.debounce import Debouncer


def project_position(samples: list[Sample], horizon_s: float = 0.3) -> tuple[float, ...] | None:
    if len(samples) < 2:
        return None
    v = velocity(samples)
    return add(samples[-1].pos, scale(v, horizon_s))


def within_cone(
    hand_pos: tuple[float, ...],
    projected_pos: tuple[float, ...],
    object_pos: tuple[float, ...],
    half_angle_deg: float,
) -> bool:
    """True if `object_pos`, viewed from `hand_pos`, falls within a cone
    of half-angle `half_angle_deg` around the direction to `projected_pos`."""
    to_projected = sub(projected_pos, hand_pos)
    to_object = sub(object_pos, hand_pos)
    n1, n2 = norm(to_projected), norm(to_object)
    if n1 < 1e-9 or n2 < 1e-9:
        return False
    cos_theta = max(-1.0, min(1.0, sum(a * b for a, b in zip(to_projected, to_object)) / (n1 * n2)))
    angle_deg = math.degrees(math.acos(cos_theta))
    return angle_deg <= half_angle_deg


class IntentTracker:
    """Debounced, hysteretic per-object intent confirmation."""

    def __init__(self, k: int, n: int, half_angle_deg: float, horizon_s: float = 0.3) -> None:
        self.half_angle_deg = half_angle_deg
        self.horizon_s = horizon_s
        self._debounce = Debouncer(k=k, n=n)

    def update(
        self,
        object_id: str,
        hand_samples: list[Sample],
        object_pos: tuple[float, ...],
    ) -> bool:
        """Returns the confirmed (debounced) intent-toward-object state."""
        projected = project_position(hand_samples, self.horizon_s)
        raw = (
            projected is not None
            and within_cone(hand_samples[-1].pos, projected, object_pos, self.half_angle_deg)
        )
        state, _ = self._debounce.update(object_id, raw)
        return state
