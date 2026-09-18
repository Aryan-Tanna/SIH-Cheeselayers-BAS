"""Clock abstraction.

Every time-driven subsystem (debounce k-of-n, alert cooldowns, timeout
constraints) takes a Clock instead of calling time.monotonic() directly.
That is what lets harness/replay.py run a whole clip's worth of protocol
logic in milliseconds, driven off fixture timestamps, instead of sleeping
in real time — and what makes a replay deterministic and repeatable.

Never call time.monotonic() from src/protocol, src/logging, or harness.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds, monotonic. Not wall-clock time."""
        ...


class SystemClock:
    """Real clock for live runtime use."""

    def now(self) -> float:
        return time.monotonic()


class VirtualClock:
    """Deterministic clock for tests and replay.

    Time only moves forward, driven explicitly by the caller (typically
    from a fixture's or detection stream's `t` field). This is what lets
    replay run faster than real time.
    """

    def __init__(self, t0: float = 0.0) -> None:
        self._t = t0

    def now(self) -> float:
        return self._t

    def advance_to(self, t: float) -> None:
        if t < self._t:
            raise ValueError(f"VirtualClock cannot move backward: {t} < {self._t}")
        self._t = t

    def advance_by(self, dt: float) -> None:
        if dt < 0:
            raise ValueError(f"VirtualClock cannot move backward: dt={dt}")
        self._t += dt
