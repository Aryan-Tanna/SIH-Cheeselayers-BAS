from pathlib import Path

from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent, AnomalyEvent, OperatorOverrideEvent
from src.protocol.loader import resolve
from src.runtime.clock import VirtualClock

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"


def _engine():
    clock = VirtualClock()
    return ProtocolEngine(resolve(PROTOCOL, DEFAULTS), clock=clock), clock


def _act(engine, clock, t, action, target, **kw):
    clock.advance_to(t)
    engine.process(ActionEvent(ts=t, action=action, target=target, **kw))


def _types(engine):
    return [e.event_type for e in engine.out]


def _lid_open(engine, clock):
    _act(engine, clock, 1.0, "open", "container")
    _act(engine, clock, 2.0, "remove_from", "module_a", source="container")
    _act(engine, clock, 3.0, "open", "module_a")


def test_events_while_paused_are_ignored_and_counted():
    engine, clock = _engine()
    _lid_open(engine, clock)
    engine.pause_session(5.0)
    _act(engine, clock, 6.0, "move_to_zone", "module_a.lid", zone="stow_zone")
    assert "stow_a_lid" not in engine.complete
    engine.resume_session(10.0)
    resumed = [e for e in engine.out if e.event_type == "session_resumed"][0]
    assert resumed.extra["ignored_events"] == 1
    assert resumed.extra["paused_for_s"] == 5.0


def test_timeouts_frozen_during_pause():
    engine, clock = _engine()
    _lid_open(engine, clock)  # lid detached at t=3, 12 s timeout
    engine.pause_session(5.0)
    engine.check_timeouts(100.0)
    assert "violation" not in _types(engine)


def test_timer_resumes_where_it_stopped():
    engine, clock = _engine()
    _lid_open(engine, clock)  # 2 s elapsed at pause
    engine.pause_session(5.0)
    engine.resume_session(50.0)
    engine.check_timeouts(59.0)  # 2 + 9 = 11 s unpaused
    assert "violation" not in _types(engine)
    engine.check_timeouts(61.0)  # 13 s unpaused
    v = [e for e in engine.out if e.event_type == "violation"]
    assert [e.violation_type for e in v] == ["lid_unstowed"]


def test_step_after_resume_completes_normally():
    engine, clock = _engine()
    _lid_open(engine, clock)
    engine.pause_session(5.0)
    engine.resume_session(40.0)
    _act(engine, clock, 41.0, "move_to_zone", "module_a.lid", zone="stow_zone")
    assert "stow_a_lid" in engine.complete
    assert "violation" not in _types(engine)


def test_pause_and_resume_are_idempotent():
    engine, _ = _engine()
    engine.pause_session(1.0)
    engine.pause_session(2.0)
    engine.resume_session(3.0)
    engine.resume_session(4.0)
    assert _types(engine).count("session_paused") == 1
    assert _types(engine).count("session_resumed") == 1


def test_operator_override_is_logged_even_while_paused():
    engine, _ = _engine()
    engine.pause_session(1.0)
    engine.process(OperatorOverrideEvent(ts=2.0, note="manual"))
    assert "operator_override" in _types(engine)


def test_anomaly_event_changes_no_state():
    engine, clock = _engine()
    _act(engine, clock, 1.0, "open", "container")
    before = (set(engine.complete), engine.satisfiable_steps())
    engine.process(AnomalyEvent(ts=2.0, label="pen"))
    assert (set(engine.complete), engine.satisfiable_steps()) == before
    a = engine.out[-1]
    assert a.event_type == "anomaly" and a.root_cause_id == "anomaly:foreign_object"
    assert a.target == "pen"


def test_action_on_undeclared_object_is_anomaly_not_wrong_object():
    engine, clock = _engine()
    _act(engine, clock, 1.0, "open", "container")
    # remove_a / remove_b are satisfiable; a "remove_from" on a pen would
    # otherwise be judged against them
    _act(engine, clock, 2.0, "remove_from", "pen", source="container")
    assert engine.out[-1].event_type == "anomaly"
    assert "violation" not in _types(engine)
    _act(engine, clock, 3.0, "remove_from", "module_a", source="container")
    assert "remove_a" in engine.complete


def test_out_of_order_carries_unmet_prerequisites():
    engine, clock = _engine()
    _lid_open(engine, clock)
    _act(engine, clock, 4.0, "close", "module_a")
    v = [e for e in engine.out if e.event_type == "violation"][0]
    assert v.violation_type == "out_of_order"
    assert v.extra["unmet"] == ["stow_a_lid"]


def test_operator_command_logged():
    engine, _ = _engine()
    engine.note_operator_command(1.0, "quiet_mode")
    assert engine.out[-1].event_type == "operator_command"
    assert engine.out[-1].message == "quiet_mode"
