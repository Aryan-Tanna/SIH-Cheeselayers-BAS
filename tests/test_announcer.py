from pathlib import Path

import pytest

from src.protocol.alerts import AlertManager
from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent, AnomalyEvent, EngineEvent
from src.protocol.loader import resolve
from src.runtime.announcer import (
    ANOMALY_TEXT,
    FALLBACK_ALERT_TEXT,
    PAUSED_TEXT,
    Announcer,
    AnnouncerSettings,
    alert_text_by_code,
    speakable_phrases,
)
from src.runtime.clock import VirtualClock

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"


def _setup(settings=None):
    resolved = resolve(PROTOCOL, DEFAULTS)
    clock = VirtualClock()
    engine = ProtocolEngine(resolved, clock=clock)
    ann = Announcer(resolved, AlertManager.from_policy(resolved.alert_policy, clock=clock), settings)
    return resolved, clock, engine, ann


class _Driver:
    """Feeds actions and returns the audio plan for each engine batch."""

    def __init__(self, settings=None):
        self.resolved, self.clock, self.engine, self.ann = _setup(settings)
        self.seen = 0

    def batch(self):
        b = self.engine.out[self.seen:]
        self.seen = len(self.engine.out)
        return self.ann.plan(b)

    def act(self, t, action, target, **kw):
        self.clock.advance_to(t)
        self.engine.process(ActionEvent(ts=t, action=action, target=target, **kw))
        return self.batch()

    def do_module(self, t0, mod, letter):
        self.act(t0, "remove_from", mod, source="container")
        self.act(t0 + 1, "open", mod)
        self.act(t0 + 2, "move_to_zone", f"{mod}.lid", zone="stow_zone")
        self.act(t0 + 3, "close", mod)
        return self.act(t0 + 4, "place_into", mod, dest="container")


def _texts(reqs, kind=None):
    return [r.text for r in reqs if kind is None or r.kind == kind]


def _alerts(reqs):
    return [r for r in reqs if r.kind == "alert"]


# --- phrases ------------------------------------------------------------------

def test_alert_text_comes_from_constraints_not_engine_message():
    texts = alert_text_by_code(resolve(PROTOCOL, DEFAULTS))
    assert texts["mutual_exclusion_breach"] == "Return the current module before accessing another."


def test_speakable_phrases_cover_everything_the_announcer_can_say():
    phrases = set(speakable_phrases(resolve(PROTOCOL, DEFAULTS)))
    assert {"Open the payload container.", "Experiment complete. Log written.",
            FALLBACK_ALERT_TEXT, ANOMALY_TEXT, PAUSED_TEXT,
            "Missed on the yellow module: Reseal the module.",
            "Expected first, on the red module: Secure the lid in the stow zone.",
            "And 3 more steps.", "And 1 more step."} <= phrases


def test_every_planned_segment_is_prewarmable():
    # Anything the announcer says must be in speakable_phrases, or it is
    # synthesized at alert time (0.4-0.9 s measured).
    d = _Driver()
    phrases = set(speakable_phrases(d.resolved))
    said = list(d.batch())
    said += d.act(1.0, "open", "container")
    said += d.act(2.0, "remove_from", "module_a", source="container")
    said += d.act(3.0, "open", "module_a")
    said += d.act(4.0, "close", "module_a")
    said += d.act(5.0, "close", "container")
    for r in said:
        assert set(r.segments) <= phrases, r


# --- prompts ------------------------------------------------------------------

def test_session_start_speaks_first_prompt():
    assert _texts(_Driver().batch()) == ["Open the payload container."]


def test_two_new_steps_speak_only_first_in_protocol_order():
    d = _Driver()
    d.batch()
    reqs = d.act(1.0, "open", "container")
    assert _texts(reqs, "prompt") == ["Remove the first specimen module."]
    assert _texts(reqs, "success") == ["Container open. Select a specimen module."]


def test_passed_over_parallel_step_is_prompted_after_branch_completes():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    reqs = d.do_module(2.0, "module_a", "a")
    assert _texts(reqs, "prompt") == ["Remove the second specimen module."]


def test_new_step_in_current_branch_beats_older_open_step():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    reqs = d.act(2.0, "remove_from", "module_b", source="container")
    assert [r.step_id for r in reqs if r.kind == "prompt"] == ["open_b_lid"]


def test_other_module_reprompted_after_b_first_branch():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    reqs = d.do_module(2.0, "module_b", "b")
    assert [r.step_id for r in reqs if r.kind == "prompt"] == ["remove_a"]


def test_step_passed_over_out_of_order_is_not_reprompted():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.act(2.0, "remove_from", "module_a", source="container")
    d.act(3.0, "open", "module_a")
    d.act(4.0, "close", "module_a")  # skipped stowing the lid
    reqs = d.act(5.0, "place_into", "module_a", dest="container")
    assert "stow_a_lid" not in [r.step_id for r in reqs]


def test_no_prompt_after_terminal_step():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    reqs = d.act(2.0, "close", "container")
    assert _texts(reqs, "prompt") == []
    assert "Experiment complete. Log written." in _texts(reqs, "success")


def test_speak_next_step_none_disables_prompts():
    assert _texts(_Driver(AnnouncerSettings(speak_next_step="none")).batch(), "prompt") == []


def test_settings_reject_unknown_values():
    with pytest.raises(ValueError):
        AnnouncerSettings.from_config({"speak_next_step": "all"})
    with pytest.raises(ValueError):
        AnnouncerSettings.from_config({"mode": "loud"})


# --- named alerts -------------------------------------------------------------

def test_skip_names_the_missed_step_and_its_object():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.do_module(2.0, "module_a", "a")
    d.act(7.0, "remove_from", "module_b", source="container")
    d.act(8.0, "open", "module_b")
    d.act(9.0, "move_to_zone", "module_b.lid", zone="stow_zone")
    d.act(10.0, "place_into", "module_b", dest="container")  # never resealed
    reqs = d.act(11.0, "close", "container")
    spoken = [r.segments for r in _alerts(reqs) if r.severity == "warning"]
    assert spoken == [("Missed on the yellow module: Reseal the module.",)]


def test_many_skips_become_one_utterance_naming_the_first_two():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.do_module(2.0, "module_a", "a")
    reqs = d.act(7.0, "close", "container")  # all five module_b steps missed
    skip_alerts = [r for r in _alerts(reqs) if r.severity == "warning"]
    assert len(skip_alerts) == 1
    assert skip_alerts[0].segments == (
        "Missed on the yellow module: Remove the second specimen module.",
        "Unseal the module.",
        "And 3 more steps.",
    )
    assert skip_alerts[0].interrupt


def test_out_of_order_covered_by_skip_is_not_spoken_twice():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.do_module(2.0, "module_a", "a")
    reqs = d.act(7.0, "close", "container")
    assert not any(r.severity == "caution" for r in _alerts(reqs))


def test_out_of_order_names_what_was_expected_first():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.act(2.0, "remove_from", "module_a", source="container")
    d.act(3.0, "open", "module_a")
    reqs = d.act(4.0, "close", "module_a")
    assert _alerts(reqs)[0].segments == (
        "That step is out of sequence.",
        "Expected first, on the red module: Secure the lid in the stow zone.",
    )


def test_advisory_is_tone_only():
    _resolved, _clock, _engine, ann = _setup()
    ev = EngineEvent(ts_monotonic=0.0, event_type="violation", violation_type="wrong_orientation",
                     severity="advisory", root_cause_id="r1", target="module_a")
    reqs = ann.plan([ev])
    assert len(reqs) == 1 and reqs[0].earcon == "advisory" and not reqs[0].segments


def test_suppressed_by_cooldown_is_fully_silent():
    _resolved, clock, _engine, ann = _setup()

    def ev(t):
        return EngineEvent(ts_monotonic=t, event_type="violation",
                           violation_type="mutual_exclusion_breach", severity="caution",
                           root_cause_id="same_root", target="module_b")

    assert len(ann.plan([ev(0.0)])) == 1
    clock.advance_to(2.0)
    assert ann.plan([ev(2.0)]) == []


def test_unknown_violation_code_uses_fallback_text():
    _resolved, _clock, _engine, ann = _setup()
    ev = EngineEvent(ts_monotonic=0.0, event_type="violation", violation_type="premature_close",
                     severity="caution", root_cause_id="r", target="container")
    assert ann.plan([ev])[0].segments == (FALLBACK_ALERT_TEXT,)


# --- quiet mode ---------------------------------------------------------------

def test_quiet_mode_ticks_steps_and_speaks_no_prompts():
    d = _Driver(AnnouncerSettings(mode="quiet"))
    assert d.batch() == []
    reqs = d.act(1.0, "open", "container")
    assert [(r.kind, r.earcon, r.segments) for r in reqs] == [("step", "step", ())]


def test_quiet_mode_still_speaks_alerts_and_the_end():
    d = _Driver(AnnouncerSettings(mode="quiet"))
    d.batch()
    d.act(1.0, "open", "container")
    reqs = d.act(2.0, "close", "container")
    assert _alerts(reqs) and _alerts(reqs)[0].segments
    assert "Experiment complete. Log written." in _texts(reqs, "success")


def test_switching_mode_at_runtime():
    d = _Driver()
    d.batch()
    ack = d.ann.set_mode("quiet")
    assert ack[0].segments == ("Quiet mode. Alerts only.",)
    assert [r.kind for r in d.act(1.0, "open", "container")] == ["step"]
    d.ann.set_mode("voice")
    reqs = d.act(2.0, "remove_from", "module_a", source="container")
    assert _texts(reqs, "prompt") == ["Unseal the module."]


def test_repeat_speaks_current_step_even_in_quiet_mode():
    d = _Driver(AnnouncerSettings(mode="quiet"))
    d.batch()
    d.act(1.0, "open", "container")
    d.act(2.0, "remove_from", "module_a", source="container")
    assert [r.step_id for r in d.ann.repeat()] == ["open_a_lid"]


# --- pause / resume / anomaly -------------------------------------------------

def test_pause_flushes_and_resume_restates_current_step():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.act(2.0, "remove_from", "module_a", source="container")
    d.engine.pause_session(3.0)
    paused = d.batch()
    assert paused[0].flush_all and paused[0].segments == (PAUSED_TEXT,)
    d.clock.advance_to(20.0)
    d.engine.resume_session(20.0)
    resumed = d.batch()
    assert resumed[0].segments == ("Resuming.",)
    assert [r.step_id for r in resumed if r.kind == "prompt"] == ["open_a_lid"]


def test_anomaly_spoken_once_then_current_step_restated():
    d = _Driver()
    d.batch()
    d.act(1.0, "open", "container")
    d.act(2.0, "remove_from", "module_a", source="container")
    d.clock.advance_to(3.0)
    d.engine.process(AnomalyEvent(ts=3.0, label="pen"))
    reqs = d.batch()
    assert _alerts(reqs)[0].segments == (ANOMALY_TEXT, "Continue with the current step.")
    assert [r.step_id for r in reqs if r.kind == "prompt"] == ["open_a_lid"]
    d.clock.advance_to(4.0)
    d.engine.process(AnomalyEvent(ts=4.0, label="pen"))
    assert d.batch() == []  # same root, within cooldown


def test_anomaly_in_quiet_mode_is_just_the_alert():
    d = _Driver(AnnouncerSettings(mode="quiet"))
    d.batch()
    d.engine.process(AnomalyEvent(ts=0.0, label="pen"))
    reqs = d.batch()
    assert [r.segments for r in reqs] == [(ANOMALY_TEXT,)]
