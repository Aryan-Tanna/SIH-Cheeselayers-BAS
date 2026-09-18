from src.kinematics.grasp import GraspDetector, bbox_contains_or_near, motion_coherence
from src.kinematics.motion import Sample


def test_bbox_contains_or_near():
    assert bbox_contains_or_near((0.0, 0.0), (0.0, 0.0), bbox_radius=1.0, margin=0.5)
    assert not bbox_contains_or_near((10.0, 0.0), (0.0, 0.0), bbox_radius=1.0, margin=0.5)


def test_motion_coherence_zero_when_object_stationary():
    hand = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0))]
    obj = [Sample(0.0, (5.0, 5.0)), Sample(1.0, (5.0, 5.0))]
    assert motion_coherence(hand, obj) == 0.0


def test_motion_coherence_high_when_moving_together():
    hand = [Sample(0.0, (0.0, 0.0)), Sample(1.0, (1.0, 0.0))]
    obj = [Sample(0.0, (5.0, 0.0)), Sample(1.0, (6.0, 0.0))]
    assert motion_coherence(hand, obj) > 0.99


def test_distance_alone_does_not_trigger_grasp():
    """A hand resting near a stationary object, with no coherent motion,
    must NOT register as a grasp — distance alone is too weak."""
    det = GraspDetector(proximity_margin=0.5, coherence_threshold=0.7, k=2, n=2)
    obj_center = (0.0, 0.0)
    hand = [Sample(0.0, (0.1, 0.0))]
    obj = [Sample(0.0, (0.0, 0.0))]
    for t in (0.0, 1.0, 2.0):
        hand.append(Sample(t, (0.1, 0.0)))
        obj.append(Sample(t, (0.0, 0.0)))
        event = det.update(t, hand, obj, obj_center, object_bbox_radius=0.3)
    assert det.active is False
    assert event is None


def test_near_plus_coherent_motion_triggers_grasp_start_and_end():
    det = GraspDetector(proximity_margin=0.5, coherence_threshold=0.7, k=2, n=2)
    obj_center = (0.0, 0.0)

    hand_samples = [Sample(0.0, (0.0, 0.0))]
    obj_samples = [Sample(0.0, (0.0, 0.0))]

    events = []
    # Hand approaches and then moves together with the object.
    for i, t in enumerate([1.0, 2.0, 3.0, 4.0]):
        pos = (0.0, 0.0) if i == 0 else (float(i), 0.0)
        hand_samples.append(Sample(t, pos))
        obj_samples.append(Sample(t, pos))
        ev = det.update(t, hand_samples, obj_samples, obj_center, object_bbox_radius=5.0)
        if ev:
            events.append(ev)

    assert any(e.kind == "grasp_start" for e in events)
    assert det.active is True
