"""Rolling-window motion maths. All pure functions, all rack-space, all
unit-testable with hand-written synthetic trajectories — no video, no
camera, no I/O in this module.

Velocity smoothing uses the One Euro filter (Casiez et al. 2012)
rather than a moving average: a moving average trades latency for
smoothness on a fixed knob, while One Euro adapts its cutoff to speed —
still at rest, responsive during fast motion — which is the latency/
jitter trade-off this system actually needs (sub-150ms glass-to-alert
while not jittering on a stationary hand).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, ...]


def _sub(a: Vec, b: Vec) -> Vec:
    return tuple(x - y for x, y in zip(a, b))


def _add(a: Vec, b: Vec) -> Vec:
    return tuple(x + y for x, y in zip(a, b))


def _scale(a: Vec, s: float) -> Vec:
    return tuple(x * s for x in a)


def _norm(a: Vec) -> float:
    return math.sqrt(sum(x * x for x in a))


def _dot(a: Vec, b: Vec) -> float:
    return sum(x * y for x, y in zip(a, b))


# Public aliases — other kinematics modules (grasp, intent) need these
# small vector primitives too; re-implementing them per-module would
# risk the two definitions drifting apart.
norm = _norm
dot = _dot
sub = _sub
add = _add
scale = _scale


@dataclass(frozen=True, slots=True)
class Sample:
    t: float
    pos: Vec


# --------------------------------------------------------------------------
# One Euro filter
# --------------------------------------------------------------------------


class OneEuroFilter:
    """Scalar One Euro filter. Feed it (value, timestamp) pairs in order."""

    def __init__(self, mincutoff: float = 1.0, beta: float = 0.0, dcutoff: float = 1.0) -> None:
        if mincutoff <= 0 or dcutoff <= 0:
            raise ValueError("mincutoff and dcutoff must be positive")
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._x_prev = x
            self._dx_prev = 0.0
            self._t_prev = t
            return x

        dt = max(t - self._t_prev, 1e-6)
        self._t_prev = t

        dx = (x - self._x_prev) / dt
        a_d = self._alpha(self.dcutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self._dx_prev
        self._dx_prev = dx_hat

        cutoff = self.mincutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._x_prev
        self._x_prev = x_hat

        return x_hat


class VectorOneEuroFilter:
    """One independent OneEuroFilter per dimension of an N-D point."""

    def __init__(self, dims: int, mincutoff: float = 1.0, beta: float = 0.0, dcutoff: float = 1.0) -> None:
        self._filters = [OneEuroFilter(mincutoff, beta, dcutoff) for _ in range(dims)]

    def __call__(self, x: Vec, t: float) -> Vec:
        return tuple(f(xi, t) for f, xi in zip(self._filters, x))


# --------------------------------------------------------------------------
# Rolling-window kinematics over a short deque of Samples, oldest-first
# --------------------------------------------------------------------------


def velocity(samples: list[Sample]) -> Vec:
    """Finite difference over the last two samples. Zero vector if <2 samples."""
    if len(samples) < 2:
        return (0.0,) * (len(samples[0].pos) if samples else 2)
    a, b = samples[-2], samples[-1]
    dt = max(b.t - a.t, 1e-6)
    return _scale(_sub(b.pos, a.pos), 1.0 / dt)


def speed(samples: list[Sample]) -> float:
    return _norm(velocity(samples))


def acceleration(samples: list[Sample]) -> Vec:
    """Finite difference of velocity over the last three samples."""
    if len(samples) < 3:
        return (0.0,) * (len(samples[0].pos) if samples else 2)
    v1 = velocity(samples[:-1])
    v2 = velocity(samples)
    dt = max(samples[-1].t - samples[-2].t, 1e-6)
    return _scale(_sub(v2, v1), 1.0 / dt)


def direction(samples: list[Sample]) -> Vec | None:
    """Unit vector of travel, or None if stationary/insufficient data."""
    v = velocity(samples)
    n = _norm(v)
    if n < 1e-9:
        return None
    return _scale(v, 1.0 / n)


def angular_change_rate(samples: list[Sample]) -> float:
    """Radians/sec of heading change, 2D only. 0 if insufficient or
    either leg of travel is stationary."""
    if len(samples) < 3:
        return 0.0
    d1 = direction(samples[:-1])
    d2 = direction(samples)
    if d1 is None or d2 is None or len(d1) != 2:
        return 0.0
    cos_theta = max(-1.0, min(1.0, _dot(d1, d2)))
    angle = math.acos(cos_theta)
    dt = max(samples[-1].t - samples[-2].t, 1e-6)
    return angle / dt


def dwell_duration_s(samples: list[Sample], radius: float) -> float:
    """How long (seconds, from the most recent sample backward) position
    has stayed within `radius` of the current position. 0 if the very
    latest step already exceeds radius."""
    if not samples:
        return 0.0
    anchor = samples[-1].pos
    dwell_start_t = samples[-1].t
    for s in reversed(samples):
        if _norm(_sub(s.pos, anchor)) > radius:
            break
        dwell_start_t = s.t
    return samples[-1].t - dwell_start_t


def hand_object_distance(hand_pos: Vec, object_pos: Vec) -> float:
    return _norm(_sub(hand_pos, object_pos))


def distance_rate_of_change(
    hand_samples: list[Sample], object_samples: list[Sample]
) -> float:
    """d(distance)/dt over the last two paired samples. Negative = closing."""
    if len(hand_samples) < 2 or len(object_samples) < 2:
        return 0.0
    d_prev = hand_object_distance(hand_samples[-2].pos, object_samples[-2].pos)
    d_now = hand_object_distance(hand_samples[-1].pos, object_samples[-1].pos)
    dt = max(hand_samples[-1].t - hand_samples[-2].t, 1e-6)
    return (d_now - d_prev) / dt


def approach_angle(hand_samples: list[Sample], object_pos: Vec) -> float | None:
    """Angle (radians) between the hand's velocity vector and the vector
    from the hand to the object. 0 = heading straight at it, pi = heading
    straight away. None if the hand isn't moving."""
    v = velocity(hand_samples)
    if _norm(v) < 1e-9:
        return None
    to_object = _sub(object_pos, hand_samples[-1].pos)
    if _norm(to_object) < 1e-9:
        return 0.0
    cos_theta = _dot(v, to_object) / (_norm(v) * _norm(to_object))
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return math.acos(cos_theta)
