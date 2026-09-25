import pytest

from src.perception.detector import Detection
from src.protocol.events import StateEvent
from src.perception.fusion import (
    FusionConfig,
    ImageSpaceGeometry,
    RoleBinding,
    SceneFusion,
    StateVote,
    binding_for,
    overlap_fraction,
)
from src.protocol.loader import REPO_ROOT, resolve

BINDING = RoleBinding("container", "case_open", "case_closed",
                      {"module_a": "red_module", "module_b": "yellow_module"})
BOX = (100, 100, 500, 300)  # container, image px


def det(cls, x0, y0, x1, y1, conf=0.9):
    return Detection(cls, conf, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0,
                     ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def case(state="open"):
    return det("case_open" if state == "open" else "case_closed", *BOX)


RED_IN = ("red_module", 150, 150, 250, 250)
RED_OUT = ("red_module", 600, 150, 700, 250)
YEL_IN = ("yellow_module", 300, 150, 400, 250)
YEL_OUT = ("yellow_module", 600, 320, 700, 420)


def run(frames, k=3, n=4, fps=10.0, stale_s=1.5):
    f = SceneFusion(BINDING, FusionConfig(k=k, n=n, stale_s=stale_s))
    out = []
    for i, dets in enumerate(frames):
        for e in f.update(i / fps, dets):
            out.append((round(e.ts, 2), e.action, e.target))
    return out, f


def test_state_vote_needs_k_of_n():
    v = StateVote("in", k=3, n=4, stale_s=10)
    assert [v.observe(t, s) for t, s in enumerate(["out", "in", "out", "out"])] == [None, None, None, "out"]
    assert v.state == "out"


def test_state_vote_stale_window_is_cleared():
    v = StateVote("in", k=2, n=3, stale_s=1.0)
    assert v.observe(0.0, "out") is None
    assert v.observe(5.0, "out") is None  # old vote dropped after the gap
    assert v.observe(5.1, "out") == "out"


def test_overlap_fraction():
    assert overlap_fraction((0, 0, 10, 10), (0, 0, 20, 20)) == 1.0
    assert overlap_fraction((10, 0, 30, 10), (0, 0, 20, 20)) == 0.5


def test_clean_open_remove_return_close():
    frames = [[case("closed")]] * 4 + [[case(), det(*RED_IN)]] * 4 + [[case(), det(*RED_OUT)]] * 4 \
        + [[case(), det(*RED_IN)]] * 4 + [[case("closed")]] * 4
    events, f = run(frames)
    assert [(a, t) for _, a, t in events] == [
        ("open", "container"), ("remove_from", "module_a"),
        ("place_into", "module_a"), ("close", "container")]
    assert f.states() == {"container": "closed", "module_a": "in", "module_b": "in"}


def test_two_objects_moving_concurrently_are_two_distinct_events():
    # the test2.mp4 pattern: red out, then yellow out while red is still out
    frames = [[case(), det(*RED_IN), det(*YEL_IN)]] * 4 \
        + [[case(), det(*RED_OUT), det(*YEL_IN)]] * 2 \
        + [[case(), det(*RED_OUT), det(*YEL_OUT)]] * 6
    events, _ = run(frames)
    removes = [(t, tgt) for t, a, tgt in events if a == "remove_from"]
    assert [tgt for _, tgt in removes] == ["module_a", "module_b"]
    assert removes[0][0] != removes[1][0] or len(removes) == 2


def test_simultaneous_removal_same_frame_still_two_events():
    frames = [[case(), det(*RED_IN), det(*YEL_IN)]] * 4 + [[case(), det(*RED_OUT), det(*YEL_OUT)]] * 4
    events, _ = run(frames)
    assert sorted(tgt for _, a, tgt in events if a == "remove_from") == ["module_a", "module_b"]


def test_occlusion_holds_state():
    frames = [[case(), det(*RED_IN)]] * 4 + [[case()]] * 20 + [[case(), det(*RED_IN)]] * 4
    events, _ = run(frames)
    assert [a for _, a, _ in events] == ["open"]


def test_single_frame_flicker_is_ignored():
    frames = [[case(), det(*RED_IN)]] * 4 + [[case(), det(*RED_OUT)]] + [[case(), det(*RED_IN)]] * 6
    events, _ = run(frames)
    assert "remove_from" not in [a for _, a, _ in events]


def test_held_in_front_of_container_counts_as_out():
    # overlaps the container box in the image, but mostly sticks out of it
    held = ("red_module", 200, 220, 360, 420)
    frames = [[case(), det(*RED_IN)]] * 4 + [[case(), det(*held)]] * 4
    events, _ = run(frames)
    assert ("remove_from", "module_a") in [(a, t) for _, a, t in events]


def test_clip_starting_open_emits_open():
    events, _ = run([[case()]] * 4)
    assert events[0][1:] == ("open", "container")


def test_module_seen_before_any_container_is_ignored():
    events, _ = run([[det(*RED_OUT)]] * 6)
    assert events == []


def test_low_confidence_below_class_threshold_is_not_evidence():
    f = SceneFusion(BINDING, FusionConfig(k=2, n=3, min_conf={"red_module": 0.5}))
    out = []
    for i in range(5):
        out += f.update(i * 0.1, [case(), det(*RED_OUT, conf=0.3)])
    assert [e.action for e in out] == ["open"]


def test_binding_from_real_protocol_and_profiles():
    P = REPO_ROOT / "configs/protocols/bas_specimen_v1.json"
    b = binding_for(resolve(P, object_profile="configs/objects/profile_rect.yaml"))
    assert b.container == "container" and b.open_cls == "case_open"
    assert b.modules == {"module_a": "red_module", "module_b": "yellow_module"}


def test_geometry_min_overlap():
    g = ImageSpaceGeometry(0.8)
    assert g.inside(det(*RED_IN), BOX)
    assert not g.inside(det(*RED_OUT), BOX)


# --- rack space (ArUco floor mm) ----------------------------------------------------

import math  # noqa: E402

import numpy as np  # noqa: E402

from src.perception.rack import RackFit, RackPose  # noqa: E402


def _pose(status="ok", scale=1.0):
    """Floor = image scaled: 1 px -> `scale` mm (an overhead camera)."""
    h = np.diag([scale, scale, 1.0])
    return RackPose(status, RackFit(h, np.linalg.inv(h), (1,), 0.5), (1,), 0.0, 0.0)


def rotated(cls, cx, cy, w, h, angle_deg, conf=0.9):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = tuple((cx + ca * x - sa * y, cy + sa * x + ca * y)
                for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)))
    return Detection(cls, conf, cx, cy, w, h, angle_deg, pts)


def _feed(fusion, frames, pose=None, fps=10.0):
    out = []
    for i, dets in enumerate(frames):
        out += [(e.action, e.target) for e in fusion.update(i / fps, dets, pose)]
    return out


AUTO = FusionConfig(k=3, n=4, geometry="auto", rack_margin_mm=10.0)


def test_image_mode_ignores_the_rack_pose_entirely():
    """geometry 'image' (the default) + a pose == today's behaviour."""
    frames = [[case("closed")]] * 4 + [[case("open"), det(*RED_IN)]] * 4 + [[case("open"), det(*RED_OUT)]] * 5
    a = _feed(SceneFusion(BINDING, FusionConfig(k=3, n=4)), frames)
    b = _feed(SceneFusion(BINDING, FusionConfig(k=3, n=4)), frames, _pose())
    c = _feed(SceneFusion(BINDING, AUTO), frames, None)  # auto, but no rack
    assert a == b == c and ("remove_from", "module_a") in a


def test_rotated_container_module_beside_it_is_out_only_in_rack_space():
    # case rotated 40 deg: its axis-aligned box covers floor beside it
    box = rotated("case_open", 300, 300, 300, 120, 40)
    beside = det("red_module", 330, 170, 370, 210)  # in the AABB corner, off the case
    frames = [[box]] * 4 + [[box, beside]] * 6
    img = _feed(SceneFusion(BINDING, FusionConfig(k=3, n=4, min_overlap=0.8)), frames)
    rack = _feed(SceneFusion(BINDING, AUTO), frames, _pose())
    assert ("remove_from", "module_a") not in img  # image space: fooled
    assert ("remove_from", "module_a") in rack


def test_open_lid_flap_is_not_interior():
    closed = det("case_closed", 100, 100, 300, 200)
    opened = det("case_open", 100, 100, 300, 320)  # lid flap swung down to y=320
    on_lid = det("red_module", 180, 250, 220, 290)  # resting on the open lid
    frames = [[closed]] * 4 + [[opened]] * 4 + [[opened, on_lid]] * 6
    rack = _feed(SceneFusion(BINDING, AUTO), frames, _pose())
    img = _feed(SceneFusion(BINDING, FusionConfig(k=3, n=4)), frames)
    assert ("remove_from", "module_a") in rack
    assert ("remove_from", "module_a") not in img


def test_container_moved_while_open_uses_the_open_box():
    f = SceneFusion(BINDING, AUTO)
    _feed(f, [[det("case_closed", 100, 100, 300, 200)]] * 4, _pose())
    _feed(f, [[det("case_open", 600, 600, 800, 800)]] * 4, _pose())  # slid far away
    interior = f.interior_floor()
    assert interior[:, 0].min() == pytest.approx(600.0)


def test_mm_margin_scales_with_the_rack_not_pixels():
    box = det("case_open", 100, 100, 300, 300)
    just_out = det("red_module", 300, 180, 340, 220)  # centre 20 px right of the edge
    frames = [[box]] * 4 + [[box, just_out]] * 6
    # 1 px = 1 mm: 20 mm out > 10 mm margin -> out
    assert ("remove_from", "module_a") in _feed(SceneFusion(BINDING, AUTO), frames, _pose(scale=1.0))
    # 1 px = 0.25 mm (camera further away... or zoomed): 5 mm out -> still in
    assert ("remove_from", "module_a") not in _feed(SceneFusion(BINDING, AUTO), frames, _pose(scale=0.25))


def test_switching_geometry_clears_pending_votes_not_state():
    f = SceneFusion(BINDING, AUTO)
    box = det("case_open", 100, 100, 300, 300)
    out = det("red_module", 400, 100, 440, 140)
    _feed(f, [[box]] * 4, _pose())
    f.update(1.0, [box, out], _pose())
    f.update(1.1, [box, out], _pose())  # 2 of k=3 'out' votes in rack mode
    assert f.mode == "rack"
    f.update(1.2, [box, out], None)  # rack lost -> image mode, votes cleared
    assert f.mode == "image" and f.modules["module_a"].state == "in"
    assert not f.update(1.3, [box, out], None)  # would have been the 3rd vote
    assert ("remove_from", "module_a") in [(e.action, e.target) for e in f.update(1.4, [box, out], None)]


def test_held_pose_counts_none_does_not():
    f = SceneFusion(BINDING, AUTO)
    f.update(0.0, [case("open")], _pose("held"))
    assert f.mode == "rack"
    f.update(0.1, [case("open")], _pose("none"))
    assert f.mode == "image"


def test_geometry_setting_validated():
    with pytest.raises(ValueError):
        FusionConfig.from_config({"perception": {"geometry": "floor"}}, {})
    assert FusionConfig.from_config({}, {}).geometry == "image"


def test_rack_containment_is_role_driven_not_red_yellow():
    """Nothing depends on the jar classes or on two modules: any profile's
    container/module classes, any number of modules."""
    b = RoleBinding("tray", "tray_open", "tray_closed",
                    {"m1": "blue_vial", "m2": "green_vial", "m3": "white_vial"})
    f = SceneFusion(b, AUTO)
    tray = det("tray_open", 100, 100, 400, 300)
    inside = [det(c, 150 + 80 * i, 150, 190 + 80 * i, 190) for i, c in enumerate(("blue_vial", "green_vial", "white_vial"))]
    out_green = det("green_vial", 600, 150, 640, 190)
    ev = _feed(f, [[tray] + inside] * 4 + [[tray, inside[0], out_green, inside[2]]] * 5, _pose())
    assert ("open", "tray") in ev and ("remove_from", "m2") in ev
    assert not any(t in ("m1", "m3") for _, t in ev)


# --- operator presence (hands in view) ---------------------------------------------

def _hand_states(f, frames, fps=10.0):
    out = []
    for i, dets in enumerate(frames):
        out += [(round(i / fps, 1), e.value) for e in f.update(i / fps, dets) if isinstance(e, StateEvent)]
    return out


def test_hands_gone_needs_k_of_n_frames_not_one_miss():
    from dataclasses import replace

    b = replace(BINDING, hand_classes=frozenset({"hand_bare", "hand_gloved"}))
    f = SceneFusion(b, FusionConfig(k=3, n=4, hands_k=4, hands_n=5))
    hand = det("hand_bare", 10, 10, 60, 60)
    # a detector blinking on the hand (2 misses) must not read as "left"
    blink = [[hand], [], [], [hand], [hand], [], [hand]]
    assert _hand_states(f, blink) == []
    f2 = SceneFusion(b, FusionConfig(k=3, n=4, hands_k=4, hands_n=5))
    gone_then_back = [[hand]] * 3 + [[]] * 5 + [[det("hand_gloved", 10, 10, 60, 60)]] * 5
    assert [v for _, v in _hand_states(f2, gone_then_back)] == [False, True]


def test_hand_classes_come_from_profile_and_config_can_override():
    from src.perception.fusion import with_hand_classes

    r = resolve(REPO_ROOT / "configs/protocols/bas_specimen_v1.json",
                object_profile=REPO_ROOT / "configs/objects/profile_jar.yaml")
    b = binding_for(r)
    assert b.hand_classes == {"hand_gloved", "hand_bare"}
    assert with_hand_classes(b, {"perception": {"hand_classes": ["operator_glove"]}}).hand_classes == {"operator_glove"}
    assert with_hand_classes(b, {}).hand_classes == b.hand_classes


def test_no_hand_classes_means_presence_not_tracked():
    f = SceneFusion(BINDING, FusionConfig(k=3, n=4))  # BINDING declares none
    assert _hand_states(f, [[]] * 30) == [] and "hands" not in f.states()
