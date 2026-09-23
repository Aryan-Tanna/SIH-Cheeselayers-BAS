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
    "out_of_order",
    "skip",
    "wrong_object",
})


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

    def satisfiable_steps(self) -> set[str]:
        result = set()
        for step_id in self.parsed.order:
            if step_id in self.complete or step_id in self.skipped:
                continue
            unmet = self.parsed.effective_after_leaf_ids(step_id) - (
                self.complete | self.skipped
            )
            if not unmet:
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
        unmet = self.parsed.effective_after_leaf_ids(step_id) - (
            self.complete | self.skipped
        )

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

        if not self._has_dependent[step_id]:
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
    "wrong_orientation": "correct_insertion_orientation",
    "out_of_order": "out_of_order",
    "skip": "skip",
    "wrong_object": "wrong_object",
}
