"""Alert policy: one alert per root cause.

Rationale (preserve this — it is why the module exists): a single root
error can produce four alertable conditions in twelve seconds — e.g. an
unsealed module triggers module_not_sealed on return, then a downstream
timeout fires lid_unstowed, then the same missing module fires
module_not_returned when the container closes. An astronaut who hears
four alerts in twelve seconds mutes the system, and a muted system has
zero mission value.

Log completeness and alert restraint are separate concerns, separately
configurable: every violation is ALWAYS logged (that responsibility is
the caller's — see src/logging/session_log.py — this module never
drops a log line). Only whether to SPEAK is decided here, per
root_cause_id, with a cooldown window, plus a global rate cap as a
second, independent backstop.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.runtime.clock import Clock, SystemClock

Severity = str  # "advisory" | "caution" | "warning"


@dataclass
class AlertDecision:
    speak: bool
    tone: bool
    reason: str


class AlertManager:
    def __init__(
        self,
        root_cause_cooldown_s: float,
        max_alerts_per_minute: int,
        severity_speaks: set[str],
        severity_tone_only: set[str],
        suppress_consequences_of_same_root: bool = True,
        clock: Clock | None = None,
    ) -> None:
        self.root_cause_cooldown_s = root_cause_cooldown_s
        self.max_alerts_per_minute = max_alerts_per_minute
        self.severity_speaks = severity_speaks
        self.severity_tone_only = severity_tone_only
        self.suppress_consequences_of_same_root = suppress_consequences_of_same_root
        self.clock = clock or SystemClock()

        self._last_alert_ts_by_root: dict[str, float] = {}
        self._recent_alert_ts: list[float] = []

    @classmethod
    def from_policy(cls, policy: dict, clock: Clock | None = None) -> "AlertManager":
        return cls(
            root_cause_cooldown_s=policy["root_cause_cooldown_s"],
            max_alerts_per_minute=policy["max_alerts_per_minute"],
            severity_speaks=set(policy.get("severity_speaks", [])),
            severity_tone_only=set(policy.get("severity_tone_only", [])),
            suppress_consequences_of_same_root=policy.get(
                "suppress_consequences_of_same_root", True
            ),
            clock=clock,
        )

    def _prune_rate_window(self, now: float) -> None:
        cutoff = now - 60.0
        self._recent_alert_ts = [t for t in self._recent_alert_ts if t > cutoff]

    def decide(self, severity: Severity, root_cause_id: str) -> AlertDecision:
        """Call once per violation. Logging happens regardless of the
        decision — this only decides whether the voice speaks."""
        now = self.clock.now()

        if severity in self.severity_tone_only:
            tone, speak_eligible = True, False
        elif severity in self.severity_speaks:
            tone, speak_eligible = True, True
        else:
            tone, speak_eligible = False, False

        if not speak_eligible:
            return AlertDecision(speak=False, tone=tone, reason="severity_tone_only")

        last = self._last_alert_ts_by_root.get(root_cause_id)
        if (
            self.suppress_consequences_of_same_root
            and last is not None
            and (now - last) < self.root_cause_cooldown_s
        ):
            return AlertDecision(
                speak=False, tone=tone, reason="root_cause_cooldown_active"
            )

        self._prune_rate_window(now)
        if len(self._recent_alert_ts) >= self.max_alerts_per_minute:
            return AlertDecision(speak=False, tone=tone, reason="rate_limit")

        self._last_alert_ts_by_root[root_cause_id] = now
        self._recent_alert_ts.append(now)
        return AlertDecision(speak=True, tone=tone, reason="root_cause_new_or_expired")
