from src.kinematics.drift import DriftDetector
from src.kinematics.motion import Sample
from src.kinematics.tracker import TrackState


def moving_samples(n=5, step=0.5):
    return [Sample(float(i), (i * step, 0.0)) for i in range(n)]


def test_drift_confirmed_for_sustained_unheld_motion():
    det = DriftDetector(min_displacement=0.3, min_speed=0.1, n_consecutive=3)
    samples = moving_samples()
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.VISIBLE, hand_in_grasp_range=False, grasp_active=False)
        for i in range(len(samples))
    ]
    assert any(fired)


def test_no_drift_when_hand_in_grasp_range():
    det = DriftDetector(min_displacement=0.3, min_speed=0.1, n_consecutive=2)
    samples = moving_samples()
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.VISIBLE, hand_in_grasp_range=True, grasp_active=False)
        for i in range(len(samples))
    ]
    assert not any(fired)


def test_no_drift_when_grasp_active():
    det = DriftDetector(min_displacement=0.3, min_speed=0.1, n_consecutive=2)
    samples = moving_samples()
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.VISIBLE, hand_in_grasp_range=False, grasp_active=True)
        for i in range(len(samples))
    ]
    assert not any(fired)


def test_left_frame_never_counts_as_drift():
    """This is the phantom-drift-on-exit guard: an object that left frame
    must never be reported as drifting."""
    det = DriftDetector(min_displacement=0.3, min_speed=0.1, n_consecutive=2)
    samples = moving_samples()
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.LEFT_FRAME, hand_in_grasp_range=False, grasp_active=False)
        for i in range(len(samples))
    ]
    assert not any(fired)


def test_occluded_does_not_count_as_drift():
    det = DriftDetector(min_displacement=0.3, min_speed=0.1, n_consecutive=2)
    samples = moving_samples()
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.OCCLUDED, hand_in_grasp_range=False, grasp_active=False)
        for i in range(len(samples))
    ]
    assert not any(fired)


def test_tiny_jitter_below_min_displacement_is_not_drift():
    det = DriftDetector(min_displacement=5.0, min_speed=0.01, n_consecutive=2)
    samples = moving_samples(step=0.1)  # small motion, below min_displacement
    fired = [
        det.update("obj1", samples[: i + 1], TrackState.VISIBLE, hand_in_grasp_range=False, grasp_active=False)
        for i in range(len(samples))
    ]
    assert not any(fired)
