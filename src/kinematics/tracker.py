"""Object tracker interface only — no implementation in phase 0 (there is
no video to track). Concrete trackers (perception/) implement this once
clips land.

Required states, and why LEFT_FRAME must be distinct from OCCLUDED:
an object sliding behind another object is OCCLUDED — it is still where
physics predicts and should not be flagged as drifting or lost. An
object that has left the frame entirely has no position to reason about
at all; treating it as OCCLUDED (i.e. "still tracked, just hidden") is
exactly what produces phantom drift alerts the instant something exits
frame, since a naive tracker would keep predicting motion for it.
DRIFTING is a distinct state (not just a flag) so it participates in
state-machine transitions the same way VISIBLE/OCCLUDED do.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class TrackState(Enum):
    VISIBLE = "visible"
    OCCLUDED = "occluded"
    LEFT_FRAME = "left_frame"
    DRIFTING = "drifting"


class ObjectTracker(Protocol):
    """One instance per tracked object (a role instance, e.g. module_a)."""

    def update(self, t: float, detection: dict[str, Any] | None) -> TrackState:
        """Feed one frame's detection (or None if nothing matched this
        frame) and get back the current track state."""
        ...

    def state(self) -> TrackState:
        ...

    def last_position(self) -> tuple[float, ...] | None:
        ...
