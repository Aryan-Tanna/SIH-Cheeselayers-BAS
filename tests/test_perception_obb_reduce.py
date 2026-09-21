import math

from src.perception.obb_reduce import obb_to_reduced

# Fixed test box: top-left (0, 0), width 4, height 2. Deliberately
# non-square so rotation about the top-left pivot actually moves the
# centroid at every angle below (a square box at 90 deg would mask a
# pivot bug by coincidence).
W, H = 4.0, 2.0
RADIUS = math.hypot(W / 2.0, H / 2.0)  # sqrt(5), rotation-invariant


def test_centroid_at_zero_rotation_matches_naive():
    r = obb_to_reduced(0.0, 0.0, W, H, 0.0)
    assert abs(r.centroid[0] - 2.0) < 1e-9
    assert abs(r.centroid[1] - 1.0) < 1e-9


def test_centroid_at_45_degrees():
    r = obb_to_reduced(0.0, 0.0, W, H, 45.0)
    k = math.sqrt(2.0) / 2.0
    expected_x = 1.0 * k  # (dx=2, dy=1) rotated 45 deg CW
    expected_y = 3.0 * k
    assert abs(r.centroid[0] - expected_x) < 1e-6
    assert abs(r.centroid[1] - expected_y) < 1e-6


def test_centroid_at_90_degrees():
    r = obb_to_reduced(0.0, 0.0, W, H, 90.0)
    assert abs(r.centroid[0] - (-1.0)) < 1e-9
    assert abs(r.centroid[1] - 2.0) < 1e-9


def test_centroid_at_asymmetric_30_degrees():
    r = obb_to_reduced(0.0, 0.0, W, H, 30.0)
    cos30, sin30 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    dx, dy = 2.0, 1.0  # (width/2, height/2) — center relative to pivot
    expected_x = dx * cos30 - dy * sin30
    expected_y = dx * sin30 + dy * cos30
    assert abs(r.centroid[0] - expected_x) < 1e-9
    assert abs(r.centroid[1] - expected_y) < 1e-9


def test_naive_centroid_formula_is_wrong_once_rotated():
    """Regression guard: (x + w/2, y + h/2) is only correct at
    rotation == 0. If someone "simplifies" obb_to_reduced back to the
    naive formula, this must fail."""
    r = obb_to_reduced(0.0, 0.0, W, H, 90.0)
    naive = (0.0 + W / 2.0, 0.0 + H / 2.0)
    assert abs(r.centroid[0] - naive[0]) > 0.5
    assert abs(r.centroid[1] - naive[1]) > 0.5


def test_centroid_translates_with_nonzero_pivot():
    r = obb_to_reduced(10.0, 5.0, W, H, 90.0)
    assert abs(r.centroid[0] - 9.0) < 1e-9
    assert abs(r.centroid[1] - 7.0) < 1e-9


def test_radius_is_rotation_invariant():
    for angle in (0.0, 30.0, 45.0, 90.0, 137.0):
        r = obb_to_reduced(0.0, 0.0, W, H, angle)
        assert abs(r.radius - RADIUS) < 1e-9


def test_rotation_deg_normalized_to_0_360():
    assert abs(obb_to_reduced(0.0, 0.0, W, H, 450.0).rotation_deg - 90.0) < 1e-9
    assert abs(obb_to_reduced(0.0, 0.0, W, H, -90.0).rotation_deg - 270.0) < 1e-9


def test_rotation_deg_preserved_not_discarded():
    r = obb_to_reduced(0.0, 0.0, W, H, 33.0)
    assert abs(r.rotation_deg - 33.0) < 1e-9
