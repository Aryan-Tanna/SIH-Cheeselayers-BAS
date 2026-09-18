"""Drift = non-zero rack-space velocity with no hand in grasp range and no
active grasp.

Needs guardrails or it false-positives constantly on ordinary noise and
on objects settling after being placed:

  * minimum displacement over the observation window (kills jitter)
  * gate on track continuity — only VISIBLE tracks count
  * N consecutive confirming frames (debounced, not single-frame)
  * exclude LEFT_FRAME explicitly — an object that left frame is not
    drifting, it's gone; conflating the two causes phantom drift alerts
    every time something exits frame (see src/kinematics/tracker.py).
"""

from __future__ import annotations

from src.kinematics.motion import Sample, norm, sub
from src.kinematics.tracker import TrackState
from src.protocol.debounce import Debouncer


class DriftDetector:
    def __init__(
        self,
        min_displacement: float,
        min_speed: float,
        n_consecutive: int,
    ) -> None:
        if n_consecutive < 1:
            raise ValueError("n_consecutive must be >= 1")
        self.min_displacement = min_displacement
        self.min_speed = min_speed
        self._debounce = Debouncer(k=n_consecutive, n=n_consecutive)

    def update(
        self,
        object_id: str,
        samples: list[Sample],
        track_state: TrackState,
        hand_in_grasp_range: bool,
        grasp_active: bool,
    ) -> bool:
        """Returns True exactly on the confirmed transition into drifting."""
        raw = self._raw_drift_signal(samples, track_state, hand_in_grasp_range, grasp_active)
        state, transitioned = self._debounce.update(object_id, raw)
        return transitioned and state

    def _raw_drift_signal(
        self,
        samples: list[Sample],
        track_state: TrackState,
        hand_in_grasp_range: bool,
        grasp_active: bool,
    ) -> bool:
        if track_state in (TrackState.LEFT_FRAME, TrackState.OCCLUDED):
            return False
        if hand_in_grasp_range or grasp_active:
            return False
        if len(samples) < 2:
            return False

        displacement = norm(sub(samples[-1].pos, samples[0].pos))
        if displacement < self.min_displacement:
            return False

        dt = max(samples[-1].t - samples[-2].t, 1e-6)
        speed = norm(sub(samples[-1].pos, samples[-2].pos)) / dt
        return speed >= self.min_speed
