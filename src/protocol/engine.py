"""Constraint-graph state machine.

Tracks a SET of currently-satisfiable steps, not an index into a list —
per the addendum, groups are not atomic and free-order siblings can
become satisfiable simultaneously. Consumes semantic events (see
src/protocol/events.py) and emits step completions and violations.

Design notes (read before changing violation semantics):

* Ordering (`out_of_order`) comes only from the `after` graph, expanded
  through enclosing groups (ParsedProtocol.effective_after_leaf_ids).
  Sibling steps inside a group with no explicit `after` between them are
  genuinely free-order — that is not a bug in bas_specimen_v1, it is the
  documented design (see addendum, "groups are not atomic").

* Two things are enforced as HARD ORDERING (engine-level, unconditional,
  cannot be disabled): you cannot remove something from a closed
  container, and you cannot stow a lid that hasn't been detached yet.
  Both indicate the incoming event contradicts already-known physical
  state, which in a real deployment means a perception error, not
  something the operator actually did — so these are logged as
  `engine_anomaly`, not as one of the operator-facing violation codes,
  and the event is otherwise ignored (no state change, nothing completes).

  "A container cannot be closed while a module is outside it" is
  deliberately NOT a hard block, and is no longer even listed as hard
  ordering in configs/defaults.yaml (it was there in an earlier draft
  and got corrected). Unlike the two above, an operator really can
  attempt this — push a lid closed over a module that's still out — so
  it is handled as the non-overridable `container_empty_before_close`
  POLICY constraint instead: logged, alerted, and the close still
  completes. That's what "Operator authority ... never block, never
  lock" (CLAUDE.md) actually requires.

* `out_of_order`, `skip`, and `wrong_object` are engine-native: the
  engine always walks the after-graph and always runs end-of-run skip
  detection, so unlike the six domain constraints there is no "does this
  check even run" toggle. What configs/defaults.yaml's entries for these
  three control is purely policy — severity, and whether the resulting
  violation is reported at all (`enabled`) — which is why severity comes
  from `constraints_by_id`, not a hardcoded table here. See
  `_ENGINE_JUDGMENT_SEVERITY` below for the fallback used only if an
  engine is somehow run without these three in its resolved constraint
  set (defensive, not the normal path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.protocol.events import (
    ActionEvent,
    AnomalyEvent,
    EngineEvent,
    OperatorOverrideEvent,
    SemanticEvent,
    StateEvent,
)
from src.protocol.loader import ParsedProtocol, ResolvedConstraint, ResolvedProtocol
from src.runtime.clock import Clock, SystemClock

# Fallback only, per the docstring note above — normal path is
# constraints_by_id["out_of_order"/"skip"/"wrong_object"].severity, now
# that configs/defaults.yaml declares all three.
_ENGINE_JUDGMENT_SEVERITY = {
    "out_of_order": "caution",
    "wrong_object": "caution",
    "skip": "warning",
}

# Which of configs/defaults.yaml's default_constraints this phase-0 engine
# actually evaluates. no_loose_objects needs rack-space zone/position
# geometry (permitted_zones vs. tracked position) that does not exist
# without kinematics + perception; correct_insertion_orientation needs an
# orientation predicate no StateEvent producer feeds yet (see
# _process_state). Both are real, declared, non-negotiable-tier-2-or-not
# constraints — they are simply not wired to anything that can trip them
# in phase 0. loader.format_resolved_report() uses this set so the
# startup printout says so explicitly, rather than implying a fail-safe
# constraint is live when it is inert.
IMPLEMENTED_CONSTRAINT_IDS = frozenset({
    "one_module_at_a_time",
    "sealed_before_return",
    "container_empty_before_close",
    "lid_stow_required",
    "attended_while_open",
    "step_time_limit",
    "out_of_order",
    "no_extra_steps",
    "skip",
    "wrong_object",
})


HANDS_IN_VIEW = "operator.hands_in_view"


def split_target(target: str) -> tuple[str, str | None]:
    """"module_a" -> ("module_a", None); "module_a.lid" -> ("module_a", "lid")."""
    if "." in target:
        role, sub = target.split(".", 1)
        return role, sub
    return target, None


def evaluate_condition(cond: str, own_role: str, profile: dict[str, Any] | None) -> bool:
    """Tiny evaluator for the condition grammar CLAUDE.md's examples use:
    "target.has_lid" or "not target.has_lid". "target" always refers to
    the step's own target role (with any ".lid" suffix stripped), per
    the schema's own description of `condition`.
    """
    negate = False
    expr = cond.strip()
    if expr.startswith("not "):
        negate = True
        expr = expr[4:].strip()

    parts = expr.split(".")
    if len(parts) != 2:
        raise ValueError(f"unsupported condition expression: {cond!r}")
    subject, attr = parts
    if subject != "target":
        raise ValueError(f"unsupported condition subject: {subject!r} in {cond!r}")

    if profile is None:
        value = False
    else:
        role_def = profile.get("roles", {}).get(own_role, {})
        value = bool(role_def.get(attr, False))

    return (not value) if negate else value


@dataclass
class RoleState:
    open: bool = False  # container open, or module's own lid detached
    location: str | None = None  # "in_container" | "out" | None
    lid_zone: str = "__attached__"  # "__attached__" | "__held__" | <real zone id>
    lid_detached_ts: float | None = None
    lid_unstowed_fired: bool = False


@dataclass
class EngineConfig:
    step_debounce_frames: int
    step_debounce_of_n: int


class ProtocolEngine:
    def __init__(
        self,
        resolved: ResolvedProtocol,
        clock: Clock | None = None,
        operator: str | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.operator = operator

        self.complete: set[str] = set()
        # Steps credited by operator confirmation, not perception. The camera
        # may still see the action a moment later; that late sighting must
        # not be judged as a new action (see _process_action).
        self.confirmed_by_operator: set[str] = set()
        self.skipped: set[str] = set()
        self._suggested: set[str] = set()  # steps we've already announced
        self._skip_check_done = False
        self.role_state: dict[str, RoleState] = {}

        # Operator pause: while paused, perception events are dropped (not
        # applied, not judged) and timeouts are frozen. See pause_session().
        self.paused = False
        self._paused_at: float | None = None
        self._ignored_while_paused = 0

        # Operator presence (attended_while_open). Perception reports it as
        # StateEvent("operator.hands_in_view", bool). Until it says
        # otherwise the operator is assumed present: no camera, no alert.
        self.hands_in_view = True
        self._hands_away_since: float | None = None
        self._unattended_fired = False

        # Per-step time limits (step_time_limit): seconds each step has
        # spent actually due, accumulated tick to tick so a pause or an
        # exclusion hold simply stops the clock. See _check_step_time_limits.
        self._step_active_s: dict[str, float] = {}
        self._step_overdue_fired: set[str] = set()
        self._last_tick: float | None = self.clock.now()
        # no_extra_steps: per object, an extra action waiting out settle_s
        self._pending_extra: dict[str, dict[str, Any]] = {}

        self.out: list[EngineEvent] = []
        self._load(resolved)
        self._emit(EngineEvent(
            ts_monotonic=self.clock.now(),
            event_type="session_start",
            message=f"session start: {self.parsed.protocol_id}",
        ))
        self._announce_newly_satisfiable()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _load(self, resolved: ResolvedProtocol, preserve_state: bool = False) -> None:
        """Everything derived from a resolved protocol. Called once from
        __init__, and again from reload_protocol() with preserve_state=True
        so hot reload doesn't throw away progress on steps/roles that
        still exist in the new protocol.
        """
        self.resolved = resolved
        self.parsed: ParsedProtocol = resolved.parsed
        self.constraints_by_id: dict[str, ResolvedConstraint] = {
            c.id: c for c in resolved.constraints
        }

        self._container_roles, self._module_roles = self._classify_roles()
        self._lid_stow_zones = self._find_lid_stow_zones()
        self._has_dependent = self._compute_has_dependent()

        old_role_state = self.role_state
        new_role_state: dict[str, RoleState] = {}
        for role in self.parsed.roles:
            if preserve_state and role in old_role_state:
                new_role_state[role] = old_role_state[role]
            else:
                rs = RoleState()
                if role in self._module_roles:
                    rs.location = "in_container"
                new_role_state[role] = rs
        self.role_state = new_role_state

        if preserve_state:
            old_step_ids = set(self.complete)
            still_valid = {
                s for s in old_step_ids
                if s in self.parsed.nodes and not self.parsed.nodes[s].is_group
            }
            dropped = old_step_ids - still_valid
            self.complete = still_valid
            self.skipped &= set(self.parsed.nodes)
            self._suggested &= set(self.parsed.nodes)
            # A surviving step keeps its elapsed time; its (possibly
            # changed) limit is read from the new protocol on every tick.
            self._step_active_s = {k: v for k, v in self._step_active_s.items() if k in self.parsed.nodes}
            self._step_overdue_fired &= set(self.parsed.nodes)
            self._pending_extra = {r: p for r, p in self._pending_extra.items() if r in self.role_state}
            self._skip_check_done = False
            if dropped:
                self._emit(EngineEvent(
                    ts_monotonic=self.clock.now(),
                    event_type="protocol_reloaded",
                    message=f"steps no longer present in reloaded protocol, progress dropped: {sorted(dropped)}",
                ))

        self._resolve_skipped_by_condition()

    def _classify_roles(self) -> tuple[set[str], set[str]]:
        container_roles: set[str] = set()
        module_roles: set[str] = set()
        for step_id in self.parsed.order:
            node = self.parsed.nodes[step_id]
            if node.action == "remove_from":
                if node.source:
                    container_roles.add(node.source)
                module_roles.add(split_target(node.target)[0])
            elif node.action == "place_into":
                if node.dest:
                    container_roles.add(node.dest)
                module_roles.add(split_target(node.target)[0])
        return container_roles, module_roles

    def _find_lid_stow_zones(self) -> dict[str, str]:
        """role -> the zone id its own move_to_zone(role.lid, zone) step
        names, read from the protocol rather than assumed to be a fixed
        string — a protocol is free to call its stow zone anything."""
        zones: dict[str, str] = {}
        for step_id in self.parsed.order:
            node = self.parsed.nodes[step_id]
            if node.action == "move_to_zone":
                role, sub = split_target(node.target)
                if sub == "lid" and node.zone:
                    zones[role] = node.zone
        return zones

    def _compute_has_dependent(self) -> dict[str, bool]:
        has_dep = {s: False for s in self.parsed.order}
        for node_id, node in self.parsed.nodes.items():
            for ref in node.after:
                for leaf in self.parsed.leaf_steps(ref):
                    has_dep[leaf] = True
        return has_dep

    def _resolve_skipped_by_condition(self) -> None:
        profile = self.parsed.object_profile
        for step_id in self.parsed.order:
            node = self.parsed.nodes[step_id]
            if step_id in self.complete:
                continue
            if node.condition:
                own_role = split_target(node.target)[0]
                if not evaluate_condition(node.condition, own_role, profile):
                    self.skipped.add(step_id)

    def reload_protocol(self, new_resolved: ResolvedProtocol) -> None:
        """Hot reload: swap in a newly validated protocol without
        restarting the session. Caller is responsible for having already
        run it through scripts/validate_protocol.py — per the addendum,
        "Run the validator in CI and on every hot reload. A malformed
        protocol must fail loudly at load, never silently mid-run,"
        which is a load-time gate this method deliberately does not
        re-implement (it would need to import and shell out to the
        validator script, or duplicate its checks — the caller already
        has the validated ResolvedProtocol in hand from calling
        src.protocol.loader.resolve() + scripts.validate_protocol.validate()
        itself).
        """
        old_protocol_id = self.parsed.protocol_id
        self._load(new_resolved, preserve_state=True)
        self._emit(EngineEvent(
            ts_monotonic=self.clock.now(),
            event_type="protocol_reloaded",
            message=f"{old_protocol_id} -> {new_resolved.parsed.protocol_id}",
        ))
        self._announce_newly_satisfiable()

    # ------------------------------------------------------------------
    # Satisfiability
    # ------------------------------------------------------------------

    def prerequisites(self, step_id: str) -> set[str]:
        """The leaf steps that must be COMPLETE before step_id is due.

        A step skipped by its condition "silently does not exist for this
        run" (addendum) -- so it cannot satisfy ordering either: its OWN
        prerequisites take its place. Treating it as done let slab props
        (no lid) return a module that was never removed: return_b's only
        `after` is close_b_lid, which is skipped, so return_b became due
        the moment the container opened, with no out_of_order (found live
        2026-09-25). Now the chain passes through skipped steps:
        return_b -> close_b_lid(skipped) -> ... -> remove_b.
        """
        out: set[str] = set()
        stack = list(self.parsed.effective_after_leaf_ids(step_id))
        seen: set[str] = set()
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            if p in self.skipped or (
                p not in self.complete and getattr(self.parsed.nodes[p], "optional", False)
            ):
                # optional = allowed, never required: an undone one gates nothing
                stack.extend(self.parsed.effective_after_leaf_ids(p))
            else:
                out.add(p)
        return out

    def satisfiable_steps(self) -> set[str]:
        result = set()
        for step_id in self.parsed.order:
            if step_id in self.complete or step_id in self.skipped:
                continue
            if not (self.prerequisites(step_id) - self.complete):
                result.add(step_id)
        return result

    def _announce_newly_satisfiable(self) -> None:
        for step_id in sorted(self.satisfiable_steps() - self._suggested):
            node = self.parsed.nodes[step_id]
            self._suggested.add(step_id)
            self._emit(EngineEvent(
                ts_monotonic=self.clock.now(),
                event_type="next_step_suggested",
                step_id=step_id,
                message=node.prompt,
            ))

    # ------------------------------------------------------------------
    # Event log emission
    # ------------------------------------------------------------------

    def _emit(self, event: EngineEvent) -> None:
        self.out.append(event)

    def _violation(
        self,
        code: str,
        root_cause_id: str,
        target: str,
        message: str,
        step_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        default = self.constraints_by_id.get(_CODE_TO_DEFAULT_ID.get(code, ""))
        severity = (
            default.severity if default is not None else _ENGINE_JUDGMENT_SEVERITY.get(code, "caution")
        )
        self._emit(EngineEvent(
            ts_monotonic=self.clock.now(),
            event_type="violation",
            step_id=step_id,
            violation_type=code,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            root_cause_id=root_cause_id,
            target=target,
            message=message,
            operator=self.operator,
            extra=extra or {},
        ))

    # ------------------------------------------------------------------
    # Operator pause / resume
    # ------------------------------------------------------------------

    def pause_session(self, ts: float, note: str = "") -> None:
        """Operator paused the session. Until resume_session(): perception events
        are ignored (counted, not applied) and no timeout can fire -- a
        lid set down during a pause must not trip lid_unstowed the
        instant the session resumes.

        Known limit, stated rather than hidden: anything physically done
        during the pause is invisible to the protocol. If the operator
        finishes a step while paused, it will not be credited on resume.
        """
        if self.paused:
            return
        self.check_timeouts(ts)  # settle anything already due before freezing
        self.paused = True
        self._paused_at = ts
        self._ignored_while_paused = 0
        self._emit(EngineEvent(
            ts_monotonic=ts, event_type="session_paused", message=note or "paused by operator",
            operator=self.operator,
        ))

    def note_operator_command(self, ts: float, command: str) -> None:
        """Log an operator command that changes no protocol state."""
        self._emit(EngineEvent(
            ts_monotonic=ts, event_type="operator_command", message=command,
            operator=self.operator,
        ))

    def resume_session(self, ts: float, note: str = "") -> None:
        if not self.paused:
            return
        paused_for = max(0.0, ts - (self._paused_at or ts))
        # Shift every running timer by the pause length: the stow clock
        # resumes where it stopped rather than counting the pause.
        for rs in self.role_state.values():
            if rs.lid_detached_ts is not None:
                rs.lid_detached_ts += paused_for
        if self._hands_away_since is not None:
            self._hands_away_since += paused_for
        for p in self._pending_extra.values():
            p["since"] += paused_for
        # Step time limits accumulate tick to tick: restart from here so
        # the pause itself is never counted.
        self._last_tick = ts
        self.paused = False
        self._paused_at = None
        self._emit(EngineEvent(
            ts_monotonic=ts,
            event_type="session_resumed",
            message=note or (
                f"resumed after {paused_for:.1f}s; "
                f"{self._ignored_while_paused} perception event(s) ignored while paused"
            ),
            operator=self.operator,
            extra={"paused_for_s": paused_for, "ignored_events": self._ignored_while_paused},
        ))

    # ------------------------------------------------------------------
    # Timeouts
    # ------------------------------------------------------------------

    def check_timeouts(self, now: float) -> None:
        if self.paused:
            return
        self._check_step_time_limits(now)
        self._check_pending_extras(now)
        self._check_attendance(now)
        lid_stow = self.constraints_by_id.get("lid_stow_required")
        if lid_stow is None or not lid_stow.enabled:
            return
        timeout_s = lid_stow.params.get("timeout_s", 12)
        for role, stow_zone_id in self._lid_stow_zones.items():
            rs = self.role_state[role]
            if (
                rs.lid_detached_ts is not None
                and not rs.lid_unstowed_fired
                and rs.lid_zone != stow_zone_id
                and (now - rs.lid_detached_ts) > timeout_s
            ):
                rs.lid_unstowed_fired = True
                self._violation(
                    "lid_unstowed",
                    root_cause_id=f"{role}.lid_stow",
                    target=role,
                    message=f"{role} lid not stowed within {timeout_s}s",
                )

    def _check_step_time_limits(self, now: float) -> None:
        """step_time_limit: a step that declares its own `timeout_s` must be
        done within that many seconds of being DUE. Fires once per step,
        never blocks (operator authority), nothing after the terminal step.

        The clock runs only while the step is actually actionable. In the
        free-order reference protocol, remove_b is satisfiable the moment
        the container opens, yet one_module_at_a_time forbids starting it
        while module A is out -- a wall-clock limit on remove_b would fire
        on a CORRECT run. So a step whose module group is exclusive is held
        while another module group is in progress."""
        last = self._last_tick
        if last is not None and now < last:
            return  # never let the clock run backward
        self._last_tick = now
        if last is None or self._skip_check_done:
            return
        c = self.constraints_by_id.get("step_time_limit")
        if c is None or not c.enabled:
            return
        dt = now - last
        for step_id in sorted(self.satisfiable_steps()):
            node = self.parsed.nodes[step_id]
            limit = getattr(node, "timeout_s", None)
            if not limit or step_id in self._step_overdue_fired or self._held_by_exclusion(step_id):
                continue
            elapsed = self._step_active_s.get(step_id, 0.0) + dt
            self._step_active_s[step_id] = elapsed
            if elapsed > limit:
                self._step_overdue_fired.add(step_id)
                self._violation(
                    "step_overdue",
                    root_cause_id=f"{step_id}.time_limit",
                    target=node.target,
                    message=f"'{step_id}' not done within its {limit:g}s time limit",
                    step_id=step_id,
                    extra={"time_limit_s": limit},
                )

    def _held_by_exclusion(self, step_id: str) -> bool:
        """True if one_module_at_a_time currently forbids starting this
        step's group because another module group is in progress."""
        mutex = self.constraints_by_id.get("one_module_at_a_time")
        if mutex is None or not mutex.enabled:
            return False
        group = self._enclosing_top_group(step_id)
        if group is None or getattr(self.parsed.nodes[group], "concurrency", "forbidden") != "forbidden":
            return False
        return any(
            other != group and self.parsed.nodes[other].is_group and self._group_in_progress(other)
            for other in self.parsed.top_level
        )

    def _group_in_progress(self, group_id: str) -> bool:
        """Started (some step done) but not finished (a required step left)."""
        started = any(s in self.complete for s in self.parsed.leaf_steps(group_id))
        finished = all(s in self.complete or s in self.skipped
                       for s in self.parsed.required_leaf_steps(group_id))
        return started and not finished

    def open_modules(self) -> list[str]:
        """Module roles whose own lid is off right now."""
        return sorted(r for r in self._module_roles if self.role_state.get(r) and self.role_state[r].open)

    def attendance_status(self, now: float) -> dict[str, Any]:
        """For the GUI timer: which modules are open, whether hands are in
        view, how long they have been away (the grace clock), the limit."""
        c = self.constraints_by_id.get("attended_while_open")
        grace = float(c.params.get("grace_s", 5)) if c is not None else None
        open_mods = self.open_modules()
        away = None
        if not self.hands_in_view and self._hands_away_since is not None and open_mods:
            opened = max((self.role_state[r].lid_detached_ts or self._hands_away_since) for r in open_mods)
            ref = self._paused_at if (self.paused and self._paused_at is not None) else now
            away = max(0.0, ref - max(self._hands_away_since, opened))
        return {"enabled": bool(c is not None and c.enabled), "open_modules": open_mods,
                "hands_in_view": self.hands_in_view, "away_s": away, "grace_s": grace,
                "alerted": self._unattended_fired}

    def _check_attendance(self, now: float) -> None:
        """attended_while_open: a module with its lid off must not be left
        with nobody at it. Fires ONCE per unattended episode, after
        grace_s with no hands in view; a new episode starts when hands
        come back or every module is sealed again. The lid itself may lie
        anywhere in view -- the whole view is the stow area."""
        c = self.constraints_by_id.get("attended_while_open")
        if c is None or not c.enabled or self.hands_in_view or self._unattended_fired:
            return
        open_mods = self.open_modules()
        if not open_mods or self._hands_away_since is None:
            return
        grace = float(c.params.get("grace_s", 5))
        # the clock runs from the LATER of: hands left, module opened
        opened = max((self.role_state[r].lid_detached_ts or self._hands_away_since) for r in open_mods)
        started = max(self._hands_away_since, opened)
        if now - started > grace:
            self._unattended_fired = True
            self._violation(
                "unattended_open_module",
                root_cause_id="attendance",
                target=open_mods[0],
                message=f"{', '.join(open_mods)} open with no hands in view for {grace:g}s",
                extra={"open_modules": open_mods, "grace_s": grace},
            )

    # ------------------------------------------------------------------
    # Hard ordering guards — see module docstring
    # ------------------------------------------------------------------

    def _hard_ordering_violation(self, event: ActionEvent) -> str | None:
        role, sub = split_target(event.target)
        if event.action == "remove_from" and event.source:
            source_state = self.role_state.get(event.source)
            if source_state is not None and not source_state.open:
                return (
                    f"a module cannot leave a closed container: "
                    f"{event.source} is closed"
                )
        if event.action == "move_to_zone" and sub == "lid":
            role_state = self.role_state.get(role)
            if role_state is not None and not role_state.open:
                return f"a lid cannot be stowed before it is detached: {role}.lid"
        return None

    # ------------------------------------------------------------------
    # Matching + state effects
    # ------------------------------------------------------------------

    def _matches(self, node, event: ActionEvent) -> bool:
        if node.action != event.action or node.target != event.target:
            return False
        if node.source is not None and node.source != event.source:
            return False
        if node.dest is not None and node.dest != event.dest:
            return False
        if node.zone is not None and node.zone != event.zone:
            return False
        return True

    def _note_extra_action(self, event: ActionEvent, settle_s: float) -> None:
        """An extra action is alerted only if it is NOT undone within
        settle_s. Measured on real clips: a screw cap resting on the jar
        reads as closed, then open, then closed again within 0.5-2 s, and
        a jar hovering at the rim reads as returned, then out, then in --
        the operator did nothing wrong. An object put back as it was
        within settle_s is logged (not spoken); one that stays changed is
        extra_step, keyed per object so one cooldown covers it."""
        role, _ = split_target(event.target)
        rs = self.role_state[role]
        pending = self._pending_extra.get(role)
        if pending is None:
            pending = {"since": event.ts, "before": (rs.open, rs.location), "actions": [],
                       "settle_s": settle_s}
            self._pending_extra[role] = pending
        done = next((s for s in self.parsed.order if s in self.complete
                     and self._matches(self.parsed.nodes[s], event)), None)
        pending["actions"].append({"action": event.action, "target": event.target, "repeat_of": done})
        self._apply_state_effect(None, event)
        if (rs.open, rs.location) == pending["before"]:
            del self._pending_extra[role]
            acts = ", ".join(f"{a['action']} {a['target']}" for a in pending["actions"])
            self._emit(EngineEvent(
                ts_monotonic=event.ts,
                event_type="unmatched_action",
                target=role,
                message=(f"extra action undone within {event.ts - pending['since']:.1f}s, not alerted "
                         f"(detector jitter or put straight back): {acts}"),
                extra={"extra_reverted": pending["actions"]},
            ))

    def _check_pending_extras(self, now: float) -> None:
        for role, p in list(self._pending_extra.items()):
            if now - p["since"] < p["settle_s"]:
                continue
            del self._pending_extra[role]
            first = p["actions"][0]
            why = (f"repeats '{first['repeat_of']}', already done" if first["repeat_of"]
                   else "is not a step of this procedure")
            self._violation(
                "extra_step",
                root_cause_id=f"extra:{role}",
                target=first["target"],
                message=f"{first['action']} on '{first['target']}' {why}",
                extra={"actions": p["actions"], "action_ts": p["since"], "settle_s": p["settle_s"]},
            )

    def _changes_state(self, event: ActionEvent) -> bool:
        """Would this action change the engine's model of the world?
        Actions with no tracked state (grasp, release, dwell) count as real."""
        role, sub = split_target(event.target)
        rs = self.role_state.get(role)
        if rs is None:
            return False
        if event.action == "open":
            return not rs.open
        if event.action == "close":
            return rs.open
        if event.action == "remove_from":
            return rs.location != "out"
        if event.action == "place_into":
            return rs.location != "in_container"
        if event.action == "move_to_zone" and sub == "lid":
            return rs.lid_zone != event.zone
        return True

    def _apply_state_effect(self, node, event: ActionEvent) -> None:
        role, sub = split_target(event.target)
        rs = self.role_state.get(role)
        if rs is None:
            return

        if event.action == "open":
            rs.open = True
            if role in self._lid_stow_zones:
                rs.lid_zone = "__held__"
                rs.lid_detached_ts = event.ts
                rs.lid_unstowed_fired = False
        elif event.action == "close":
            rs.open = False
            if role in self._lid_stow_zones:
                # Re-attached directly without a separate stow: no longer
                # an unsecured floating lid, so the stow timeout no
                # longer applies. Distinct from actually reaching the
                # stow zone, but equally not a hazard.
                rs.lid_detached_ts = None
                rs.lid_unstowed_fired = False
        elif event.action == "remove_from":
            rs.location = "out"
        elif event.action == "place_into":
            rs.location = "in_container"
        elif event.action == "move_to_zone" and sub == "lid":
            rs.lid_zone = event.zone or rs.lid_zone
            if event.zone == self._lid_stow_zones.get(role):
                rs.lid_detached_ts = None
                rs.lid_unstowed_fired = False

    def _run_domain_constraints(self, node, event: ActionEvent) -> None:
        role, sub = split_target(event.target)

        if event.action == "remove_from":
            mutex = self.constraints_by_id.get("one_module_at_a_time")
            group_id = self._enclosing_top_group(node.id if hasattr(node, "id") else None)
            concurrency_ok = False
            if group_id is not None:
                grp = self.parsed.nodes[group_id]
                if getattr(grp, "concurrency", "forbidden") != "forbidden":
                    concurrency_ok = True
            if mutex is not None and mutex.enabled and not concurrency_ok:
                others_out = [
                    r
                    for r in self._module_roles
                    if r != role and self.role_state[r].location == "out"
                ]
                if others_out:
                    self._violation(
                        "mutual_exclusion_breach",
                        root_cause_id="one_module_at_a_time",
                        target=role,
                        message=f"{role} accessed while {others_out} still out",
                    )

        if event.action == "place_into":
            sealed = self.constraints_by_id.get("sealed_before_return")
            profile = self.parsed.object_profile
            has_lid = bool(
                profile
                and profile.get("roles", {}).get(role, {}).get("has_lid", False)
            )
            if sealed is not None and sealed.enabled and has_lid:
                if self.role_state[role].open:
                    self._violation(
                        "module_not_sealed",
                        root_cause_id=role,
                        target=role,
                        message=f"{role} returned while still open/unsealed",
                    )

        if event.action == "close" and event.target in self._container_roles:
            empty = self.constraints_by_id.get("container_empty_before_close")
            if empty is not None and empty.enabled:
                still_out = [
                    r for r in self._module_roles if self.role_state[r].location == "out"
                ]
                if still_out:
                    for r in still_out:
                        self._violation(
                            "module_not_returned",
                            root_cause_id=r,
                            target=r,
                            message=f"container closed with {r} still outside",
                        )

    def _enclosing_top_group(self, node_id: str | None) -> str | None:
        if node_id is None:
            return None
        chain = [node_id, *self.parsed.ancestors(node_id)]
        top_groups = set(self.parsed.top_level)
        for c in chain:
            if c in top_groups and self.parsed.nodes[c].is_group:
                return c
        return None

    # ------------------------------------------------------------------
    # End-of-run skip detection
    # ------------------------------------------------------------------

    def _run_skip_detection(self) -> None:
        if self._skip_check_done:
            return
        self._skip_check_done = True
        skip_constraint = self.constraints_by_id.get("skip")
        if skip_constraint is not None and not skip_constraint.enabled:
            return
        for step_id in self.parsed.order:
            node = self.parsed.nodes[step_id]
            if step_id in self.complete or step_id in self.skipped or node.optional:
                continue
            self._violation(
                "skip",
                root_cause_id=step_id,
                target=node.target,
                message=f"required step '{step_id}' never completed",
                step_id=step_id,
            )

    # ------------------------------------------------------------------
    # Public event processing
    # ------------------------------------------------------------------

    def process(self, event: SemanticEvent) -> None:
        if isinstance(event, StateEvent) and event.key == HANDS_IN_VIEW:
            # Presence is tracked even while paused (it is not a step, and a
            # stale value would misfire on resume); timers stay frozen.
            self._set_hands_in_view(event.ts, bool(event.value))
            return
        if self.paused and not isinstance(event, OperatorOverrideEvent):
            self._ignored_while_paused += 1
            return
        if isinstance(event, ActionEvent):
            self._process_action(event)
        elif isinstance(event, AnomalyEvent):
            self._anomaly(event.ts, event.kind, event.label)
        elif isinstance(event, StateEvent):
            self._process_state(event)
        elif isinstance(event, OperatorOverrideEvent):
            self._emit(EngineEvent(
                ts_monotonic=event.ts,
                event_type="operator_override",
                message=event.note,
                operator=self.operator,
            ))
        else:  # pragma: no cover - exhaustiveness guard
            raise TypeError(f"unknown event type: {type(event)!r}")

    def _set_hands_in_view(self, ts: float, value: bool) -> None:
        if value == self.hands_in_view:
            return
        self.hands_in_view = value
        if value:
            self._hands_away_since = None
            self._unattended_fired = False
        else:
            self._hands_away_since = ts
        self._emit(EngineEvent(
            ts_monotonic=ts, event_type="unmatched_action",
            message=f"operator hands {'back in view' if value else 'out of view'}",
            operator=self.operator,
        ))
        if not self.paused:
            self.check_timeouts(ts)

    def _process_state(self, event: StateEvent) -> None:
        # Reserved for orientation/zone-confinement predicates once
        # kinematics feeds them in. No default constraint in phase 0
        # consumes a bare StateEvent yet (wrong_orientation is opt-in
        # and disabled by default), so this only logs today.
        self._emit(EngineEvent(
            ts_monotonic=event.ts,
            event_type="unmatched_action",
            message=f"state {event.key}={event.value!r} (no consumer wired yet)",
        ))

    def _anomaly(self, ts: float, kind: str, label: str | None) -> None:
        """Something outside the experiment. Logged and announced; no
        protocol state changes, so the session continues from the step
        it was on. root_cause_id is per kind, so the alert policy's
        cooldown stops a lingering object being re-announced."""
        self._emit(EngineEvent(
            ts_monotonic=ts,
            event_type="anomaly",
            severity="caution",
            root_cause_id=f"anomaly:{kind}",
            target=label,
            message=f"{kind}: {label or 'unidentified object'}",
            extra={"kind": kind},
        ))

    def _process_action(self, event: ActionEvent) -> None:
        self.check_timeouts(event.ts)

        # An action on something that is not one of this protocol's roles
        # is not a wrong_object (that is the wrong ROLE, e.g. module_b for
        # module_a) -- the object is not part of the experiment at all.
        if split_target(event.target)[0] not in self.parsed.roles:
            self._anomaly(event.ts, "foreign_object", event.target)
            return

        late = next(
            (s for s in self.parsed.order
             if s in self.confirmed_by_operator and self._matches(self.parsed.nodes[s], event)),
            None,
        )
        if late is not None:
            # Already credited by the operator: log it, judge nothing. Else
            # a late "remove module A" reads as wrong_object for module B.
            self._emit(EngineEvent(
                ts_monotonic=event.ts,
                event_type="unmatched_action",
                step_id=late,
                target=event.target,
                message=f"perception saw '{late}' after the operator confirmed it",
            ))
            return

        guard_msg = self._hard_ordering_violation(event)
        if guard_msg:
            self._emit(EngineEvent(
                ts_monotonic=event.ts,
                event_type="engine_anomaly",
                target=event.target,
                message=guard_msg,
            ))
            return

        candidates = [
            s
            for s in self.parsed.order
            if s not in self.complete
            and s not in self.skipped
            and self._matches(self.parsed.nodes[s], event)
        ]

        if not candidates:
            self._handle_unmatched(event)
            return

        self._complete_step(candidates[0], event, status="complete")

    def _complete_step(self, step_id: str, event: ActionEvent, status: str) -> None:
        """Credit a step: state effect, domain constraints, ordering check,
        step_complete, newly unlocked steps, skip detection. Shared by
        perceived actions and operator confirmation so the two can never
        drift apart."""
        node = self.parsed.nodes[step_id]
        unmet = self.prerequisites(step_id) - self.complete

        self._apply_state_effect(node, event)
        self.complete.add(step_id)
        self._run_domain_constraints(node, event)

        out_of_order_constraint = self.constraints_by_id.get("out_of_order")
        out_of_order_enabled = out_of_order_constraint is None or out_of_order_constraint.enabled
        if unmet and out_of_order_enabled:
            self._violation(
                "out_of_order",
                root_cause_id=step_id,
                target=node.target,
                message=f"'{step_id}' attempted before prerequisites complete: {sorted(unmet)}",
                step_id=step_id,
                extra={"unmet": sorted(unmet)},
            )

        self._emit(EngineEvent(
            ts_monotonic=event.ts,
            event_type="step_complete",
            step_id=step_id,
            status=status,
            confidence=event.confidence,
            message=node.success,
        ))

        self._announce_newly_satisfiable()

        # An optional step with nothing after it is NOT the end of the run:
        # doing a permitted extra must never trigger end-of-run skip checks.
        if not self._has_dependent[step_id] and not getattr(node, "optional", False):
            self._run_skip_detection()

    def confirm_step(self, ts: float, step_id: str, note: str = "") -> bool:
        """The operator says a step is done that perception did not see
        (voice "next step"). The astronaut is the authority -- but only a
        step that is due now (satisfiable) can be confirmed, so this can
        never be used to skip ahead. The step's own state effect and
        domain constraints run exactly as if it had been seen, so timers
        and mutual exclusion stay honest. Logged twice over: an
        operator_override naming the step, then step_complete with status
        "operator_confirmed" -- the record shows the camera did not see it.
        Returns False (nothing changed) if paused or the step is not due."""
        if self.paused or step_id not in self.satisfiable_steps():
            return False
        self.check_timeouts(ts)
        node = self.parsed.nodes[step_id]
        self._emit(EngineEvent(
            ts_monotonic=ts,
            event_type="operator_override",
            step_id=step_id,
            target=node.target,
            message=note or f"operator confirmed '{step_id}'",
            operator=self.operator,
        ))
        event = ActionEvent(
            ts=ts, action=node.action, target=node.target,
            source=node.source, dest=node.dest, zone=node.zone, confidence=1.0,
        )
        self.confirmed_by_operator.add(step_id)
        self._complete_step(step_id, event, status="operator_confirmed")
        return True

    def _handle_unmatched(self, event: ActionEvent) -> None:
        pending_role = split_target(event.target)[0]
        if pending_role in self._pending_extra and self._changes_state(event):
            # The same object is mid-extra: this action continues it or
            # undoes it (cap put back on) -- not a wrong_object attempt
            # at whatever step happens to be due.
            self._note_extra_action(event, self._pending_extra[pending_role]["settle_s"])
            return
        action_used = any(
            self.parsed.nodes[s].action == event.action for s in self.parsed.order
        )
        if action_used:
            same_action_satisfiable = [
                s
                for s in self.satisfiable_steps()
                if self.parsed.nodes[s].action == event.action
            ]
            wrong_object_constraint = self.constraints_by_id.get("wrong_object")
            wrong_object_enabled = (
                wrong_object_constraint is None or wrong_object_constraint.enabled
            )
            if len(same_action_satisfiable) == 1 and wrong_object_enabled:
                expected = self.parsed.nodes[same_action_satisfiable[0]]
                self._violation(
                    "wrong_object",
                    root_cause_id=same_action_satisfiable[0],
                    target=event.target,
                    message=(
                        f"expected {event.action} on '{expected.target}', "
                        f"got '{event.target}'"
                    ),
                )
                return
        extra = self.constraints_by_id.get("no_extra_steps")
        if self._skip_check_done and self._changes_state(event):
            # After "Experiment complete." the crew packs up (opens the box,
            # takes the props out): record it, never alert on it -- like the
            # step time limits, the procedure's rules end with the procedure.
            self._apply_state_effect(None, event)
            self._emit(EngineEvent(
                ts_monotonic=event.ts, event_type="unmatched_action", target=event.target,
                message=f"{event.action} on '{event.target}' after the procedure ended (not alerted)",
            ))
            return
        if extra is not None and extra.enabled and self._changes_state(event):
            # PS 26174: "alert when ... an out of sequence step is ADDED".
            # An action on an experiment object that no remaining step asks
            # for: a repeat of a finished step, or one the protocol never
            # has. A protocol that wants to allow such an action declares
            # it as an `optional` step. Only a real change counts (opening
            # what is already open is a duplicate report, not an action).
            # The world DID change, so the state follows: a returned module
            # taken out again makes a later close flag module_not_returned.
            self._note_extra_action(event, float(extra.params.get("settle_s", 3.0)))
            return
        self._emit(EngineEvent(
            ts_monotonic=event.ts,
            event_type="unmatched_action",
            target=event.target,
            message=f"{event.action} on '{event.target}' not recognized by this protocol",
        ))

    # ------------------------------------------------------------------
    # Session resume
    # ------------------------------------------------------------------

    def resume(self, prior_events: list[EngineEvent]) -> None:
        """Reload a session log and pick up mid-protocol: replay only the
        state-mutating facts (completions), not the alerting/suggestion
        side effects, so resuming never re-speaks or re-suggests stale
        prompts."""
        for e in prior_events:
            if e.event_type == "step_complete" and e.step_id:
                self.complete.add(e.step_id)
                self._suggested.add(e.step_id)
                if e.status == "operator_confirmed":
                    self.confirmed_by_operator.add(e.step_id)
        self._announce_newly_satisfiable()

    def resume_from_log(self, path: str) -> None:
        """Convenience wrapper: resume() straight from a JSONL session
        log path, going through src.logging.session_log's own record
        shape rather than requiring the caller to reconstruct
        EngineEvents by hand."""
        from src.logging.session_log import load_events_for_resume

        self.resume(load_events_for_resume(path))


_CODE_TO_DEFAULT_ID = {
    "mutual_exclusion_breach": "one_module_at_a_time",
    "loose_object": "no_loose_objects",
    "module_not_sealed": "sealed_before_return",
    "module_not_returned": "container_empty_before_close",
    "lid_unstowed": "lid_stow_required",
    "unattended_open_module": "attended_while_open",
    "step_overdue": "step_time_limit",
    "extra_step": "no_extra_steps",
    "wrong_orientation": "correct_insertion_orientation",
    "out_of_order": "out_of_order",
    "skip": "skip",
    "wrong_object": "wrong_object",
}
