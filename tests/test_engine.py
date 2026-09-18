from pathlib import Path

from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent, OperatorOverrideEvent
from src.protocol.loader import load_yaml, resolve
from src.runtime.clock import VirtualClock

PROTOCOL = Path("configs/protocols/bas_specimen_v1.json")
DEFAULTS = Path("configs/defaults.yaml")


def make_engine(protocol_path=PROTOCOL):
    clock = VirtualClock()
    r = resolve(protocol_path, DEFAULTS)
    return ProtocolEngine(r, clock=clock), clock


def send(engine, clock, t, **kwargs):
    clock.advance_to(t)
    engine.process(ActionEvent(ts=t, **kwargs))


def violations(engine, code=None):
    out = [e for e in engine.out if e.event_type == "violation"]
    if code:
        out = [e for e in out if e.violation_type == code]
    return out


def test_clean_run_produces_zero_violations():
    eng, clock = make_engine()
    events = [
        (1.0, dict(action="open", target="container")),
        (2.0, dict(action="remove_from", target="module_a", source="container")),
        (3.0, dict(action="open", target="module_a")),
        (4.0, dict(action="move_to_zone", target="module_a.lid", zone="stow_zone")),
        (5.0, dict(action="close", target="module_a")),
        (6.0, dict(action="place_into", target="module_a", dest="container")),
        (7.0, dict(action="remove_from", target="module_b", source="container")),
        (8.0, dict(action="open", target="module_b")),
        (9.0, dict(action="move_to_zone", target="module_b.lid", zone="stow_zone")),
        (10.0, dict(action="close", target="module_b")),
        (11.0, dict(action="place_into", target="module_b", dest="container")),
        (12.0, dict(action="close", target="container")),
    ]
    for t, kwargs in events:
        send(eng, clock, t, **kwargs)
    assert violations(eng) == []
    complete_steps = {e.step_id for e in eng.out if e.event_type == "step_complete"}
    assert complete_steps == set(eng.parsed.order)


def test_out_of_order_when_prereq_unmet_but_action_still_completes():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="module_a")
    v = violations(eng, "out_of_order")
    assert len(v) == 1
    assert v[0].root_cause_id == "open_a_lid"
    # Operator authority: the action still happened.
    assert "open_a_lid" in eng.complete


def test_mutual_exclusion_breach_when_second_module_taken_out():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="remove_from", target="module_b", source="container")
    v = violations(eng, "mutual_exclusion_breach")
    assert len(v) == 1
    assert v[0].target == "module_b"
    assert v[0].root_cause_id == "one_module_at_a_time"


def test_module_not_sealed_when_returned_open():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="open", target="module_a")
    send(eng, clock, 4.0, action="place_into", target="module_a", dest="container")
    v = violations(eng, "module_not_sealed")
    assert len(v) == 1
    assert v[0].root_cause_id == "module_a"


def test_module_not_returned_when_container_closed_with_module_out():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="close", target="container")
    v = violations(eng, "module_not_returned")
    assert len(v) == 1
    assert v[0].root_cause_id == "module_a"


def test_lid_unstowed_timeout_fires_after_configured_seconds():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="open", target="module_a")  # lid detached at t=3
    clock.advance_to(16.0)
    eng.check_timeouts(16.0)
    v = violations(eng, "lid_unstowed")
    assert len(v) == 1
    assert v[0].target == "module_a"


def test_lid_unstowed_does_not_fire_if_stowed_in_time():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="open", target="module_a")
    send(eng, clock, 5.0, action="move_to_zone", target="module_a.lid", zone="stow_zone")
    clock.advance_to(20.0)
    eng.check_timeouts(20.0)
    assert violations(eng, "lid_unstowed") == []


def test_hard_ordering_guard_blocks_remove_from_closed_container():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="remove_from", target="module_a", source="container")
    anomalies = [e for e in eng.out if e.event_type == "engine_anomaly"]
    assert len(anomalies) == 1
    assert "remove_a" not in eng.complete


def test_hard_ordering_guard_blocks_stow_before_detach():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="move_to_zone", target="module_a.lid", zone="stow_zone")
    anomalies = [e for e in eng.out if e.event_type == "engine_anomaly"]
    assert len(anomalies) == 1
    assert "stow_a_lid" not in eng.complete


def test_skip_detected_at_sink_for_never_completed_required_step():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="open", target="module_a")
    send(eng, clock, 4.0, action="close", target="module_a")  # stow_a_lid skipped
    send(eng, clock, 5.0, action="place_into", target="module_a", dest="container")
    send(eng, clock, 6.0, action="remove_from", target="module_b", source="container")
    send(eng, clock, 7.0, action="open", target="module_b")
    send(eng, clock, 8.0, action="move_to_zone", target="module_b.lid", zone="stow_zone")
    send(eng, clock, 9.0, action="close", target="module_b")
    send(eng, clock, 10.0, action="place_into", target="module_b", dest="container")
    send(eng, clock, 11.0, action="close", target="container")
    v = violations(eng, "skip")
    assert {x.root_cause_id for x in v} == {"stow_a_lid"}


def test_wrong_object_when_exactly_one_satisfiable_step_of_that_action():
    """With explicit intra-group after chains, remove_a and remove_b are
    the only actions satisfiable right after open_container — reaching
    for module_a a second time, after it's already been removed, leaves
    remove_b as the sole satisfiable remove_from step."""
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="remove_from", target="module_a", source="container")  # already complete -> no match
    v = violations(eng, "wrong_object")
    assert len(v) == 1
    assert v[0].root_cause_id == "remove_b"


def test_conditional_step_skipped_silently_for_no_lid_profile():
    r = resolve(PROTOCOL, DEFAULTS)
    r.parsed.object_profile = load_yaml("configs/objects/profile_rect.yaml")
    clock = VirtualClock()
    eng = ProtocolEngine(r, clock=clock)
    assert "open_a_lid" in eng.skipped
    assert "stow_a_lid" in eng.skipped
    assert "close_a_lid" in eng.skipped
    # Skipped steps are not violations, not logged as missed.
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="place_into", target="module_a", dest="container")
    send(eng, clock, 4.0, action="remove_from", target="module_b", source="container")
    send(eng, clock, 5.0, action="place_into", target="module_b", dest="container")
    send(eng, clock, 6.0, action="close", target="container")
    assert violations(eng, "skip") == []
    assert violations(eng, "module_not_sealed") == []


def test_operator_override_is_logged_not_refused():
    eng, clock = make_engine()
    clock.advance_to(1.0)
    eng.process(OperatorOverrideEvent(ts=1.0, note="astronaut override: proceeding anyway"))
    overrides = [e for e in eng.out if e.event_type == "operator_override"]
    assert len(overrides) == 1
    assert overrides[0].message == "astronaut override: proceeding anyway"


def test_resume_reconstructs_completed_steps_without_re_speaking():
    r = resolve(PROTOCOL, DEFAULTS)
    clock = VirtualClock()
    eng = ProtocolEngine(r, clock=clock)
    from src.protocol.events import EngineEvent

    prior = [
        EngineEvent(ts_monotonic=1.0, event_type="step_complete", step_id="open_container"),
        EngineEvent(ts_monotonic=2.0, event_type="step_complete", step_id="remove_a"),
    ]
    eng.resume(prior)
    assert "open_container" in eng.complete
    assert "remove_a" in eng.complete
    assert eng.satisfiable_steps() - {"remove_a", "open_container"}


def test_resume_round_trips_through_a_real_session_log(tmp_path):
    """The actual CLAUDE.md requirement: reload a SESSION LOG (JSONL, as
    src/logging/session_log.py writes it), not a hand-built EngineEvent
    list."""
    from src.logging.session_log import SessionLogger

    log_path = tmp_path / "session.jsonl"
    eng1, clock1 = make_engine()
    logged = 0
    with SessionLogger(log_path, session_id="s1") as logger:
        for e in eng1.out[logged:]:
            logger.log_event(e)
        logged = len(eng1.out)

        send(eng1, clock1, 1.0, action="open", target="container")
        for e in eng1.out[logged:]:
            logger.log_event(e)
        logged = len(eng1.out)

        send(eng1, clock1, 2.0, action="remove_from", target="module_a", source="container")
        for e in eng1.out[logged:]:
            logger.log_event(e)
        logged = len(eng1.out)

    eng2, _ = make_engine()
    eng2.resume_from_log(str(log_path))
    assert "open_container" in eng2.complete
    assert "remove_a" in eng2.complete


def test_hot_reload_preserves_completed_steps_that_still_exist():
    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")
    assert "open_container" in eng.complete

    r2 = resolve(PROTOCOL, DEFAULTS)  # same protocol, simulating a re-edit
    eng.reload_protocol(r2)
    assert "open_container" in eng.complete
    reload_events = [e for e in eng.out if e.event_type == "protocol_reloaded"]
    assert len(reload_events) == 1


def test_hot_reload_revalidated_protocol_still_enforces_after_swap(tmp_path):
    import json as _json

    eng, clock = make_engine()
    send(eng, clock, 1.0, action="open", target="container")

    raw = _json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["strict_mode"] = {"require_orientation": True}
    p = tmp_path / "variant.json"
    p.write_text(_json.dumps(raw), encoding="utf-8")
    r2 = resolve(p, DEFAULTS)

    eng.reload_protocol(r2)
    assert eng.constraints_by_id["correct_insertion_orientation"].enabled is True
    # Progress and satisfiability are still live post-reload.
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    assert "remove_a" in eng.complete


def test_lid_stow_zone_name_comes_from_protocol_not_hardcoded(tmp_path):
    """A protocol naming its stow zone something other than 'stow_zone'
    must still clear the lid_stow_required timeout when the lid reaches
    it."""
    import json as _json

    raw = _json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["zones"]["parking_area"] = {"frame": "rack"}
    for step in raw["steps"]:
        if step.get("type") == "group":
            for child in step["steps"]:
                if child["id"] == "stow_a_lid":
                    child["zone"] = "parking_area"
    p = tmp_path / "variant.json"
    p.write_text(_json.dumps(raw), encoding="utf-8")

    eng, clock = make_engine(p)
    send(eng, clock, 1.0, action="open", target="container")
    send(eng, clock, 2.0, action="remove_from", target="module_a", source="container")
    send(eng, clock, 3.0, action="open", target="module_a")
    send(eng, clock, 5.0, action="move_to_zone", target="module_a.lid", zone="parking_area")
    clock.advance_to(20.0)
    eng.check_timeouts(20.0)
    assert violations(eng, "lid_unstowed") == []
