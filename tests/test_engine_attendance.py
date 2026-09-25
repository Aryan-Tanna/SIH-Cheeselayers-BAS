"""attended_while_open: a module with its lid off must not be left with
nobody at it. The lid may lie anywhere in view (whole view = stow area)."""

from pathlib import Path

from src.protocol.engine import HANDS_IN_VIEW, ProtocolEngine
from src.protocol.events import ActionEvent, StateEvent
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


def _hands(engine, clock, t, present):
    clock.advance_to(t)
    engine.process(StateEvent(ts=t, key=HANDS_IN_VIEW, value=present))


def _tick(engine, clock, t):
    clock.advance_to(t)
    engine.check_timeouts(t)


def _unattended(engine):
    return [e for e in engine.out if e.violation_type == "unattended_open_module"]


def _module_a_open(engine, clock):
    _act(engine, clock, 1.0, "open", "container")
    _act(engine, clock, 2.0, "remove_from", "module_a", source="container")
    _act(engine, clock, 3.0, "open", "module_a")  # lid off


def test_hands_leave_with_lid_off_alerts_once_after_grace():
    eng, clock = _engine()
    _module_a_open(eng, clock)
    _hands(eng, clock, 4.0, False)
    _tick(eng, clock, 8.9)  # 4.9 s < 5 s grace
    assert _unattended(eng) == []
    _tick(eng, clock, 9.1)
    v = _unattended(eng)
    assert len(v) == 1 and v[0].target == "module_a" and v[0].severity == "warning"
    _tick(eng, clock, 30.0)
    assert len(_unattended(eng)) == 1  # alert once, never repeat


def test_hands_back_before_grace_no_alert_and_new_episode_after():
    eng, clock = _engine()
    _module_a_open(eng, clock)
    _hands(eng, clock, 4.0, False)
    _hands(eng, clock, 7.0, True)
    _tick(eng, clock, 20.0)
    assert _unattended(eng) == []
    _hands(eng, clock, 21.0, False)  # walks away again -> a new episode
    _tick(eng, clock, 26.5)
    assert len(_unattended(eng)) == 1
    _hands(eng, clock, 27.0, True)
    _hands(eng, clock, 28.0, False)
    _tick(eng, clock, 34.0)
    assert len(_unattended(eng)) == 2


def test_no_alert_when_lids_are_on():
    eng, clock = _engine()
    _act(eng, clock, 1.0, "open", "container")  # container open is fine
    _act(eng, clock, 2.0, "remove_from", "module_a", source="container")
    _hands(eng, clock, 3.0, False)
    _tick(eng, clock, 60.0)
    assert _unattended(eng) == []


def test_resealing_ends_the_risk():
    eng, clock = _engine()
    _module_a_open(eng, clock)
    _act(eng, clock, 4.0, "close", "module_a")  # lid back on
    _hands(eng, clock, 5.0, False)
    _tick(eng, clock, 60.0)
    assert _unattended(eng) == []


def test_grace_counts_from_the_later_of_hands_gone_and_lid_off():
    eng, clock = _engine()
    _act(eng, clock, 1.0, "open", "container")
    _act(eng, clock, 2.0, "remove_from", "module_a", source="container")
    _hands(eng, clock, 2.5, False)
    # lid comes off at t=10 (a late perception event); the clock starts then
    _act(eng, clock, 10.0, "open", "module_a")
    _tick(eng, clock, 14.0)
    assert _unattended(eng) == []
    _tick(eng, clock, 15.5)
    assert len(_unattended(eng)) == 1


def test_pause_freezes_the_clock_but_tracks_presence():
    eng, clock = _engine()
    _module_a_open(eng, clock)
    _hands(eng, clock, 4.0, False)
    eng.pause_session(5.0)  # 1 s of the grace used
    _tick(eng, clock, 100.0)
    assert _unattended(eng) == []
    eng.resume_session(100.0)
    _tick(eng, clock, 103.5)  # 1 + 3.5 = 4.5 s
    assert _unattended(eng) == []
    _tick(eng, clock, 104.5)
    assert len(_unattended(eng)) == 1
    # presence changes during a pause are applied, so no stale state
    eng2, clock2 = _engine()
    _module_a_open(eng2, clock2)
    _hands(eng2, clock2, 4.0, False)
    eng2.pause_session(5.0)
    _hands(eng2, clock2, 6.0, True)
    eng2.resume_session(10.0)
    _tick(eng2, clock2, 60.0)
    assert _unattended(eng2) == []


def test_no_camera_means_no_alert():
    eng, clock = _engine()
    _module_a_open(eng, clock)  # nothing ever reports hands
    _tick(eng, clock, 120.0)
    assert _unattended(eng) == []


def test_protocol_can_turn_it_off(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["strict_mode"] = {"require_attendance": False}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    r = resolve(p, DEFAULTS, REPO / "configs" / "objects" / "profile_jar.yaml")
    assert {c.id: c for c in r.constraints}["attended_while_open"].enabled is False


def test_attendance_status_reports_the_running_timer():
    eng, clock = _engine()
    _module_a_open(eng, clock)
    assert eng.attendance_status(3.5)["away_s"] is None
    _hands(eng, clock, 4.0, False)
    st = eng.attendance_status(6.5)
    assert st["open_modules"] == ["module_a"] and st["away_s"] == 2.5 and st["grace_s"] == 5.0
    assert not st["alerted"]
