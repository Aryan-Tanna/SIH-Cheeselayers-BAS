"""One live session: engine + alert policy + announcer + log + audio,
behind a single lock.

Two threads drive it: the perception/fusion thread (semantic events,
timeout ticks) and the voice-control thread (operator commands). The
engine is not thread-safe, so every entry point here takes the same
lock; nothing outside this class should touch the engine directly.

Operator commands (see configs/runtime.yaml voice_control.commands):
  pause   -- engine frozen (events ignored, timers stopped), voice silenced
  resume  -- carry on from the same step; the current step is re-stated
  quiet   -- step prompts become a tick per completed step; alerts still spoken
  voice   -- step prompts spoken again
  repeat  -- speak the current step
  next    -- mark the current step done (camera missed it) and move on;
             logged as operator_override. Only the step due now: it can't
             skip ahead, and it does nothing while paused.
"Hey BAS" alone cuts off and holds all speech for the command window so
the operator can talk (see AudioWorker hold). The next command ends the
hold; with no command, the worker's hold times out on its own. Either
way the cut-off clip is restarted -- except after pause (flushed; resume
re-states the step) and quiet (prompts are not spoken; alerts still are).
The engine and its timers keep running through a hold: only explicit
pause stops them, because pausing also ignores perception events and an
accidental wake must not cost the operator a step.
Every command is logged. The operator's authority is absolute: commands
are never refused.
"""

from __future__ import annotations

import threading
from typing import Callable

from src.logging.session_log import SessionLogger
from src.protocol.alerts import AlertManager
from src.protocol.engine import ProtocolEngine, split_target
from src.protocol.events import EngineEvent, SemanticEvent
from src.protocol.loader import ResolvedProtocol
from src.runtime.announcer import Announcer, AnnouncerSettings, AudioRequest, role_spoken_name
from src.runtime.clock import Clock, SystemClock
from src.runtime.voice_control import WAKE

COMMANDS = ("pause", "resume", "quiet", "voice", "repeat", "next", WAKE)


class Session:
    def __init__(
        self,
        resolved: ResolvedProtocol,
        clock: Clock | None = None,
        audio_submit: Callable[[list[AudioRequest]], None] | None = None,
        settings: AnnouncerSettings | None = None,
        logger: SessionLogger | None = None,
        operator: str | None = None,
        event_listeners: list[Callable[[EngineEvent], None]] | None = None,
        audio_listeners: list[Callable[[AudioRequest], None]] | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self._lock = threading.RLock()
        self._audio_submit = audio_submit
        self.logger = logger
        self.engine = ProtocolEngine(resolved, clock=self.clock, operator=operator)
        self.announcer = Announcer(
            resolved, AlertManager.from_policy(resolved.alert_policy, clock=self.clock), settings
        )
        # GUI hooks: called with every engine event / audio request, in
        # order, under the session lock -- keep them fast (enqueue only).
        # Passed at construction so they also see session_start and the
        # first prompt.
        self.event_listeners: list[Callable[[EngineEvent], None]] = list(event_listeners or [])
        self.audio_listeners: list[Callable[[AudioRequest], None]] = list(audio_listeners or [])
        self._seen = 0
        self._holding = False  # a wake chime is holding speech
        with self._lock:
            self._flush()  # session_start + first prompt

    # ------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self.engine.paused

    @property
    def mode(self) -> str:
        return self.announcer.mode

    def on_event(self, event: SemanticEvent) -> None:
        with self._lock:
            self.engine.process(event)
            self._flush()

    def tick(self, now: float | None = None) -> None:
        """Let timeouts fire with no new event (call every frame / ~1 s)."""
        with self._lock:
            self.engine.check_timeouts(self.clock.now() if now is None else now)
            self._flush()

    def command(self, command: str, ts: float | None = None) -> None:
        if command not in COMMANDS:
            raise ValueError(f"unknown command {command!r}; expected one of {COMMANDS}")
        with self._lock:
            ts = self.clock.now() if ts is None else ts
            extra: list[AudioRequest] = []
            if command == WAKE:
                self._holding = True
                extra = self.announcer.wake_ack()
            elif command == "pause":
                self.engine.pause_session(ts)
            elif command == "resume":
                self.engine.resume_session(ts)
            elif command in ("quiet", "voice"):
                self.engine.note_operator_command(ts, f"{command}_mode")
                extra = self.announcer.set_mode(command)
            elif command == "repeat":
                self.engine.note_operator_command(ts, "repeat")
                extra = [] if self.engine.paused else self.announcer.repeat()
            elif command == "next":
                sid = self.announcer.current_step()
                if sid is None or not self.engine.confirm_step(ts, sid, note="voice: next step"):
                    self.engine.note_operator_command(ts, "next_step_not_applied")
                    if not self.engine.paused:
                        extra = self.announcer.repeat()  # "No step is pending." / the step
            if command != WAKE and self._holding:
                # After the command's own acknowledgement, so the operator
                # hears the command confirmed before the cut-off clip.
                self._holding = False
                extra.append(AudioRequest(kind="system", release=True,
                                          replay_prompt=command != "quiet"))
            self._flush(extra)

    def snapshot(self) -> dict:
        """Read-only view of protocol state for a GUI, taken under the
        lock so it is consistent. Each step's status is one of:
        done, confirmed (operator said "next step"), missed (skip
        violation), not_applicable (condition false), open (due now),
        pending."""
        with self._lock:
            eng = self.engine
            open_steps = eng.satisfiable_steps()
            missed = {
                e.step_id for e in eng.out
                if e.event_type == "violation" and e.violation_type == "skip"
            }
            steps = []
            for sid in eng.parsed.order:
                node = eng.parsed.nodes[sid]
                if sid in eng.confirmed_by_operator:
                    status = "confirmed"
                elif sid in eng.complete:
                    status = "done"
                elif sid in eng.skipped:
                    status = "not_applicable"
                elif sid in missed:
                    status = "missed"
                elif sid in open_steps:
                    status = "open"
                else:
                    status = "pending"
                role = split_target(node.target)[0]
                steps.append({"id": sid, "prompt": node.prompt or sid, "status": status,
                              "target": node.target,
                              "object": role_spoken_name(self.announcer.resolved, role)})
            return {
                "protocol_id": eng.parsed.protocol_id,
                "title": eng.parsed.raw.get("title", eng.parsed.protocol_id),
                "steps": steps,
                "current_step": self.announcer.current_step(),
                "mode": self.announcer.mode,
                "paused": eng.paused,
                "violations": sum(1 for e in eng.out if e.event_type == "violation"),
            }

    def reload_protocol(self, resolved: ResolvedProtocol) -> None:
        """Hot reload. The caller validates first (see engine.reload_protocol)."""
        with self._lock:
            self.announcer.set_protocol(resolved)
            self.engine.reload_protocol(resolved)
            self._flush()

    # ------------------------------------------------------------------

    def _flush(self, extra: list[AudioRequest] | None = None) -> None:
        batch = self.engine.out[self._seen:]
        self._seen = len(self.engine.out)
        for e in batch:
            if self.logger is not None:
                self.logger.log_event(e)
            for cb in self.event_listeners:
                cb(e)
        requests = self.announcer.plan(batch) + (extra or [])
        for r in requests:
            for cb in self.audio_listeners:
                cb(r)
        if requests and self._audio_submit is not None:
            self._audio_submit(requests)
