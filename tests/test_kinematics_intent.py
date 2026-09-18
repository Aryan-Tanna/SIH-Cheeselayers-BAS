from src.kinematics.intent import IntentTracker, project_position, within_cone
from src.kinematics.motion import Sample


def test_project_position_extrapolates_linearly():
    samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0))]
    projected = project_position(samples, horizon_s=0.3)
    assert projected == (1.3, 0.0)


def test_within_cone_true_when_aligned():
    assert within_cone((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), half_angle_deg=10.0)


def test_within_cone_false_when_perpendicular():
    assert not within_cone((0.0, 0.0), (1.0, 0.0), (0.0, 5.0), half_angle_deg=10.0)


def test_reaching_past_one_module_toward_another_is_not_immediately_confirmed():
    """Naive linear extrapolation would flag this as 'heading for module A'
    even though the hand is really continuing on to module B just beyond
    it — k-of-n + hysteresis means a single frame of alignment isn't
    enough to confirm intent."""
    tracker = IntentTracker(k=3, n=3, half_angle_deg=15.0, horizon_s=0.3)
    hand_samples = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0))]
    confirmed = tracker.update("module_a", hand_samples, object_pos=(1.2, 0.0))
    assert confirmed is False


def test_sustained_alignment_confirms_intent():
    tracker = IntentTracker(k=2, n=3, half_angle_deg=15.0, horizon_s=0.3)
    hand_samples = [Sample(0.0, (0.0, 0.0))]
    confirmed = False
    for t in (1.0, 2.0, 3.0):
        hand_samples.append(Sample(t, (t, 0.0)))
        confirmed = tracker.update("module_a", hand_samples, object_pos=(t + 1.0, 0.0))
    assert confirmed is True
