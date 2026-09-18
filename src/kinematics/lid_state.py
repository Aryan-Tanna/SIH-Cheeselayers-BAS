"""Lid state: closed / half_open / open, with hysteresis so a
measurement bouncing around a threshold doesn't chatter the state.

Must be lid_type-aware: a hinged lid rotates about an edge (measured as
an angle), a screw cap translates axially as it's unscrewed (measured
as a distance). Different maths, same public interface — callers never
branch on lid_type themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from src.protocol.debounce import Debouncer

LidState = Literal["closed", "half_open", "open"]
LidType = Literal["hinged", "screw"]


class LidMeasurer(Protocol):
    def state_for(self, value: float) -> LidState:
        """Raw (undebounced) state classification for one measurement."""
        ...


@dataclass(frozen=True, slots=True)
class HingedLidMeasurer:
    """value = lid angle in degrees, 0 = closed."""

    half_open_deg: float
    open_deg: float

    def state_for(self, value: float) -> LidState:
        if value >= self.open_deg:
            return "open"
        if value >= self.half_open_deg:
            return "half_open"
        return "closed"


@dataclass(frozen=True, slots=True)
class ScrewLidMeasurer:
    """value = axial travel in px (or mm, rack space), 0 = fully seated."""

    half_open_travel: float
    open_travel: float

    def state_for(self, value: float) -> LidState:
        if value >= self.open_travel:
            return "open"
        if value >= self.half_open_travel:
            return "half_open"
        return "closed"


def make_measurer(lid_type: LidType, **thresholds: float) -> LidMeasurer:
    if lid_type == "hinged":
        return HingedLidMeasurer(
            half_open_deg=thresholds["half_open_deg"],
            open_deg=thresholds["open_deg"],
        )
    if lid_type == "screw":
        return ScrewLidMeasurer(
            half_open_travel=thresholds["half_open_travel"],
            open_travel=thresholds["open_travel"],
        )
    raise ValueError(f"unknown lid_type: {lid_type!r}")


_STATE_RANK: dict[LidState, int] = {"closed": 0, "half_open": 1, "open": 2}


class LidStateTracker:
    """Hysteretic lid-state tracker for one lid. hysteresis_frames comes
    from configs/defaults.yaml `default_timing.lid_state_hysteresis_frames`
    (or a protocol override), never hardcoded here.
    """

    def __init__(self, measurer: LidMeasurer, hysteresis_frames: int) -> None:
        self.measurer = measurer
        # Reuse the generic debouncer per discrete transition: "at least
        # half_open" and "at least open" are each their own k-of-n gate,
        # so the tracker can only advance/retreat one rank at a time
        # without needing sustained agreement, which is what makes it
        # resistant to a single noisy frame without adding latency for
        # a real, sustained lid movement.
        self._at_least_half_open = Debouncer(k=hysteresis_frames, n=hysteresis_frames)
        self._at_least_open = Debouncer(k=hysteresis_frames, n=hysteresis_frames)
        self.current: LidState = "closed"

    def update(self, value: float) -> LidState:
        raw = self.measurer.state_for(value)
        half_open_ok, _ = self._at_least_half_open.update(
            "half_open", _STATE_RANK[raw] >= _STATE_RANK["half_open"]
        )
        open_ok, _ = self._at_least_open.update(
            "open", _STATE_RANK[raw] >= _STATE_RANK["open"]
        )
        if open_ok:
            self.current = "open"
        elif half_open_ok:
            self.current = "half_open"
        else:
            self.current = "closed"
        return self.current
