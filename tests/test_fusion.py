import pytest

from src.perception.detector import Detection
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
