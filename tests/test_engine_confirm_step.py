"""Operator confirmation ("Hey BAS, next step"): credit a step the camera
missed, without ever letting it skip ahead."""
from pathlib import Path

from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent
from src.protocol.loader import resolve
from src.runtime.clock import VirtualClock

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"


def _engine():
    clock = VirtualClock()
    return ProtocolEngine(resolve(PROTOCOL, DEFAULTS), clock=clock, operator="op1"), clock


def test_confirm_due_step_completes_it_and_logs_override():
    engine, _ = _engine()
    assert engine.confirm_step(1.0, "open_container", note="voice: next step")
    assert "open_container" in engine.complete
    override = [e for e in engine.out if e.event_type == "operator_override"]
    done = [e for e in engine.out if e.event_type == "step_complete"]
    assert override[0].step_id == "open_container" and override[0].operator == "op1"
    assert done[0].status == "operator_confirmed"
    # the steps it unlocks are offered, same as after a seen action
    assert "remove_a" in engine.satisfiable_steps()


def test_cannot_confirm_a_step_that_is_not_due():
    engine, _ = _engine()
    assert not engine.confirm_step(1.0, "close_container")
    assert not engine.confirm_step(1.0, "remove_a")   # container not open yet
    assert engine.complete == set()
    assert not any(e.event_type == "operator_override" for e in engine.out)


def test_cannot_confirm_while_paused():
    engine, _ = _engine()
    engine.pause_session(0.5)
    assert not engine.confirm_step(1.0, "open_container")
    assert "open_container" not in engine.complete


def test_confirm_applies_state_effect_so_timers_stay_honest():
    # Confirming "open module A's lid" must start the lid-stow clock exactly
    # as a seen action would -- otherwise lid_unstowed could never fire.
    engine, clock = _engine()
    for t, sid in [(1.0, "open_container"), (2.0, "remove_a"), (3.0, "open_a_lid")]:
        clock.advance_to(t)
        assert engine.confirm_step(t, sid)
    engine.check_timeouts(3.0 + 3600.0)
    assert any(e.violation_type == "lid_unstowed" for e in engine.out)


def test_confirmed_and_seen_steps_mix():
    engine, clock = _engine()
    assert engine.confirm_step(1.0, "open_container")
    clock.advance_to(2.0)
    engine.process(ActionEvent(ts=2.0, action="remove_from", target="module_a", source="container"))
    statuses = {e.step_id: e.status for e in engine.out if e.event_type == "step_complete"}
    assert statuses == {"open_container": "operator_confirmed", "remove_a": "complete"}


def test_late_sighting_of_confirmed_step_is_not_judged():
    # Operator confirms "remove module A", then the camera sees it late. That
    # must not become wrong_object (module B's removal is also due) or any
    # other violation -- just a logged note.
    engine, clock = _engine()
    engine.confirm_step(1.0, "open_container")
    engine.confirm_step(2.0, "remove_a")
    n = len(engine.out)
    clock.advance_to(3.0)
    engine.process(ActionEvent(ts=3.0, action="remove_from", target="module_a", source="container"))
    new = engine.out[n:]
    assert [e.event_type for e in new] == ["unmatched_action"]
    assert new[0].step_id == "remove_a"
