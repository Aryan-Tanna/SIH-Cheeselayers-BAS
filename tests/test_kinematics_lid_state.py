from src.kinematics.lid_state import LidStateTracker, make_measurer


def test_hinged_measurer_classifies_by_angle():
    m = make_measurer("hinged", half_open_deg=10.0, open_deg=35.0)
    assert m.state_for(0.0) == "closed"
    assert m.state_for(20.0) == "half_open"
    assert m.state_for(40.0) == "open"


def test_screw_measurer_classifies_by_axial_travel():
    m = make_measurer("screw", half_open_travel=5.0, open_travel=18.0)
    assert m.state_for(0.0) == "closed"
    assert m.state_for(8.0) == "half_open"
    assert m.state_for(20.0) == "open"


def test_same_tracker_interface_for_both_lid_types():
    hinged = LidStateTracker(make_measurer("hinged", half_open_deg=10.0, open_deg=35.0), hysteresis_frames=1)
    screw = LidStateTracker(make_measurer("screw", half_open_travel=5.0, open_travel=18.0), hysteresis_frames=1)
    assert hinged.update(40.0) == "open"
    assert screw.update(20.0) == "open"


def test_hysteresis_requires_sustained_frames_to_advance():
    tracker = LidStateTracker(make_measurer("screw", half_open_travel=5.0, open_travel=18.0), hysteresis_frames=3)
    assert tracker.update(20.0) == "closed"  # 1st open-ish frame, not yet confirmed
    assert tracker.update(20.0) == "closed"  # 2nd
    assert tracker.update(20.0) == "open"  # 3rd confirms


def test_single_noisy_frame_does_not_flip_confirmed_state():
    tracker = LidStateTracker(make_measurer("screw", half_open_travel=5.0, open_travel=18.0), hysteresis_frames=3)
    for _ in range(3):
        tracker.update(20.0)
    assert tracker.current == "open"
    # One noisy low reading shouldn't immediately drop it to closed.
    tracker.update(0.0)
    assert tracker.current in ("open", "half_open")
