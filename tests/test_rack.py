"""Rack geometry from ArUco markers -- synthetic cameras, no video.

The camera model is a pinhole looking at the floor from ~0.7 m, tilted
0-50 degrees: a phone over a tub. The marker layout mirrors the measured
rig (four 49 mm markers ~265-455 mm apart)."""

from __future__ import annotations

import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from src.perception.rack import (  # noqa: E402
    MarkerPose,
    RackConfig,
    RackTracker,
    apply_h,
    autodetect_dictionary,
    calibrate_layout,
    fit_rack,
    fit_rigid_square,
    load_rack_config,
    marker_corners_mm,
    save_rack_config,
    to_rack,
)

SIZE = 49.0
TRUE_LAYOUT = {  # rack frame, ID1 at the origin
    1: MarkerPose(0.0, 0.0, 0.0),
    2: MarkerPose(-120.0, 440.0, 3.0),
    3: MarkerPose(140.0, 225.0, -2.0),
    4: MarkerPose(-265.0, 190.0, 5.0),
}
CENTRE = np.array([-60.0, 215.0])


def camera(tilt_deg: float, yaw_deg: float = 0.0, height: float = 700.0, f: float = 1400.0):
    """Returns project(points_mm (N,2) on the floor) -> pixels (N,2)."""
    t, y = math.radians(tilt_deg), math.radians(yaw_deg)
    # camera looks at CENTRE from above, tilted back by t, yawed by y
    look = np.array([CENTRE[0], CENTRE[1], 0.0])
    eye = look + np.array([math.sin(y) * math.sin(t), -math.cos(y) * math.sin(t), -math.cos(t)]) * height
    zc = (look - eye) / np.linalg.norm(look - eye)
    up = np.array([0.0, 1.0, 0.0])
    xc = np.cross(up, zc)
    if np.linalg.norm(xc) < 1e-9:
        xc = np.array([1.0, 0.0, 0.0])
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    r = np.vstack([xc, yc, zc])
    k = np.array([[f, 0, 960.0], [0, f, 540.0], [0, 0, 1]])

    def project(pts: np.ndarray, z: float = 0.0) -> np.ndarray:
        p = np.hstack([np.asarray(pts, float).reshape(-1, 2), np.full((len(pts), 1), -z)])
        c = (p - eye) @ r.T
        uv = c @ k.T
        return uv[:, :2] / uv[:, 2:3]

    return project


def observe(project, ids=(1, 2, 3, 4), noise: float = 0.0, rng=None) -> dict[int, np.ndarray]:
    rng = rng or np.random.default_rng(0)
    return {i: project(marker_corners_mm(TRUE_LAYOUT[i], SIZE)) + rng.normal(0, noise, (4, 2))
            for i in ids}


def cfg_with(layout=TRUE_LAYOUT, **kw) -> RackConfig:
    return RackConfig(marker_size_mm=SIZE, marker_ids=(1, 2, 3, 4), layout=dict(layout), **kw)


def layout_error_mm(est: dict[int, MarkerPose]) -> float:
    return max(math.hypot(est[i].x_mm - TRUE_LAYOUT[i].x_mm, est[i].y_mm - TRUE_LAYOUT[i].y_mm)
               for i in TRUE_LAYOUT)


# --- pure geometry ------------------------------------------------------------

def test_rigid_square_fit_recovers_pose_and_ignores_scale():
    pose = MarkerPose(12.0, -7.0, 33.0)
    pts = marker_corners_mm(pose, SIZE)
    got = fit_rigid_square(pts, SIZE)
    assert got.x_mm == pytest.approx(12.0) and got.y_mm == pytest.approx(-7.0)
    assert got.angle_deg == pytest.approx(33.0)
    # a 20% too-big observed square still gives the same centre and angle
    got2 = fit_rigid_square((pts - pts.mean(0)) * 1.2 + pts.mean(0), SIZE)
    assert got2.angle_deg == pytest.approx(33.0)


@pytest.mark.parametrize("tilt", [0, 20, 40, 50])
def test_single_marker_maps_the_whole_floor(tilt):
    """One visible marker is enough (all four are visible in only 8-81% of
    real frames). Error far from that marker grows with corner noise."""
    proj = camera(tilt, yaw_deg=25)
    fit = fit_rack(observe(proj, ids=(3,), noise=0.0), cfg_with())
    assert fit is not None and fit.ids_used == (3,)
    far = np.array([[-265.0, 190.0], [-120.0, 440.0], [CENTRE[0], CENTRE[1]]])
    assert np.abs(to_rack(fit, proj(far)) - far).max() < 0.01  # float32 inside OpenCV


@pytest.mark.parametrize("tilt", [0, 30, 50])
def test_all_markers_with_noise_accurate_to_a_few_mm(tilt):
    proj = camera(tilt, yaw_deg=-15)
    rng = np.random.default_rng(1)
    fit = fit_rack(observe(proj, noise=0.3, rng=rng), cfg_with())
    assert fit is not None and len(fit.ids_used) == 4
    grid = np.array([[x, y] for x in (-250, -60, 120) for y in (0, 215, 430)], float)
    assert np.abs(to_rack(fit, proj(grid)) - grid).max() < 3.0


def test_moved_marker_is_outvoted_not_averaged_in():
    proj = camera(25)
    obs = observe(proj)
    moved = dict(TRUE_LAYOUT)
    moved[4] = MarkerPose(-205.0, 190.0, 5.0)  # someone re-taped ID4 60 mm off
    fit = fit_rack(obs, cfg_with(layout=moved))
    assert fit is not None and 4 not in fit.ids_used
    assert fit.reproj_px < 0.5


def test_unknown_ids_ignored():
    proj = camera(10)
    obs = observe(proj, ids=(1, 3))
    obs[17] = obs[1] + 300.0  # reflection read as another ID
    fit = fit_rack(obs, cfg_with())
    assert fit is not None and fit.ids_used == (1, 3)


def test_no_layout_marker_visible_gives_none():
    assert fit_rack({}, cfg_with()) is None
    assert fit_rack({9: np.zeros((4, 2))}, cfg_with()) is None


# --- calibration --------------------------------------------------------------

def _clip_observations(tilt: float, yaw: float, n: int, noise: float, seed: int):
    """A fixed camera, hands hiding random markers: like the real clips."""
    rng = np.random.default_rng(seed)
    proj = camera(tilt, yaw)
    frames = []
    for _ in range(n):
        ids = [i for i in (1, 2, 3, 4) if rng.random() > 0.35]
        frames.append(observe(proj, ids=ids, noise=noise, rng=rng))
    return frames


@pytest.mark.parametrize("tilt,yaw", [(5, 0), (25, 30), (45, -20)])
def test_calibration_recovers_layout_from_one_fixed_camera(tilt, yaw):
    frames = _clip_observations(tilt, yaw, n=120, noise=0.3, seed=tilt)
    res = calibrate_layout(frames, SIZE)
    assert res.unplaced == []
    assert layout_error_mm(res.layout) < 2.0
    assert all(abs(res.layout[i].angle_deg - TRUE_LAYOUT[i].angle_deg) < 1.0 for i in TRUE_LAYOUT)
    assert res.rms_reproj_px < 1.0


def test_calibration_needs_two_markers_together():
    proj = camera(10)
    with pytest.raises(ValueError):
        calibrate_layout([observe(proj, ids=(1,)), observe(proj, ids=(2,))], SIZE)


def test_calibrated_layout_then_tracks_a_different_camera():
    """Calibrate on one camera placement, then track from another: the
    whole point of rack space is that moving the camera changes nothing."""
    res = calibrate_layout(_clip_observations(10, 0, 100, 0.3, 7), SIZE)
    proj2 = camera(40, yaw_deg=60)
    fit = fit_rack(observe(proj2, ids=(2, 4), noise=0.3), cfg_with(layout=res.layout))
    assert fit is not None
    pts = np.array([[-60.0, 215.0], [100.0, 400.0]])
    assert np.abs(to_rack(fit, proj2(pts)) - pts).max() < 4.0


# --- tracker: hold / fallback ---------------------------------------------------

def test_tracker_hold_then_fallback():
    proj = camera(15)
    tr = RackTracker(cfg_with(hold_s=1.0))
    assert tr.update_markers(0.0, observe(proj, ids=(2,))).status == "ok"
    assert tr.geometry_status == "rack"
    held = tr.update_markers(0.6, {})
    assert held.status == "held" and held.fit is not None and held.age_s == pytest.approx(0.6)
    assert tr.update_markers(1.5, {}).status == "none"
    assert tr.geometry_status == "image"
    assert tr.update_markers(1.6, observe(proj, ids=(1,))).status == "ok"


def test_tracker_uncalibrated_and_off():
    tr = RackTracker(RackConfig(marker_size_mm=SIZE, layout={}))
    assert tr.update_markers(0.0, observe(camera(0), ids=(1,))).status == "uncalibrated"
    assert tr.geometry_status == "image"
    off = RackTracker(RackConfig(enabled=False))
    assert off.update(0.0, np.zeros((10, 10, 3), np.uint8)).status == "off"


# --- config ---------------------------------------------------------------------

def test_config_roundtrip_and_validation(tmp_path):
    cfg = cfg_with()
    path = tmp_path / "rack.yaml"
    save_rack_config(cfg, path, layout_note="test")
    back = load_rack_config(path)
    assert back.marker_ids == (1, 2, 3, 4) and back.marker_size_mm == SIZE
    assert back.layout[3].x_mm == pytest.approx(140.0)
    assert "BAD" not in path.read_text()
    for bad in (RackConfig(dictionary="DICT_NOPE"), RackConfig(marker_size_mm=0),
                RackConfig(marker_ids=()), RackConfig(marker_ids=(1, 1)),
                RackConfig(marker_ids=(1,), layout={2: MarkerPose(0, 0, 0)})):
        assert bad.validate()
        with pytest.raises(ValueError):
            save_rack_config(bad, tmp_path / "x.yaml")
    assert load_rack_config(tmp_path / "missing.yaml").enabled is False


# --- real detector on rendered markers -------------------------------------------

def _render(dictionary: int, ids: list[int], px: int = 80) -> np.ndarray:
    img = np.full((400, 700), 255, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(dictionary)
    for k, i in enumerate(ids):
        m = cv2.aruco.generateImageMarker(d, i, px)
        x, y = 40 + k * 160, 150
        img[y:y + px, x:x + px] = m
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def test_autodetect_finds_the_printed_dictionary_and_ids():
    img = _render(cv2.aruco.DICT_4X4_50, [1, 2, 3, 4])
    best = autodetect_dictionary(img)[0]
    assert best == ("DICT_4X4_50", [1, 2, 3, 4])


def test_tracker_end_to_end_on_a_rendered_image():
    img = _render(cv2.aruco.DICT_4X4_50, [0, 1, 17])
    lay = {0: MarkerPose(0, 0, 0), 1: MarkerPose(160 * SIZE / 80, 0, 0)}  # 80 px = 49 mm
    tr = RackTracker(RackConfig(marker_size_mm=SIZE, marker_ids=(0, 1), layout=lay))
    pose = tr.update(0.0, img)
    assert pose.status == "ok" and pose.markers_seen == (0, 1)  # 17 filtered out
    centre0 = apply_h(pose.fit.img_to_rack, np.array([[80.0, 190.0]]))[0]
    assert np.abs(centre0).max() < 1.0


# --- GUI edits ------------------------------------------------------------------

def test_edit_size_scales_layout_and_dict_change_clears_it():
    from src.perception.rack import edit_config

    old = cfg_with()
    new, note = edit_config(old, old.dictionary, 98.0, (1, 2, 3, 4))
    assert new.layout[3].x_mm == pytest.approx(280.0) and "scaled" in note
    new2, note2 = edit_config(old, "DICT_5X5_50", SIZE, (1, 2, 3, 4))
    assert new2.layout == {} and "cleared" in note2
    new3, note3 = edit_config(old, old.dictionary, SIZE, (0, 1, 2))
    assert set(new3.layout) == {1, 2} and "dropped" in note3 and "[0]" in note3


def test_parse_ids():
    from src.perception.rack import parse_ids

    assert parse_ids(" 1, 2,3 4") == (1, 2, 3, 4)
    for bad in ("", "a,b", "1,1"):
        with pytest.raises(ValueError):
            parse_ids(bad)
