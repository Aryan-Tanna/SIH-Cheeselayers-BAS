"""k-of-n frame agreement before any state transition.

Raw per-frame detections/predicates are far too noisy to drive a state
machine directly — a single dropped or spurious frame would otherwise
fire a spurious step completion or violation. This module is the single
place that turns a noisy boolean-per-frame stream into a debounced,
confirmed boolean-per-key stream.

Deliberately dependency-free and clock-free: it only counts calls, so it
is trivial to unit test and trivial to drive from either live frames or
a replay stream at any speed.
"""

from __future__ import annotations

from collections import deque
from typing import Hashable


class Debouncer:
    """Per-key k-of-n majority filter.

    For each key, keeps the last `n` observations and reports the
    debounced state as True once at least `k` of the last `n` are True,
    False once at least `k` of the last `n` are False. `update()` returns
    the debounced state AFTER incorporating the new observation, and
    `transitioned` tells you whether that debounced state just changed
    from what it was before this call — that's the signal a state
    machine should act on, not the raw debounced state itself (which is
    already True/False on every call, including all the ones where
    nothing changed).
    """

    def __init__(self, k: int, n: int) -> None:
        if not (0 < k <= n):
            raise ValueError(f"require 0 < k <= n, got k={k} n={n}")
        self.k = k
        self.n = n
        self._windows: dict[Hashable, deque[bool]] = {}
        self._state: dict[Hashable, bool] = {}

    def reset(self, key: Hashable | None = None) -> None:
        if key is None:
            self._windows.clear()
            self._state.clear()
        else:
            self._windows.pop(key, None)
            self._state.pop(key, None)

    def state(self, key: Hashable) -> bool:
        return self._state.get(key, False)

    def update(self, key: Hashable, observation: bool) -> tuple[bool, bool]:
        """Returns (debounced_state, transitioned)."""
        window = self._windows.setdefault(key, deque(maxlen=self.n))
        window.append(observation)

        prev = self._state.get(key, False)
        true_count = sum(window)
        false_count = len(window) - true_count

        new_state = prev
        if true_count >= self.k:
            new_state = True
        elif false_count >= self.k:
            new_state = False
        # else: not enough agreement yet either way — hold prev state.

        self._state[key] = new_state
        return new_state, (new_state != prev)
