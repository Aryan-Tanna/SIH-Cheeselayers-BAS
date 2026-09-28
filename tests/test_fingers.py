"""Grasp / reach from hand landmarks, on synthetic 21-point hands."""

import math

import pytest

from src.kinematics.fingers import (
    FingerGrasp,
    aperture,
    contact,
    distance_scales,
    hand_scale,
    time_to_contact,
)


def hand(cx, cy, scale=100.0, angle_deg=0.0, tips_at=None, open_=1.0):
    """A hand whose wrist is at (cx, cy), fingers pointing along angle_deg.
    tips_at: optional (x, y) where thumb + index tips are placed (a pinch).
    open_: thumb-index spread in hand scales."""
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)  # along the fingers
    vx, vy = -uy, ux  # across the palm

    def at(along, across):
        return (cx + scale * (along * ux + across * vx), cy + scale * (along * uy + across * vy))

    lm = [at(0, 0)]  # 0 wrist
    lm += [at(0.3, -0.4), at(0.5, -0.55), at(0.7, -0.6), at(0.9, -0.5 * open_)]  # 1-4 thumb
    for i, across in enumerate((-0.25, 0.0, 0.25, 0.45)):  # index, middle, ring, pinky
        lm += [at(1.0, across), at(1.3, across), at(1.5, across), at(1.7, across + (0.5 * open_ if i == 0 else 0))]
    if tips_at is not None:
        lm[4] = (tips_at[0] - 5, tips_at[1])
        lm[8] = (tips_at[0] + 5, tips_at[1])
    return lm


def test_scale_and_aperture_are_size_invariant():
    small, big = hand(0, 0, scale=50), hand(0, 0, scale=200)
    assert hand_scale(big) == pytest.approx(4 * hand_scale(small))
    assert aperture(small) == pytest.approx(aperture(big))
    assert aperture(hand(0, 0, open_=1.5)) > aperture(hand(0, 0, open_=0.2))


def test_contact_needs_fingertips_on_the_object_not_a_hovering_palm():
    box = (400, 400, 500, 500)
    assert contact(hand(300, 450, tips_at=(450, 450)), box)
    # palm right above the jar, fingertips pointing away: not a grasp
    hovering = hand(450, 450, angle_deg=180, tips_at=None)
    assert not contact(hovering, box)


def test_orientation_does_not_matter():
    box = (400, 400, 500, 500)
    for ang in (0, 90, 180, 270, 33):
        assert contact(hand(450 - 150 * math.cos(math.radians(ang)), 450 - 150 * math.sin(math.radians(ang)),
                            angle_deg=ang, tips_at=(450, 450)), box)


def test_time_to_contact_from_a_steady_approach():
    track = [(t / 10, 3.0 - 2.0 * t / 10) for t in range(6)]  # 2 hand scales per second
    assert time_to_contact(track) == pytest.approx(2.0 / 2.0, abs=0.01)  # 2.0 left at 2/s
    receding = [(t / 10, 1.0 + t / 10) for t in range(6)]
    assert time_to_contact(receding) is None
    assert time_to_contact(track[:2]) is None


def test_reach_predicted_before_the_grasp_then_grasp():
    fg = FingerGrasp(reach_k=2, reach_n=3, grasp_k=2, grasp_n=3, horizon_s=1.5)
    box = (1000, 400, 1100, 500)
    states = []
    for i in range(12):  # palm moves toward the jar at ~150 px/frame, then pinches it
        t = i / 10
        x = 300 + 60 * i
        tips = (1050, 450) if x >= 900 else None
        states.append((t, fg.update("h", t, hand(x, 450, tips_at=tips), box)))
    reach_on = next(t for t, s in states if s.reaching)
    grasp_on = next(t for t, s in states if s.grasping)
    assert reach_on < grasp_on  # predicted before it happened
    assert any(s.eta_s is not None and s.eta_s > 0 for _, s in states if s.reaching)


def test_hand_moving_away_or_lost_is_not_reaching():
    fg = FingerGrasp()
    box = (0, 0, 100, 100)
    for i in range(10):
        s = fg.update("h", i / 10, hand(300 + 50 * i, 50), box)
        assert not s.reaching
    assert not fg.update("h", 1.1, None, box).reaching
    assert distance_scales(hand(-30, 50), box) == 0.0  # palm centre (0.8 scales ahead of the wrist) inside
