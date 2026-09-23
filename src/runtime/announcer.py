"""Engine output -> what the co-pilot should SAY. Pure logic, no audio.

The engine emits everything (log completeness); this module decides the
much smaller set of things worth putting in the operator's ear, and in
what form. It is the one place AlertManager.decide() is called in the
live runtime, so root-cause suppression happens exactly once per
violation, on the same clock the engine runs on.

Input is one BATCH: the engine events produced by a single
engine.process() call. Batching matters for prompts -- after the
container opens, the engine announces every newly satisfiable step in
one go, and "speak the first" is only meaningful across that batch.

Spoken text is never the engine's `message` (that is debug text naming
step ids). Violations speak their constraint's `alert` line from
configs/defaults.yaml (or the protocol's override of it); prompts and
successes speak the protocol author's own `prompt` / `success` strings;
WHICH object is named with the profile's `spoken_name`, since an
astronaut mid-task cannot look at a GUI to find out.

Two modes, switchable by voice at runtime:
  voice -- next-step prompts and success lines are spoken.
  quiet -- steps are marked by a short earcon only; alerts, anomaly and
           session announcements are still spoken.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.protocol.alerts import AlertManager
from src.protocol.engine import split_target
from src.protocol.events import EngineEvent
from src.protocol.loader import ResolvedProtocol

RequestKind = Literal["alert", "prompt", "success", "step", "system"]
Mode = Literal["voice", "quiet"]
MODES: tuple[str, ...] = ("voice", "quiet")

# Spoken when a violation's constraint has no `alert` line (a protocol
# constraint that forgot one). Generic on purpose -- better than silence
# for a caution/warning the policy has already decided to speak.
FALLBACK_ALERT_TEXT = "Check the current step."
ANOMALY_TEXT = "Anomaly detected."
CONTINUE_TEXT = "Continue with the current step."
PAUSED_TEXT = "Paused. Say hey bass, resume, to continue."
RESUMED_TEXT = "Resuming."
QUIET_TEXT = "Quiet mode. Alerts only."
VOICE_TEXT = "Voice prompts on."
NOTHING_PENDING_TEXT = "No step is pending."

# Earcon keys beyond the three severities (configs/runtime.yaml).
EARCON_STEP = "step"
EARCON_WAKE = "wake"


@dataclass(frozen=True, slots=True)
class AudioRequest:
    kind: RequestKind
    # Spoken in order with a short gap. Kept as separate phrases (not one
    # string) so each is pre-renderable: "Missed on the yellow module:
    # <prompt>" is one phrase per step, not one per combination.
    segments: tuple[str, ...] = ()
    earcon: str | None = None  # key into the earcon table, or None
    severity: str | None = None  # set for kind == "alert"
    # Warnings cut off whatever is playing and flush lower-priority
    # queued items (alerts.py severity tier: "tone + speech, interrupts").
    interrupt: bool = False
    # Pause: silence everything, warnings included, then say this.
    flush_all: bool = False
    step_id: str | None = None
    root_cause_id: str | None = None
    ts_monotonic: float | None = None

    @property
    def text(self) -> str | None:
        return " ".join(self.segments) if self.segments else None


@dataclass(frozen=True, slots=True)
class AnnouncerSettings:
    speak_next_step: str = "first"  # "first" | "none"
    speak_step_success: bool = True
    mode: str = "voice"
    # Missed steps named individually in one skip alert; the rest are
    # summarised as "And N more steps."
    max_named_skips: int = 2
    interrupt_severities: frozenset[str] = frozenset({"warning"})

    @classmethod
    def from_config(cls, prompts_cfg: dict) -> "AnnouncerSettings":
        mode = prompts_cfg.get("speak_next_step", "first")
        if mode not in ("first", "none"):
            raise ValueError(f"audio.prompts.speak_next_step must be 'first' or 'none', got {mode!r}")
        start_mode = prompts_cfg.get("mode", "voice")
        if start_mode not in MODES:
            raise ValueError(f"audio.prompts.mode must be one of {MODES}, got {start_mode!r}")
        return cls(
            speak_next_step=mode,
            speak_step_success=bool(prompts_cfg.get("speak_step_success", True)),
            mode=start_mode,
            max_named_skips=int(prompts_cfg.get("max_named_skips", 2)),
        )


def alert_text_by_code(resolved: ResolvedProtocol) -> dict[str, str]:
    """violation_code -> spoken alert line, from the resolved constraint
    set (so a protocol that overrides a constraint's alert text is heard,
    not the default's)."""
    out: dict[str, str] = {}
    for c in resolved.constraints:
        text = c.params.get("alert")
        if c.violation_code and text:
            out[c.violation_code] = str(text)
    return out


def role_spoken_name(resolved: ResolvedProtocol, role: str) -> str:
    profile = resolved.parsed.object_profile or {}
    name = profile.get("roles", {}).get(role, {}).get("spoken_name")
    return str(name) if name else role.replace("_", " ")


def step_spoken_prompt(resolved: ResolvedProtocol, step_id: str) -> str:
    node = resolved.parsed.nodes.get(step_id)
    if node is not None and node.prompt:
        return node.prompt
    return step_id.replace("_", " ") + "."


def missed_phrase(resolved: ResolvedProtocol, step_id: str) -> str:
    node = resolved.parsed.nodes[step_id]
    role = split_target(node.target)[0]
    return f"Missed on the {role_spoken_name(resolved, role)}: {step_spoken_prompt(resolved, step_id)}"


def expected_first_phrase(resolved: ResolvedProtocol, step_id: str) -> str:
    node = resolved.parsed.nodes[step_id]
    role = split_target(node.target)[0]
    return (
        f"Expected first, on the {role_spoken_name(resolved, role)}: "
        f"{step_spoken_prompt(resolved, step_id)}"
    )


def more_steps_phrase(n: int) -> str:
    return f"And {n} more step{'s' if n != 1 else ''}."


def speakable_phrases(resolved: ResolvedProtocol) -> list[str]:
    """Every phrase this protocol can cause to be spoken, for TTS
    pre-warming at load and hot reload."""
    phrases = set(alert_text_by_code(resolved).values())
    phrases |= {
        FALLBACK_ALERT_TEXT, ANOMALY_TEXT, CONTINUE_TEXT, PAUSED_TEXT, RESUMED_TEXT,
        QUIET_TEXT, VOICE_TEXT, NOTHING_PENDING_TEXT,
    }
    order = resolved.parsed.order
    for sid in order:
        node = resolved.parsed.nodes[sid]
        phrases.add(step_spoken_prompt(resolved, sid))
        if node.success:
            phrases.add(node.success)
        phrases.add(missed_phrase(resolved, sid))
        phrases.add(expected_first_phrase(resolved, sid))
    for n in range(1, len(order) + 1):
        phrases.add(more_steps_phrase(n))
    return sorted(phrases)


def _transitive_prereqs(resolved: ResolvedProtocol) -> dict[str, set[str]]:
    """leaf step -> every leaf step that must precede it, transitively
    (ParsedProtocol.effective_after_leaf_ids gives only the direct ones)."""
    parsed = resolved.parsed
    direct = {sid: parsed.effective_after_leaf_ids(sid) for sid in parsed.order}
    out: dict[str, set[str]] = {}

    def walk(sid: str) -> set[str]:
        if sid in out:
            return out[sid]
        out[sid] = set()  # cycle guard; the validator rejects cycles anyway
        acc: set[str] = set()
        for p in direct.get(sid, ()):
            acc.add(p)
            acc |= walk(p)
        out[sid] = acc
        return acc

    for sid in parsed.order:
        walk(sid)
    return out


class Announcer:
    def __init__(
        self,
        resolved: ResolvedProtocol,
        alert_manager: AlertManager,
        settings: AnnouncerSettings | None = None,
    ) -> None:
        self.alert_manager = alert_manager
        self.settings = settings or AnnouncerSettings()
        self.mode: str = self.settings.mode
        self._last_prompted: str | None = None
        self.set_protocol(resolved)

    def set_protocol(self, resolved: ResolvedProtocol) -> None:
        """Call on hot reload, alongside engine.reload_protocol()."""
        self.resolved = resolved
        self._alert_text = alert_text_by_code(resolved)
        self._order_index = {sid: i for i, sid in enumerate(resolved.parsed.order)}
        self._prereqs = _transitive_prereqs(resolved)
        # Sink steps (nothing depends on them): completing one ends the
        # session -- the engine runs skip detection at that point, and
        # prompting for anything afterwards is noise.
        depended_on = set().union(*self._prereqs.values()) if self._prereqs else set()
        self._terminal = {sid for sid in resolved.parsed.order if sid not in depended_on}
        # Steps the engine has announced as satisfiable that have not
        # completed yet, with their prompt text. The engine announces each
        # step exactly once, so if "speak the first" passes over a step
        # (remove_b, announced together with remove_a), nothing would
        # ever voice it again -- this is what lets it be spoken once
        # module A's branch is done.
        old_open = getattr(self, "_open", {})
        self._open: dict[str, str] = {
            sid: v for sid, v in old_open.items() if sid in resolved.parsed.nodes
        }

    def _first_in_order(self, ids: list[str]) -> str:
        return min(ids, key=lambda sid: self._order_index.get(sid, len(self._order_index)))

    # ------------------------------------------------------------------
    # Operator commands (called by the session, not driven by the engine)
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> list[AudioRequest]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self.mode = mode
        text = QUIET_TEXT if mode == "quiet" else VOICE_TEXT
        return [AudioRequest(kind="system", segments=(text,))]

    def current_step(self) -> str | None:
        """The step the operator is on: the last one prompted if still
        open, else the earliest open step."""
        if self._last_prompted in self._open:
            return self._last_prompted
        return self._first_in_order(list(self._open)) if self._open else None

    def repeat(self) -> list[AudioRequest]:
        """Speak the current step regardless of mode -- the operator asked."""
        sid = self.current_step()
        if sid is None:
            return [AudioRequest(kind="system", segments=(NOTHING_PENDING_TEXT,))]
        return [AudioRequest(kind="prompt", segments=(self._open[sid],), step_id=sid)]

    def wake_ack(self) -> list[AudioRequest]:
        return [AudioRequest(kind="system", earcon=EARCON_WAKE)]

    # ------------------------------------------------------------------
    # Engine batches
    # ------------------------------------------------------------------

    def plan(self, batch: list[EngineEvent]) -> list[AudioRequest]:
        """Session events first (pause silences everything), then alerts
        in emission order, then step feedback, then at most one next-step
        prompt -- an alert about what just went wrong must not queue
        behind "remove the second module"."""
        system: list[AudioRequest] = []
        alerts: list[AudioRequest] = []
        feedback: list[AudioRequest] = []
        skips: list[EngineEvent] = []
        # Alert decisions are deferred to after the scan: whether an
        # out_of_order is worth speaking depends on skips later in the
        # same batch (see below), and AlertManager.decide() must only be
        # called for alerts that will actually be voiced or it burns the
        # rate-cap budget.
        pending: list[EngineEvent] = []
        new_steps: list[str] = []
        progressed = False  # a step completed or new steps were offered
        session_over = False
        resumed = False
        anomaly = False

        for e in batch:
            if e.event_type == "session_paused":
                system.append(AudioRequest(
                    kind="system", segments=(PAUSED_TEXT,), flush_all=True,
                    ts_monotonic=e.ts_monotonic,
                ))
            elif e.event_type == "session_resumed":
                resumed = True
                system.append(AudioRequest(
                    kind="system", segments=(RESUMED_TEXT,), ts_monotonic=e.ts_monotonic,
                ))
            elif e.event_type == "violation" and e.violation_type == "skip":
                skips.append(e)  # aggregated below into one utterance
            elif e.event_type in ("violation", "anomaly"):
                pending.append(e)
            elif e.event_type == "step_complete":
                progressed = True
                sid = e.step_id or ""
                self._open.pop(sid, None)
                # Anything this step depended on and that is still open was
                # passed over (the operator closed the lid without stowing
                # it). That was alerted once as out_of_order; re-prompting
                # it after every later step would break "never repeat".
                for passed in self._prereqs.get(sid, ()):
                    self._open.pop(passed, None)
                if sid in self._terminal:
                    session_over = True
                feedback.extend(self._step_feedback(e))
            elif e.event_type == "next_step_suggested" and e.step_id and e.message:
                progressed = True
                self._open[e.step_id] = e.message
                new_steps.append(e.step_id)

        skipped_ids = {e.step_id for e in skips}
        for e in pending:
            if e.event_type == "anomaly":
                req = self._plan_anomaly(e)
                if req is not None:
                    anomaly = True
                    self._add_alert(alerts, req)
                continue
            # One alert per root cause: closing the container with a step
            # never done yields out_of_order (for the close) AND skip (for
            # the step) in the same instant. The skip names the step; the
            # out_of_order would only say the same thing first.
            unmet = set(e.extra.get("unmet", ()))
            if e.violation_type == "out_of_order" and unmet and unmet <= skipped_ids:
                continue
            self._add_alert(alerts, self._plan_violation(e))
        if skips:
            self._add_alert(alerts, self._plan_skips(skips))

        if session_over:
            self._open.clear()

        prompts: list[AudioRequest] = []
        # Only drop steps completed in this same batch from new_steps.
        new_steps = [sid for sid in new_steps if sid in self._open]
        # Resuming or recovering from an anomaly re-states where the
        # operator is, even in quiet mode: they asked to continue, or
        # were just interrupted, and should not have to guess the step.
        force_prompt = resumed or (anomaly and self.mode == "voice")
        if (
            self._open
            and self.settings.speak_next_step == "first"
            and ((progressed and self.mode == "voice") or force_prompt)
        ):
            # Prefer a step this batch just unlocked: it continues what the
            # operator is doing (after remove_b, "unseal", not "go get
            # module A"). Otherwise the current step -- after module B's
            # branch ends, that is what reminds them module A is still to
            # do, whichever order they chose. "First" is protocol order,
            # not the engine's sorted-id announcement order.
            first = self._first_in_order(new_steps) if new_steps else (
                self.current_step() if force_prompt and not progressed
                else self._first_in_order(list(self._open))
            )
            if first is not None:
                self._last_prompted = first
                prompts.append(AudioRequest(
                    kind="prompt", segments=(self._open[first],), step_id=first,
                ))

        return system + alerts + feedback + prompts

    # ------------------------------------------------------------------

    @staticmethod
    def _add_alert(alerts: list[AudioRequest], req: AudioRequest | None) -> None:
        # Identical lines in one batch are spoken once. The log still
        # records every one.
        if req is not None and not any(
            a.segments == req.segments and a.severity == req.severity for a in alerts
        ):
            alerts.append(req)

    def _step_feedback(self, e: EngineEvent) -> list[AudioRequest]:
        node = self.resolved.parsed.nodes.get(e.step_id or "")
        # The end of the experiment is spoken even in quiet mode: it is not
        # per-step chatter, and "did it register that I finished?" is
        # exactly what the operator would otherwise have to guess.
        terminal_line = (
            node is not None and node.success and (e.step_id in self._terminal)
        )
        if self.mode == "quiet" and not terminal_line:
            return [AudioRequest(kind="step", earcon=EARCON_STEP, step_id=e.step_id,
                                 ts_monotonic=e.ts_monotonic)]
        if self.settings.speak_step_success and node is not None and node.success:
            return [AudioRequest(kind="success", segments=(node.success,),
                                 step_id=e.step_id, ts_monotonic=e.ts_monotonic)]
        return []

    def _decide(self, severity: str, root: str) -> tuple[bool, bool] | None:
        """(tone, speak), or None for complete silence."""
        decision = self.alert_manager.decide(severity, root)
        if not decision.tone and not decision.speak:
            return None
        # A violation suppressed by root-cause cooldown or the rate cap is
        # fully silent, tone included, even though AlertDecision still
        # reports tone=True: four beeps in twelve seconds gets the system
        # muted just as surely as four sentences would. It is still logged.
        if not decision.speak and decision.reason != "severity_tone_only":
            return None
        return decision.tone, decision.speak

    def _alert(self, e: EngineEvent, severity: str, segments: tuple[str, ...],
               root: str | None = None) -> AudioRequest | None:
        d = self._decide(severity, root if root is not None else (e.root_cause_id or ""))
        if d is None:
            return None
        tone, speak = d
        return AudioRequest(
            kind="alert",
            segments=segments if speak else (),
            earcon=severity if tone else None,
            severity=severity,
            interrupt=speak and severity in self.settings.interrupt_severities,
            step_id=e.step_id,
            root_cause_id=e.root_cause_id,
            ts_monotonic=e.ts_monotonic,
        )

    def _plan_violation(self, e: EngineEvent) -> AudioRequest | None:
        segments: tuple[str, ...] = (
            self._alert_text.get(e.violation_type or "", FALLBACK_ALERT_TEXT),
        )
        unmet = [s for s in e.extra.get("unmet", ()) if s in self.resolved.parsed.nodes]
        if e.violation_type == "out_of_order" and unmet:
            segments += (expected_first_phrase(self.resolved, self._first_in_order(unmet)),)
        return self._alert(e, e.severity or "advisory", segments)

    def _plan_skips(self, skips: list[EngineEvent]) -> AudioRequest | None:
        """All missed steps in one batch (they arrive together, at the
        terminal step) become ONE utterance naming the first few -- the
        astronaut needs to know which, and cannot look at a screen. One
        utterance, so one alert-policy decision."""
        steps = [e.step_id for e in skips if e.step_id in self.resolved.parsed.nodes]
        steps.sort(key=lambda sid: self._order_index.get(sid, len(self._order_index)))
        named = steps[: self.settings.max_named_skips]
        # Name the object once per run of same-object steps: "Missed on
        # the yellow module: Remove ... . Unseal the module." -- not the
        # full prefix before every step.
        segs: list[str] = []
        prev_role: str | None = None
        for sid in named:
            role = split_target(self.resolved.parsed.nodes[sid].target)[0]
            segs.append(
                step_spoken_prompt(self.resolved, sid) if role == prev_role
                else missed_phrase(self.resolved, sid)
            )
            prev_role = role
        segments = tuple(segs)
        if len(steps) > len(named):
            segments += (more_steps_phrase(len(steps) - len(named)),)
        if not segments:
            segments = (self._alert_text.get("skip", FALLBACK_ALERT_TEXT),)
        first = skips[0]
        severity = max(
            (e.severity or "advisory" for e in skips),
            key=lambda s: ("advisory", "caution", "warning").index(s)
            if s in ("advisory", "caution", "warning") else 0,
        )
        return self._alert(first, severity, segments)

    def _plan_anomaly(self, e: EngineEvent) -> AudioRequest | None:
        segments: tuple[str, ...] = (ANOMALY_TEXT,)
        if self.mode == "voice" and self._open:
            segments += (CONTINUE_TEXT,)
        return self._alert(e, e.severity or "caution", segments)
