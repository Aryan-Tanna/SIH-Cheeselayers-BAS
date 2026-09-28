"""Min-hold debounce and the workspace filter (live session 2026-09-26:
a 0.8 s open->closed flicker ended the protocol; red chairs outside the
rig were detected as the red module)."""

from dataclasses import replace

import numpy as np
import pytest

from src.perception.detector import Detection
from src.perception.fusion import (
    FusionConfig,
    RoleBinding,
    SceneFusion,
    StateVote,
    workspace_polygon,
)
from src.protocol.loader import REPO_ROOT

BINDING = RoleBinding("container", "case_open", "case_closed",
                      {"module_a": "red_module"}, frozenset({"hand_bare"}))
BOX = (100, 100, 500, 300)


def det(cls, x0, y0, x1, y1, conf=0.9):
    return Detection(cls, conf, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0,
                     ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def case(state):
    return det("case_open" if state == "open" else "case_closed", *BOX)


# --- StateVote.min_hold_s -------------------------------------------------------

def test_min_hold_zero_is_plain_k_of_n():
    v = StateVote("closed", k=2, n=3, stale_s=10)
    assert v.observe(0.0, "open") is None
    assert v.observe(0.1, "open") == "open"


def test_short_flicker_is_not_confirmed_with_min_hold():
    v = StateVote("open", k=3, n=4, stale_s=10, min_hold_s=1.5)
    # 0.8 s of "closed" votes (k-of-n met at 0.2 s), then open again
    out = [v.observe(t, "closed") for t in (0.0, 0.1, 0.2, 0.4, 0.6, 0.8)]
    out += [v.observe(t, "open") for t in (0.9, 1.0, 1.1)]
    assert all(o is None for o in out) and v.state == "open"


def test_real_change_is_confirmed_once_held():
    v = StateVote("open", k=3, n=4, stale_s=10, min_hold_s=1.5)
    got = [(t, v.observe(t, "closed")) for t in np.arange(0.0, 2.01, 0.125)]
    confirmed = [t for t, o in got if o == "closed"]
    assert confirmed and confirmed[0] >= 1.5 and v.state == "closed"


def test_vote_for_current_state_restarts_the_hold_clock():
    v = StateVote("open", k=2, n=4, stale_s=10, min_hold_s=1.0)
    for t in (0.0, 0.5, 0.9):
        v.observe(t, "closed")
    v.observe(0.95, "open")                   # current state reasserts itself
    assert v.observe(1.2, "closed") is None   # clock restarted at 1.2
    assert v.observe(1.9, "closed") is None
    assert v.observe(2.3, "closed") == "closed"


def test_negative_min_hold_rejected():
    with pytest.raises(ValueError):
        StateVote("open", 1, 1, 1.0, min_hold_s=-1)


def test_protocol_not_ended_by_a_flicker():
    """The live failure: a 0.8 s flicker to closed must not emit close."""
    cfg = FusionConfig(k=5, n=8, container_min_hold_s=1.5)
    f = SceneFusion(BINDING, cfg)
    events, t = [], 0.0
    for state, dur in (("closed", 1.0), ("open", 3.0), ("closed", 0.8), ("open", 3.0)):
        end = t + dur
        while t < end:
            events += f.update(t, [case(state)])
            t = round(t + 0.1, 3)
    assert [e.action for e in events if hasattr(e, "action")] == ["open"]


def test_config_parsing():
    rt = {"perception": {"container_min_hold_s": 1.5, "module_min_hold_s": 0.3,
                         "workspace": {"margin_mm": 80, "roi": [0.1, 0.1, 0.9, 0.95]}}}
    c = FusionConfig.from_config(rt, {})
    assert (c.container_min_hold_s, c.module_min_hold_s) == (1.5, 0.3)
    assert c.workspace_margin_mm == 80 and c.workspace_roi == (0.1, 0.1, 0.9, 0.95)
    with pytest.raises(ValueError):
        FusionConfig.from_config({"perception": {"workspace": {"roi": [0.5, 0, 0.4, 1]}}}, {})


# --- workspace filter -----------------------------------------------------------------

def test_image_roi_drops_objects_outside_but_keeps_hands():
    cfg = FusionConfig(k=2, n=3, workspace_roi=(0.0, 0.0, 0.5, 1.0))
    f = SceneFusion(BINDING, cfg)
    far_red = ("red_module", 800, 100, 900, 200)      # right half: outside the region
    hand_far = det("hand_bare", 800, 400, 900, 500)
    events = []
    for i in range(6):
        events += f.update(i * 0.1, [case("open"), det(*far_red), hand_far], frame_size=(1000, 600))
    assert "remove_from" not in [getattr(e, "action", None) for e in events]
    assert f.filtered == 6                               # the far red module, every frame
    assert f.states()["hands"] == "present"             # hands are never filtered


def test_no_frame_size_means_no_image_roi_filtering():
    cfg = FusionConfig(k=2, n=3, workspace_roi=(0.0, 0.0, 0.5, 1.0))
    f = SceneFusion(BINDING, cfg)
    for i in range(4):
        f.update(i * 0.1, [case("open"), det("red_module", 800, 100, 900, 200)])
    assert f.filtered == 0


class _Fit:
    """Identity image->floor mapping for tests (1 px = 1 mm)."""


def test_rack_workspace_filter(monkeypatch):
    import src.perception.fusion as fu

    monkeypatch.setattr(fu, "floor_polygon", lambda fit, pts: np.asarray(pts, dtype=float).reshape(-1, 2))
    cfg = FusionConfig(k=2, n=3, workspace_margin_mm=50)
    f = SceneFusion(BINDING, cfg)
    f.workspace_floor = np.array([[0, 0], [600, 0], [600, 400], [0, 400]], dtype=float)
    pose = type("P", (), {"status": "ok", "fit": _Fit()})()
    inside_red = det("red_module", 150, 150, 250, 250)
    chair = det("red_module", 900, 100, 1000, 200)       # beyond the rig floor
    f.update(0.0, [case("open"), inside_red, chair], rack_pose=pose)
    assert f.filtered == 1
    pose_none = type("P", (), {"status": "none", "fit": None})()
    f.update(0.1, [case("open"), chair], rack_pose=pose_none)   # rack unknown: no rack filtering
    assert f.filtered == 1


def test_workspace_polygon_from_the_real_rack_layout():
    from src.perception.rack import load_rack_config

    rc = load_rack_config(REPO_ROOT / "configs/rack.yaml")
    if not rc.calibrated:
        pytest.skip("rack layout not calibrated")
    poly = workspace_polygon(rc, 100.0)
    xs, ys = poly[:, 0], poly[:, 1]
    # markers span ~-377..5 mm x 0..266 mm (+ half marker); + 100 mm margin
    assert xs.min() < -450 and xs.max() > 100 and ys.min() < -100 and ys.max() > 350
    assert workspace_polygon(replace(rc, layout={}), 100.0) is None
