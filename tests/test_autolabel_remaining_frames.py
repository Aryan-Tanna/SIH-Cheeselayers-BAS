import math

from scripts.autolabel_remaining_frames import xywhr_to_ls_box, xywhr_to_yolo_corners
from scripts.convert_labels_to_yolo_obb import obb_corners_normalized


def _ultralytics_xywhr_for_ls_box(x_pct, y_pct, w_pct, h_pct, rotation_deg, orig_w, orig_h):
    """Given a Label-Studio-style box, compute what ultralytics'
    center-pivot (cx, cy, w, h, theta) parameterization of that exact
    same physical rectangle would be -- rotation angle is pivot-
    independent (only the reference point differs), so theta is
    unchanged; only the center needs deriving from the corners."""
    corners = obb_corners_normalized(x_pct, y_pct, w_pct, h_pct, rotation_deg, orig_w, orig_h)
    xs = [c[0] * orig_w for c in corners]
    ys = [c[1] * orig_h for c in corners]
    cx, cy = sum(xs) / 4.0, sum(ys) / 4.0
    return cx, cy, w_pct / 100.0 * orig_w, h_pct / 100.0 * orig_h, math.radians(rotation_deg)


def test_round_trip_ls_to_ultralytics_and_back_zero_rotation():
    cx, cy, w, h, theta = _ultralytics_xywhr_for_ls_box(10.0, 20.0, 40.0, 10.0, 0.0, 1000, 1000)
    ls_box = xywhr_to_ls_box(cx, cy, w, h, theta, 1000, 1000)
    assert abs(ls_box["x"] - 10.0) < 1e-6
    assert abs(ls_box["y"] - 20.0) < 1e-6
    assert abs(ls_box["width"] - 40.0) < 1e-6
    assert abs(ls_box["height"] - 10.0) < 1e-6
    assert abs(ls_box["rotation"] - 0.0) < 1e-6


def test_round_trip_ls_to_ultralytics_and_back_45_degrees():
    cx, cy, w, h, theta = _ultralytics_xywhr_for_ls_box(5.0, 5.0, 20.0, 30.0, 45.0, 1000, 1000)
    ls_box = xywhr_to_ls_box(cx, cy, w, h, theta, 1000, 1000)
    assert abs(ls_box["x"] - 5.0) < 1e-6
    assert abs(ls_box["y"] - 5.0) < 1e-6
    assert abs(ls_box["width"] - 20.0) < 1e-6
    assert abs(ls_box["height"] - 30.0) < 1e-6
    assert abs(ls_box["rotation"] - 45.0) < 1e-6


def test_near_180_degree_prediction_is_the_same_rectangle_as_near_0():
    """A near-axis-aligned box has no unique 0-degree description --
    ultralytics may report it via the diagonally-opposite corner
    (theta near 180 deg instead of near 0). Both must trace out the
    same 4 corners, just starting from a different corner index."""
    w, h, orig = 40.0, 10.0, 1000
    corners_0 = xywhr_to_yolo_corners(520.0, 205.0, w, h, math.radians(0.1), orig, orig)
    corners_180 = xywhr_to_yolo_corners(520.0, 205.0, w, h, math.radians(179.9), orig, orig)
    # corners_180's point 0 should land near corners_0's point 2 (the
    # diagonally opposite corner), not be a nonsensical shape.
    assert abs(corners_180[0] - corners_0[4]) < 0.01
    assert abs(corners_180[1] - corners_0[5]) < 0.01
