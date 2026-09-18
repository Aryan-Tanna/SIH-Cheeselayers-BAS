from src.protocol.alerts import AlertManager
from src.runtime.clock import VirtualClock


def make_manager(clock, cooldown=8.0, rate=4, suppress=True):
    return AlertManager(
        root_cause_cooldown_s=cooldown,
        max_alerts_per_minute=rate,
        severity_speaks={"caution", "warning"},
        severity_tone_only={"advisory"},
        suppress_consequences_of_same_root=suppress,
        clock=clock,
    )


def test_advisory_never_speaks_but_still_tones():
    clock = VirtualClock()
    mgr = make_manager(clock)
    decision = mgr.decide("advisory", "root1")
    assert decision.speak is False
    assert decision.tone is True


def test_first_violation_from_a_root_speaks():
    clock = VirtualClock()
    mgr = make_manager(clock)
    decision = mgr.decide("caution", "root1")
    assert decision.speak is True


def test_second_violation_same_root_within_cooldown_is_suppressed():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=8.0)
    assert mgr.decide("caution", "root1").speak is True
    clock.advance_to(3.0)
    decision = mgr.decide("caution", "root1")
    assert decision.speak is False
    assert decision.reason == "root_cause_cooldown_active"


def test_violation_same_root_after_cooldown_speaks_again():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=8.0)
    assert mgr.decide("caution", "root1").speak is True
    clock.advance_to(9.0)
    decision = mgr.decide("caution", "root1")
    assert decision.speak is True


def test_different_roots_are_not_suppressed_by_each_others_cooldown():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=8.0)
    assert mgr.decide("caution", "root1").speak is True
    clock.advance_to(1.0)
    assert mgr.decide("caution", "root2").speak is True


def test_rate_limit_caps_alerts_per_minute_even_across_distinct_roots():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=0.0, rate=4)
    results = [mgr.decide("caution", f"root{i}").speak for i in range(6)]
    assert results == [True, True, True, True, False, False]


def test_rate_limit_window_expires_after_60s():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=0.0, rate=2)
    assert mgr.decide("caution", "r1").speak is True
    assert mgr.decide("caution", "r2").speak is True
    assert mgr.decide("caution", "r3").speak is False
    clock.advance_to(61.0)
    assert mgr.decide("caution", "r4").speak is True


def test_suppression_can_be_disabled_via_policy_flag():
    clock = VirtualClock()
    mgr = make_manager(clock, cooldown=8.0, suppress=False)
    assert mgr.decide("caution", "root1").speak is True
    clock.advance_to(1.0)
    assert mgr.decide("caution", "root1").speak is True


def test_unknown_severity_neither_tones_nor_speaks():
    clock = VirtualClock()
    mgr = make_manager(clock)
    decision = mgr.decide("not_a_real_severity", "root1")
    assert decision.speak is False
    assert decision.tone is False
