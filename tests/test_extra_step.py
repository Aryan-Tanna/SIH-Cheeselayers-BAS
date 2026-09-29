"""no_extra_steps (PS 26174: "alert when ... an out of sequence step is
added") and `optional` steps, the protocol's way to ALLOW an extra action."""

import json
from pathlib import Path

from scripts.validate_protocol import validate
from src.protocol.editing import build, flatten, load_raw
from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent
from src.protocol.loader import resolve
from src.runtime.announcer import Announcer, AnnouncerSettings
from src.runtime.clock import VirtualClock

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"

A_DONE = [
    (1.0, dict(action="open", target="container")),
    (2.0, dict(action="remove_from", target="module_a", source="container")),
    (3.0, dict(action="open", target="module_a")),
    (4.0, dict(action="move_to_zone", target="module_a.lid", zone="stow_zone")),
    (5.0, dict(action="close", target="module_a")),
    (6.0, dict(action="place_into", target="module_a", dest="container")),
]
B_DONE = [
    (7.0, dict(action="remove_from", target="module_b", source="container")),
    (8.0, dict(action="open", target="module_b")),
    (9.0, dict(action="move_to_zone", target="module_b.lid", zone="stow_zone")),
    (10.0, dict(action="close", target="module_b")),
    (11.0, dict(action="place_into", target="module_b", dest="container")),
]


def _engine(path=PROTOCOL):
    clock = VirtualClock()
    return ProtocolEngine(resolve(path, DEFAULTS), clock=clock), clock


def _run(eng, clock, events):
    for t, kw in events:
        clock.advance_to(t)
        eng.process(ActionEvent(ts=t, **kw))


def _tick(eng, clock, t):
    clock.advance_to(t)
    eng.check_timeouts(t)


def _violations(eng, code):
    return [e for e in eng.out if e.event_type == "violation" and e.violation_type == code]


def test_repeating_a_finished_step_is_an_extra_step_and_the_world_state_follows():
    eng, clock = _engine()
    _run(eng, clock, A_DONE + B_DONE + [(12.0, dict(action="remove_from", target="module_a", source="container"))])
    _tick(eng, clock, 14.9)
    assert _violations(eng, "extra_step") == []  # still inside settle_s (3 s)
    _tick(eng, clock, 15.1)
    extra = _violations(eng, "extra_step")
    assert len(extra) == 1
    assert extra[0].target == "module_a" and extra[0].extra["actions"][0]["repeat_of"] == "remove_a"
    assert extra[0].severity == "caution" and extra[0].root_cause_id == "extra:module_a"
    # the module really is out now: sealing the container flags it
    _run(eng, clock, [(16.0, dict(action="close", target="container"))])
    assert [v.target for v in _violations(eng, "module_not_returned")] == ["module_a"]


def test_duplicate_report_of_a_state_already_true_is_not_an_extra_step():
    eng, clock = _engine()
    _run(eng, clock, A_DONE[:1] + [(1.5, dict(action="open", target="container"))])
    assert _violations(eng, "extra_step") == []
    assert eng.out[-1].event_type == "unmatched_action"


def test_wrong_object_still_wins_when_one_due_step_matches_the_action():
    eng, clock = _engine()
    _run(eng, clock, A_DONE + [(7.0, dict(action="remove_from", target="module_a", source="container"))])
    assert len(_violations(eng, "wrong_object")) == 1
    assert _violations(eng, "extra_step") == []


def test_undone_within_settle_is_logged_not_alerted():
    """Detector jitter shape seen on real clips: cap closed -> open -> closed
    within ~2 s (resting on the jar), jar returned -> out -> in (hover)."""
    eng, clock = _engine()
    _run(eng, clock, A_DONE + B_DONE + [
        (12.0, dict(action="remove_from", target="module_a", source="container")),
        (14.0, dict(action="place_into", target="module_a", dest="container")),
        (14.5, dict(action="open", target="module_b")),
        (15.0, dict(action="move_to_zone", target="module_b.lid", zone="stow_zone")),
        (16.0, dict(action="close", target="module_b")),
    ])
    _tick(eng, clock, 30.0)
    assert _violations(eng, "extra_step") == []
    reverted = [e for e in eng.out if "extra_reverted" in e.extra]
    assert [e.target for e in reverted] == ["module_a", "module_b"]


def test_several_extra_actions_on_one_object_are_one_alert():
    eng, clock = _engine()
    _run(eng, clock, A_DONE + B_DONE + [
        (12.0, dict(action="remove_from", target="module_a", source="container")),
        (12.5, dict(action="open", target="module_a")),
    ])
    _tick(eng, clock, 20.0)
    extra = _violations(eng, "extra_step")
    assert len(extra) == 1 and [a["action"] for a in extra[0].extra["actions"]] == ["remove_from", "open"]


def test_pause_does_not_count_toward_settle():
    eng, clock = _engine()
    _run(eng, clock, A_DONE + B_DONE + [(12.0, dict(action="remove_from", target="module_a", source="container"))])
    eng.pause_session(13.0)
    _tick(eng, clock, 60.0)
    eng.resume_session(60.0)
    _tick(eng, clock, 61.5)  # 1 s before the pause + 1.5 s after = 2.5 s
    assert _violations(eng, "extra_step") == []
    _tick(eng, clock, 62.5)
    assert len(_violations(eng, "extra_step")) == 1


def test_rule_switched_off_logs_silently(tmp_path):
    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["constraints"] = [{"id": "no_extra_steps", "disabled": True, "basis": "procedural_integrity"}]
    p = tmp_path / "off.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    eng, clock = _engine(p)
    _run(eng, clock, A_DONE + B_DONE + [(12.0, dict(action="remove_from", target="module_a", source="container"))])
    _tick(eng, clock, 30.0)
    assert _violations(eng, "extra_step") == []
    assert any(e.event_type == "unmatched_action" and e.target == "module_a" for e in eng.out)


def _with_reinspection(tmp_path):
    """v1 plus an OPTIONAL second look at module A after it is returned."""
    raw = load_raw(PROTOCOL)
    raw["protocol_id"] = "reinspect_test"
    rows = flatten(raw)
    rows = build(raw, rows)
    handle_a = next(n for n in rows["steps"] if n["id"] == "handle_a")
    handle_a["steps"] += [
        {"id": "reinspect_a", "action": "remove_from", "target": "module_a", "source": "container",
         "after": ["return_a"], "optional": True, "prompt": "You may take the first module out again."},
        {"id": "rereturn_a", "action": "place_into", "target": "module_a", "dest": "container",
         "after": ["reinspect_a"], "optional": True, "prompt": "Return the first module."},
    ]
    p = tmp_path / "reinspect_test.json"
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    assert validate(p, DEFAULTS) == []
    return p


def test_an_optional_step_allows_the_action(tmp_path):
    eng, clock = _engine(_with_reinspection(tmp_path))
    _run(eng, clock, A_DONE + [
        (6.5, dict(action="remove_from", target="module_a", source="container")),
        (6.8, dict(action="place_into", target="module_a", dest="container")),
    ] + B_DONE + [(12.0, dict(action="close", target="container"))])
    assert [e for e in eng.out if e.event_type == "violation"] == []
    assert {"reinspect_a", "rereturn_a"} <= eng.complete


def test_an_optional_step_not_done_is_not_missed(tmp_path):
    eng, clock = _engine(_with_reinspection(tmp_path))
    _run(eng, clock, A_DONE + B_DONE + [(12.0, dict(action="close", target="container"))])
    assert [e for e in eng.out if e.event_type == "violation"] == []


def test_optional_step_is_never_spoken_as_the_next_step(tmp_path):
    path = _with_reinspection(tmp_path)
    resolved = resolve(path, DEFAULTS)
    eng, clock = _engine(path)
    ann = Announcer(resolved, AnnouncerSettings())
    spoken = []
    seen = 0
    for t, kw in A_DONE:
        clock.advance_to(t)
        eng.process(ActionEvent(ts=t, **kw))
        batch, seen = eng.out[seen:], len(eng.out)
        spoken += [r.step_id for r in ann.plan(batch) if r.kind == "prompt"]
    assert "reinspect_a" not in spoken
    assert ann.current_step() == "remove_b"


def test_editor_round_trips_optional(tmp_path):
    raw = load_raw(_with_reinspection(tmp_path))
    rows = flatten(raw)
    assert next(r for r in rows if r.id == "reinspect_a").optional is True
    assert next(r for r in rows if r.id == "remove_a").optional is False
    assert build(raw, rows) == raw


def test_nothing_is_alerted_after_the_experiment_ends():
    """Packing up after "Experiment complete." must not be the last thing heard."""
    eng, clock = _engine()
    _run(eng, clock, A_DONE + B_DONE + [
        (12.0, dict(action="close", target="container")),
        (15.0, dict(action="open", target="container")),
        (16.0, dict(action="remove_from", target="module_a", source="container")),
    ])
    _tick(eng, clock, 40.0)
    assert [e for e in eng.out if e.event_type == "violation"] == []
    assert "after the procedure ended" in eng.out[-1].message


def test_settle_window_is_editable_and_the_engine_uses_it(tmp_path):
    import yaml

    from src.protocol.editing import apply_rule_edit, rule_rows, save_validated

    defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    raw = load_raw(PROTOCOL)
    row = next(r for r in rule_rows(defaults, raw) if r.id == "no_extra_steps")
    assert row.timer_key == "settle_s" and row.timer == 3.0
    out = tmp_path / "settle.json"
    assert save_validated(apply_rule_edit(raw, defaults, "no_extra_steps", timer=8.0), out, DEFAULTS) == []
    eng, clock = _engine(out)
    _run(eng, clock, A_DONE + B_DONE + [(12.0, dict(action="remove_from", target="module_a", source="container"))])
    _tick(eng, clock, 19.0)
    assert _violations(eng, "extra_step") == []  # 7 s < 8 s
    _tick(eng, clock, 20.5)
    assert len(_violations(eng, "extra_step")) == 1
