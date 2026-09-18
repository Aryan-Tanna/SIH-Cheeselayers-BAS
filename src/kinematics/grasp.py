"""Grasp definition — distance alone is too weak (a hand resting near an
object is not grasping it). Grasp is:

    fingertips inside-or-near the object bbox
    AND
    coherent motion: object velocity correlates with hand velocity over
    a short window.

This one definition gives both grasp AND drift from the same underlying
signal (src/kinematics/drift.py): an object moving with no coherent hand
motion nearby, and no active grasp, is drifting rather than held.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.kinematics.motion import Sample, dot, norm, sub, velocity
from src.protocol.debounce import Debouncer


def bbox_contains_or_near(point: tuple[float, ...], bbox_center: tuple[float, ...], bbox_radius: float, margin: float) -> bool:
    dist = norm(sub(point, bbox_center))
    return dist <= (bbox_radius + margin)


def motion_coherence(hand_samples: list[Sample], object_samples: list[Sample]) -> float:
    """Cosine similarity of hand and object velocity over the current
    window, in [-1, 1]. 1.0 = moving in lockstep. Returns 0.0 (neutral,
    not coherent) if either is essentially stationary — a stationary
    object next to a stationary hand is ambiguous, not evidence of grasp.
    """
    v_hand = velocity(hand_samples)
    v_obj = velocity(object_samples)
    n_hand, n_obj = norm(v_hand), norm(v_obj)
    if n_hand < 1e-6 or n_obj < 1e-6:
        return 0.0
    return dot(v_hand, v_obj) / (n_hand * n_obj)


@dataclass(frozen=True, slots=True)
class GraspObservation:
    near: bool
    coherence: float


@dataclass(frozen=True, slots=True)
class GraspEvent:
    t: float
    kind: str  # "grasp_start" | "grasp_end"
    confidence: float


class GraspDetector:
    """Stateful, debounced grasp tracker for one (hand, object) pair.
    Emits grasp_start / grasp_end on confirmed transitions only.
    """

    def __init__(
        self,
        proximity_margin: float,
        coherence_threshold: float,
        k: int,
        n: int,
    ) -> None:
        self.proximity_margin = proximity_margin
        self.coherence_threshold = coherence_threshold
        self._debounce = Debouncer(k=k, n=n)
        self.active = False

    def update(
        self,
        t: float,
        hand_samples: list[Sample],
        object_samples: list[Sample],
        object_bbox_center: tuple[float, ...],
        object_bbox_radius: float,
    ) -> GraspEvent | None:
        if not hand_samples or not object_samples:
            near = False
            coherence = 0.0
        else:
            near = bbox_contains_or_near(
                hand_samples[-1].pos, object_bbox_center, object_bbox_radius, self.proximity_margin
            )
            coherence = motion_coherence(hand_samples, object_samples)

        raw = near and coherence >= self.coherence_threshold
        state, transitioned = self._debounce.update("grasp", raw)

        if not transitioned:
            return None

        confidence = min(1.0, max(0.0, (coherence + 1.0) / 2.0)) if near else 0.0
        if state and not self.active:
            self.active = True
            return GraspEvent(t=t, kind="grasp_start", confidence=confidence)
        if not state and self.active:
            self.active = False
            return GraspEvent(t=t, kind="grasp_end", confidence=confidence)
        return None
