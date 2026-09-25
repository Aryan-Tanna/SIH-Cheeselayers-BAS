"""Semantic event types exchanged with the protocol engine.

These are POST-fusion events: by the time something becomes a
SemanticEvent, the debouncer has already required k-of-n frame
agreement (src/protocol/debounce.py) and kinematics has already turned
raw geometry into a discrete primitive. The engine never sees a raw
detection or a bounding box.

ts is always a monotonic seconds value captured at frame acquisition,
never at processing time — see CLAUDE.md logging requirements. In
replay, ts comes straight from the fixture/stub-detector's `t` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# The primitive set is fixed for this phase (see addendum). A new kind of
# physical action requires a new primitive in code, not config.
Action = Literal[
    "grasp",
    "release",
    "open",
    "close",
    "place_into",
    "remove_from",
    "move_to_zone",
    "dwell",
]


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """An operator performed a primitive action on a target."""

    ts: float
    action: Action
    target: str
    source: str | None = None
    dest: str | None = None
    zone: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class StateEvent:
    """A derived predicate changed value.

    Keys are dotted, e.g. "module_a.sealed", "module_a.in_zone:stow_zone",
    "module_a.orientation_ok". These feed precondition/timeout constraint
    evaluation; they are not steps themselves.
    """

    ts: float
    key: str
    value: Any


@dataclass(frozen=True, slots=True)
class OperatorOverrideEvent:
    """The astronaut explicitly overrode an alert or a block.

    Operator authority is absolute: this is a logged event, never a
    request the engine can refuse.
    """

    ts: float
    note: str = ""


@dataclass(frozen=True, slots=True)
class AnomalyEvent:
    """Something outside the experiment happened -- e.g. an object that
    is not bound to any protocol role was detected or grasped.

    Not a procedure violation: protocol state is untouched and the
    session continues from the step it was on. It is logged and spoken
    as a single generic "anomaly" alert (subject to the same root-cause
    cooldown as violations, so a lingering object is not re-announced
    every frame).
    """

    ts: float
    kind: str = "foreign_object"
    label: str | None = None  # detector label / target name, if any
    confidence: float = 1.0


SemanticEvent = ActionEvent | StateEvent | OperatorOverrideEvent | AnomalyEvent


EngineEventType = Literal[
    "session_start",
    "step_complete",
    "step_skipped",
    "next_step_suggested",
    "violation",
    "operator_override",
    "protocol_reloaded",
    "session_end",
    # Internal-consistency signals, not operator-facing violations:
    # engine_anomaly = an event contradicted known physical state (see
    # ProtocolEngine's hard-ordering guards); unmatched_action = an event
    # used an action/target pair this protocol never declares.
    "engine_anomaly",
    "unmatched_action",
    # Operator-facing, not violations: something outside the experiment
    # (see AnomalyEvent), and operator pause/resume of the session.
    "anomaly",
    "session_paused",
    "session_resumed",
    # Operator voice/GUI command that changes no protocol state (e.g.
    # quiet mode) -- logged so the record shows why prompts went silent.
    "operator_command",
]

Severity = Literal["advisory", "caution", "warning"]

ViolationCode = Literal[
    "skip",
    "wrong_object",
    "out_of_order",
    "mutual_exclusion_breach",
    "lid_unstowed",
    "unattended_open_module",
    "module_not_sealed",
    "module_not_returned",
    "premature_close",
    "loose_object",
    "wrong_orientation",
]


@dataclass(frozen=True, slots=True)
class EngineEvent:
    """Output of the protocol engine. One of these per JSONL log line.

    Field names track src/logging/session_log.py's schema directly.
    """

    ts_monotonic: float
    event_type: EngineEventType
    step_id: str | None = None
    status: str | None = None
    confidence: float | None = None
    violation_type: ViolationCode | None = None
    severity: Severity | None = None
    root_cause_id: str | None = None
    target: str | None = None
    message: str | None = None
    operator: str | None = None
    geometry_status: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
