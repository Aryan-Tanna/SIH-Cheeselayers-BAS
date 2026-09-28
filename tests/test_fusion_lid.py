"""Module lid (screw cap) -> open / stow / close ActionEvents. Tuned on
train1-3 (2026-09-28): with the cap off, v5 also fires the lid class on
the open jar mouth, so "detached" = some lid box off the body."""

import pytest

from src.perception.detector import Detection
from src.perception.fusion import FusionConfig, RoleBinding, SceneFusion, binding_for
from src.protocol.loader import resolve, REPO_ROOT

BINDING = RoleBinding("container", "case_open", "case_closed",
                      {"module_a": "red_module"}, frozenset({"hand_bare"}),
                      lids={"module_a": "red_lid"}, lid_zones={"module_a": "stow_zone"})
CFG = FusionConfig(k=2, n=3, lid_k=3, lid_n=5, lid_min_hold_s=0.3)


def det(cls, x0, y0, x1, y1, conf=0.9):
    return Detection(cls, conf, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0,
                     ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


CASE = det("case_open", 0, 0, 1000, 600)
BODY = det("red_module", 1100, 100, 1300, 300)       # outside the case: removed
LID_ON = det("red_lid", 1120, 100, 1280, 160)
LID_OFF = det("red_lid", 1400, 100, 1500, 200)       # in the other hand
MOUTH = det("red_lid", 1130, 110, 1270, 170, 0.5)    # false lid on the open jar mouth


def run(frames, binding=BINDING, cfg=CFG):
    f, out, t = SceneFusion(binding, cfg), [], 0.0
    for dets, dur in frames:
        end = t + dur
        while t < end - 1e-9:
            out += [e for e in f.update(t, [CASE, *dets]) if hasattr(e, "action") and e.target.startswith("module_a")
                    and e.action != "remove_from"]
            t = round(t + 0.1, 3)
    return f, out


def test_detach_stow_reattach():
    f, ev = run([([BODY, LID_ON], 1.0), ([BODY, LID_OFF, MOUTH], 1.5), ([BODY, LID_ON], 1.0)])
    assert [(e.action, e.target, e.zone) for e in ev] == [
        ("open", "module_a", None), ("move_to_zone", "module_a.lid", "stow_zone"),
        ("close", "module_a", None)]
    assert f.states()["module_a.lid"] == "on"
    opened, closed = ev[0].ts, ev[2].ts
    assert 1.2 <= opened <= 1.6 and 2.7 <= closed <= 3.1


def test_false_lid_on_open_mouth_does_not_reattach():
    _, ev = run([([BODY, LID_ON], 1.0), ([BODY, LID_OFF, MOUTH], 3.0)])
    assert [e.action for e in ev] == ["open", "move_to_zone"]


def test_isolated_separate_lid_frames_are_ignored():
    # train2 20.4 / 20.8 s: two lone "separate lid" frames, 0.4 s apart
    frames = [([BODY, LID_ON], 1.0), ([BODY, LID_ON, LID_OFF], 0.1), ([BODY, LID_ON], 0.3),
              ([BODY, LID_ON, LID_OFF], 0.1), ([BODY, LID_ON], 1.0)]
    assert run(frames)[1] == []


def test_short_detach_below_hold_is_ignored():
    frames = [([BODY, LID_ON], 1.0), ([BODY, LID_OFF], 0.3), ([BODY, LID_ON], 1.0)]
    assert run(frames, cfg=FusionConfig(k=2, n=3, lid_k=2, lid_n=3, lid_min_hold_s=0.5))[1] == []


def test_no_body_or_no_lid_is_no_evidence():
    _, ev = run([([BODY, LID_ON], 0.5), ([LID_OFF], 1.0), ([BODY], 1.0), ([BODY, LID_ON], 0.5)])
    assert ev == []


def test_lid_left_out_of_view_is_not_stowed_before_it_is_seen():
    """Stow needs the detached lid IN VIEW; it is emitted once, per detach."""
    f, ev = run([([BODY, LID_ON], 1.0), ([BODY, LID_OFF], 1.0), ([BODY], 1.0),
                 ([BODY, LID_OFF], 1.0)])
    assert [e.action for e in ev] == ["open", "move_to_zone"]


def test_no_stow_zone_in_protocol_means_no_stow_event():
    from dataclasses import replace

    _, ev = run([([BODY, LID_ON], 1.0), ([BODY, LID_OFF], 1.0)], binding=replace(BINDING, lid_zones={}))
    assert [e.action for e in ev] == ["open"]


def test_binding_from_profiles():
    P = REPO_ROOT / "configs/protocols/bas_specimen_v1.json"
    mixed = binding_for(resolve(P, object_profile="configs/objects/profile_mixed.yaml"))
    assert mixed.lids == {"module_a": "red_lid"} and mixed.lid_zones == {"module_a": "stow_zone"}
    jar = binding_for(resolve(P, object_profile="configs/objects/profile_jar.yaml"))
    assert jar.lids == {"module_a": "red_lid", "module_b": "yellow_lid"}
    rect = binding_for(resolve(P, object_profile="configs/objects/profile_rect.yaml"))
    assert rect.lids == {} and rect.lid_zones == {}


def test_lid_config_parsing():
    c = FusionConfig.from_config({"perception": {"lid": {"attach_overlap": 0.5, "k": 2, "n": 4,
                                                          "min_hold_s": 0.6}}}, {})
    assert (c.lid_attach_overlap, c.lid_k, c.lid_n, c.lid_min_hold_s) == (0.5, 2, 4, 0.6)
    with pytest.raises(ValueError):
        SceneFusion(BINDING, FusionConfig(lid_k=4, lid_n=3))
