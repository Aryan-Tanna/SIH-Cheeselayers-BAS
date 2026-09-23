import threading
from pathlib import Path

import pytest

from src.logging.session_log import SessionLogger, load_events, verify_chain
from src.protocol.events import ActionEvent, AnomalyEvent
from src.protocol.loader import resolve
from src.runtime.announcer import AnnouncerSettings
from src.runtime.clock import VirtualClock
from src.runtime.session import Session

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"


def _session(tmp_path=None, **kw):
    clock = VirtualClock()
    heard = []
    logger = SessionLogger(tmp_path / "s.jsonl", "test") if tmp_path else None
    s = Session(resolve(PROTOCOL, DEFAULTS), clock=clock, audio_submit=heard.extend,
                logger=logger, **kw)
    return s, clock, heard


def _act(s, clock, t, action, target, **kw):
    clock.advance_to(t)
    s.on_event(ActionEvent(ts=t, action=action, target=target, **kw))


def test_first_prompt_reaches_audio_and_listeners():
    seen = []
    s, _, heard = _session(audio_listeners=[seen.append])
    assert [r.text for r in heard] == ["Open the payload container."]
    assert seen == heard


def test_quiet_command_switches_mode_and_is_logged(tmp_path):
    s, clock, heard = _session(tmp_path)
    s.command("quiet")
    assert s.mode == "quiet"
    assert heard[-1].text == "Quiet mode. Alerts only."
    heard.clear()
    _act(s, clock, 1.0, "open", "container")
    assert [r.kind for r in heard] == ["step"]
    s.logger.close()
    assert any(e["event_type"] == "operator_command" for e in load_events(tmp_path / "s.jsonl"))


def test_pause_resume_round_trip_with_log(tmp_path):
    s, clock, heard = _session(tmp_path)
    _act(s, clock, 1.0, "open", "container")
    _act(s, clock, 2.0, "remove_from", "module_a", source="container")
    clock.advance_to(3.0)
    s.command("pause")
    assert s.paused and heard[-1].flush_all
    _act(s, clock, 5.0, "open", "module_a")  # ignored
    heard.clear()
    clock.advance_to(20.0)
    s.command("resume")
    assert not s.paused
    assert [r.text for r in heard] == ["Resuming.", "Unseal the module."]
    _act(s, clock, 21.0, "open", "module_a")
    assert "open_a_lid" in s.engine.complete
    s.logger.close()
    types = [e["event_type"] for e in load_events(tmp_path / "s.jsonl")]
    assert "session_paused" in types and "session_resumed" in types
    assert verify_chain(tmp_path / "s.jsonl").ok


def test_tick_fires_timeouts():
    s, clock, heard = _session()
    _act(s, clock, 1.0, "open", "container")
    _act(s, clock, 2.0, "remove_from", "module_a", source="container")
    _act(s, clock, 3.0, "open", "module_a")
    heard.clear()
    clock.advance_to(20.0)
    s.tick()
    assert [r.text for r in heard if r.kind == "alert"] == ["Secure the lid in the stow zone."]


def test_repeat_while_paused_says_nothing():
    s, _, heard = _session()
    s.command("pause")
    heard.clear()
    s.command("repeat")
    assert heard == []


def test_wake_plays_chime():
    s, _, heard = _session()
    s.command("wake")
    assert heard[-1].earcon == "wake"


def test_unknown_command_rejected():
    s, _, _ = _session()
    with pytest.raises(ValueError):
        s.command("selfdestruct")


def test_anomaly_mid_protocol_then_continue():
    s, clock, heard = _session()
    _act(s, clock, 1.0, "open", "container")
    heard.clear()
    clock.advance_to(2.0)
    s.on_event(AnomalyEvent(ts=2.0, label="pen"))
    assert heard[0].text == "Anomaly detected. Continue with the current step."
    _act(s, clock, 3.0, "remove_from", "module_a", source="container")
    assert "remove_a" in s.engine.complete


def test_commands_and_events_from_two_threads_do_not_corrupt_state():
    s, clock, _ = _session(settings=AnnouncerSettings(mode="quiet"))
    _act(s, clock, 1.0, "open", "container")
    stop = threading.Event()

    def spam_commands():
        while not stop.is_set():
            s.command("quiet")
            s.command("repeat")

    t = threading.Thread(target=spam_commands)
    t.start()
    try:
        for mod, t0 in (("module_a", 2.0), ("module_b", 10.0)):
            _act(s, clock, t0, "remove_from", mod, source="container")
            _act(s, clock, t0 + 1, "open", mod)
            _act(s, clock, t0 + 2, "move_to_zone", f"{mod}.lid", zone="stow_zone")
            _act(s, clock, t0 + 3, "close", mod)
            _act(s, clock, t0 + 4, "place_into", mod, dest="container")
        _act(s, clock, 20.0, "close", "container")
    finally:
        stop.set()
        t.join()
    assert s.engine.complete == set(s.engine.parsed.order)
    assert not [e for e in s.engine.out if e.event_type == "violation"]


def test_wake_chime_holds_speech():
    s, _, heard = _session()
    s.command("wake")
    assert heard[-1].hold


def test_command_after_wake_releases_after_its_ack():
    s, _, heard = _session()
    s.command("wake")
    heard.clear()
    s.command("voice")
    assert [r.release for r in heard] == [False, True]   # ack, then release
    assert heard[-1].replay_prompt is True


def test_quiet_after_wake_releases_without_prompt_replay():
    s, _, heard = _session()
    s.command("wake")
    heard.clear()
    s.command("quiet")
    assert heard[-1].release and heard[-1].replay_prompt is False


def test_command_without_wake_sends_no_release():
    s, _, heard = _session()
    heard.clear()
    s.command("voice")
    assert not any(r.release for r in heard)


def test_wake_does_not_pause_engine_or_timers():
    s, _, _ = _session()
    s.command("wake")
    assert not s.paused


def test_next_step_marks_done_then_speaks_next_step(tmp_path):
    s, _, heard = _session(tmp_path)
    heard.clear()
    s.command("next")
    assert "open_container" in s.engine.complete
    texts = [r.text for r in heard]
    assert texts[0] == "Marked done."
    assert heard[-1].kind == "prompt"
    events = [e["event_type"] for e in load_events(tmp_path / "s.jsonl")]
    assert "operator_override" in events


def test_next_step_speaks_next_prompt_even_in_quiet_mode():
    s, _, heard = _session()
    s.command("quiet")
    heard.clear()
    s.command("next")
    assert heard[0].text == "Marked done." and heard[-1].kind == "prompt"


def test_next_step_while_paused_does_nothing():
    s, _, heard = _session()
    s.command("pause")
    heard.clear()
    s.command("next")
    assert heard == [] and s.engine.complete == set()


def test_next_after_wake_drops_cut_prompt_in_favour_of_new_one():
    s, _, heard = _session()
    s.command("wake")
    heard.clear()
    s.command("next")
    assert heard[-1].release and heard[-1].replay_prompt   # worker drops the stale prompt
