"""step_time_limit: a per-step `timeout_s`, alerted once if the step is
not done that long after it is DUE. Held under one_module_at_a_time so a
free-order protocol never alarms on a correct run; frozen by pause."""

import json
from pathlib import Path

from scripts.validate_protocol import validate
from src.protocol.editing import build, flatten, load_raw
from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent
from src.protocol.loader import resolve
from src.runtime.clock import VirtualClock

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"

MODULE_A = [
    (2.0, dict(action="remove_from", target="module_a", source="container")),
    (3.0, dict(action="open", target="module_a")),
    (4.0, dict(action="move_to_zone", target="module_a.lid", zone="stow_zone")),
    (5.0, dict(action="close", target="module_a")),
]


def _protocol(tmp_path, limits=None, constraints=None, concurrency=None):
    """bas_specimen_v1 with {step_id: timeout_s} added."""
    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["protocol_id"] = "time_limit_test"

    def walk(nodes):
        for n in nodes:
            if n["id"] in (limits or {}):
                n["timeout_s"] = limits[n["id"]]
            if n.get("type") == "group":
                if concurrency:
                    n["concurrency"] = concurrency
                walk(n["steps"])

    walk(raw["steps"])
    if constraints:
        raw["constraints"] = constraints
    path = tmp_path / "p.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


def _engine(path):
    clock = VirtualClock()
    return ProtocolEngine(resolve(path, DEFAULTS), clock=clock), clock


def _send(eng, clock, t, **kw):
    clock.advance_to(t)
    eng.process(ActionEvent(ts=t, **kw))


def _tick(eng, clock, t):
    clock.advance_to(t)
    eng.check_timeouts(t)


def _overdue(eng):
    return [e for e in eng.out if e.event_type == "violation" and e.violation_type == "step_overdue"]


def test_protocol_without_limits_never_fires():
    eng, clock = _engine(PROTOCOL)
    for t in range(1, 600, 5):
        _tick(eng, clock, float(t))
    assert _overdue(eng) == []


def test_fires_once_after_the_limit_not_before(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"open_container": 10}))
    _tick(eng, clock, 9.5)
    assert _overdue(eng) == []
    _tick(eng, clock, 10.5)
    _tick(eng, clock, 40.0)
    fired = _overdue(eng)
    assert len(fired) == 1
    v = fired[0]
    assert v.step_id == "open_container" and v.target == "container"
    assert v.root_cause_id == "open_container.time_limit" and v.severity == "caution"
    assert v.extra["time_limit_s"] == 10


def test_done_in_time_never_fires(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"open_container": 10}))
    _send(eng, clock, 5.0, action="open", target="container")
    _tick(eng, clock, 60.0)
    assert _overdue(eng) == []


def test_clock_starts_when_the_step_becomes_due(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"remove_a": 10}))
    _tick(eng, clock, 50.0)  # container still closed: remove_a not due yet
    _send(eng, clock, 50.0, action="open", target="container")
    _tick(eng, clock, 59.0)
    assert _overdue(eng) == []
    _tick(eng, clock, 61.0)
    assert [v.step_id for v in _overdue(eng)] == ["remove_a"]


def test_held_while_the_other_module_is_being_handled(tmp_path):
    """Free order: remove_b is due once the container opens, but the
    operator is correctly working on module A -- no alarm for B."""
    eng, clock = _engine(_protocol(tmp_path, {"remove_b": 10}))
    _send(eng, clock, 1.0, action="open", target="container")  # remove_b due, clock runs 1 -> 2
    for t, kw in MODULE_A:
        _send(eng, clock, t, **kw)
    _tick(eng, clock, 40.0)  # A still out: B held
    assert _overdue(eng) == []
    _send(eng, clock, 41.0, action="place_into", target="module_a", dest="container")
    _tick(eng, clock, 49.0)  # 1 s before A was taken + 8 s since = 9 s
    assert _overdue(eng) == []
    _tick(eng, clock, 51.0)
    assert [v.step_id for v in _overdue(eng)] == ["remove_b"]


def test_not_held_when_modules_may_be_out_together(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"remove_b": 10}, concurrency="permitted"))
    _send(eng, clock, 1.0, action="open", target="container")
    for t, kw in MODULE_A:
        _send(eng, clock, t, **kw)
    _tick(eng, clock, 12.0)
    assert [v.step_id for v in _overdue(eng)] == ["remove_b"]


def test_pause_freezes_the_clock(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"open_container": 10}))
    _tick(eng, clock, 5.0)
    clock.advance_to(5.0)
    eng.pause_session(5.0)
    _tick(eng, clock, 100.0)
    eng.resume_session(100.0)
    _tick(eng, clock, 104.0)
    assert _overdue(eng) == []
    _tick(eng, clock, 106.0)
    assert len(_overdue(eng)) == 1


def test_rule_switched_off_never_fires(tmp_path):
    path = _protocol(tmp_path, {"open_container": 10},
                     constraints=[{"id": "step_time_limit", "disabled": True, "basis": "procedural_integrity"}])
    eng, clock = _engine(path)
    _tick(eng, clock, 60.0)
    assert _overdue(eng) == []


def test_nothing_fires_after_the_experiment_ends(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"remove_b": 10}))
    _send(eng, clock, 1.0, action="open", target="container")
    _send(eng, clock, 1.5, action="close", target="container")  # terminal step: run over
    _tick(eng, clock, 100.0)
    assert _overdue(eng) == []


def test_hot_reload_keeps_elapsed_time_and_takes_the_new_limit(tmp_path):
    eng, clock = _engine(_protocol(tmp_path, {"open_container": 100}))
    _tick(eng, clock, 20.0)
    eng.reload_protocol(resolve(_protocol(tmp_path, {"open_container": 25}), DEFAULTS))
    _tick(eng, clock, 24.0)
    assert _overdue(eng) == []
    _tick(eng, clock, 26.0)
    assert len(_overdue(eng)) == 1


def test_validator_accepts_a_step_limit_and_refuses_what_would_not_be_enforced(tmp_path):
    assert validate(_protocol(tmp_path, {"remove_a": 30}), DEFAULTS) == []

    zero = validate(_protocol(tmp_path, {"remove_a": 0}), DEFAULTS)
    assert any("must be more than 0" in f.message for f in zero)

    new_rule = validate(_protocol(tmp_path, constraints=[
        {"id": "my_rule", "type": "timeout", "violation_code": "lid_unstowed", "basis": "procedural_integrity"}]),
        DEFAULTS)
    assert any("my_rule" in f.message and "never enforce" in f.message for f in new_rule)

    required = validate(_protocol(tmp_path, concurrency="required"), DEFAULTS)
    assert any("'required' is not enforced" in f.message for f in required)

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["steps"][0]["min_duration_s"] = 3
    raw["steps"][0]["requires"] = ["module_a.sealed"]
    p = tmp_path / "inert.json"
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    msgs = [f.message for f in validate(p, DEFAULTS)]
    assert any("'min_duration_s' is not enforced" in m for m in msgs)
    assert any("'requires' is not enforced" in m for m in msgs)


def test_editor_round_trips_time_limit_and_out_together(tmp_path):
    raw = load_raw(_protocol(tmp_path, {"remove_a": 30}))
    rows = flatten(raw)
    step = next(r for r in rows if r.id == "remove_a")
    assert step.time_limit == 30
    grp = next(r for r in rows if r.id == "handle_b")
    assert grp.concurrency == "forbidden"
    grp.concurrency = "permitted"
    step.time_limit = None
    out = build(raw, rows)
    handle_b = next(n for n in out["steps"] if n["id"] == "handle_b")
    handle_a = next(n for n in out["steps"] if n["id"] == "handle_a")
    assert handle_b["concurrency"] == "permitted" and "concurrency" not in handle_a
    assert "timeout_s" not in next(s for s in handle_a["steps"] if s["id"] == "remove_a")
    assert build(out, flatten(out)) == out
