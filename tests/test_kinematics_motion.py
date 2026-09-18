import math

from src.kinematics.motion import (
    OneEuroFilter,
    Sample,
    acceleration,
    angular_change_rate,
    approach_angle,
    direction,
    dwell_duration_s,
    hand_object_distance,
    speed,
    velocity,
)


def test_velocity_from_linear_trajectory():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (2.0, 0.0))]
    assert velocity(samples) == (2.0, 0.0)


def test_speed_is_velocity_norm():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (3.0, 4.0))]
    assert speed(samples) == 5.0


def test_acceleration_of_constant_velocity_is_zero():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0)), Sample(2.0, (2.0, 0.0))]
    ax, ay = acceleration(samples)
    assert abs(ax) < 1e-9
    assert abs(ay) < 1e-9


def test_direction_is_none_when_stationary():
    samples = [Sample(0.0, (1.0, 1.0)), Sample(1.0, (1.0, 1.0))]
    assert direction(samples) is None


def test_angular_change_rate_of_right_angle_turn():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0)), Sample(2.0, (1.0, 1.0))]
    rate = angular_change_rate(samples)
    assert abs(rate - math.pi / 2) < 1e-6


def test_dwell_duration_within_radius():
    samples = [Sample(t, (0.0, 0.0)) for t in range(5)]
    assert dwell_duration_s(samples, radius=0.5) == 4.0


def test_dwell_duration_zero_if_just_moved():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (10.0, 0.0))]
    assert dwell_duration_s(samples, radius=0.5) == 0.0


def test_hand_object_distance():
    assert hand_object_distance((0.0, 0.0), (3.0, 4.0)) == 5.0


def test_approach_angle_heading_straight_at_object():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0))]
    angle = approach_angle(samples, object_pos=(5.0, 0.0))
    assert abs(angle) < 1e-6


def test_approach_angle_heading_away_from_object():
    samples = [Sample(0.0, (5.0, 0.0)), Sample(1.0, (6.0, 0.0))]
    angle = approach_angle(samples, object_pos=(0.0, 0.0))
    assert abs(angle - math.pi) < 1e-6


def test_one_euro_filter_smooths_step_noise():
    f = OneEuroFilter(mincutoff=1.0, beta=0.0)
    out = f(0.0, 0.0)
    assert out == 0.0
    out = f(1.0, 1 / 30)
    # Should move toward 1.0 but not jump all the way there — smoothing.
    assert 0.0 < out < 1.0


def test_one_euro_filter_tracks_sustained_motion_closely():
    f = OneEuroFilter(mincutoff=1.0, beta=1.0)
    t = 0.0
    val = 0.0
    for _ in range(60):
        t += 1 / 30
        val += 1 / 30  # constant velocity ramp
        out = f(val, t)
    # After many frames of consistent motion, filtered output should be
    # close to the true (noiseless) ramp value.
    assert abs(out - val) < 0.05
