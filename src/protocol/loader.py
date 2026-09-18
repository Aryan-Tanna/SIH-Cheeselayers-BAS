"""Config layer: loads defaults.yaml + a protocol JSON + an object profile,
resolves the inheritance chain, and parses the step/group tree into a form
the engine and validator can both walk.

Resolution order (see configs/defaults.yaml `resolution_order` and the
addendum's three-tier posture):

  1. hard ordering       — engine-enforced, in code, never in this file.
  2. non-overridable defaults (`overridable: false` in defaults.yaml)
     — always merged in; a protocol `disabled: true` on one of these is
       rejected with a warning and the default stays enabled.
  3. explicit protocol `constraints` entries — replace a default of the
     same id.
  4. protocol `strict_mode` flags — toggle specific defaults on/off or
     inject an ordering edge (force_module_order).
  5. overridable defaults from defaults.yaml, for anything not touched
     by 3 or 4.
  6. engine fallbacks — not applicable here, engine-internal.

The loader MUST print the resolved constraint set at startup, marking
each entry [default] or [protocol] — see print_resolved_constraints().
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEFAULTS_PATH = Path("configs/defaults.yaml")

# ids from configs/defaults.yaml whose `overridable: false` marks them as
# tier-2 (non-overridable). Kept as a derived set, not hardcoded, in
# resolve_constraints() — this constant documents the expectation so a
# test can assert the derivation found exactly these.
EXPECTED_NON_OVERRIDABLE_IDS = frozenset(
    {"no_loose_objects", "container_empty_before_close"}
)

# The two physical impossibilities the engine enforces unconditionally,
# in code, regardless of protocol or strict_mode. Documentation-only here;
# actually enforced in src/protocol/engine.py. A third item — "a
# container cannot be closed while a module is outside it" — was
# originally listed here but was miscategorised: it's not a physical
# impossibility (an operator can push a lid shut over a module still
# outside it), so it is enforced as the non-overridable
# container_empty_before_close POLICY constraint below instead, not a
# hard block. See configs/defaults.yaml's note_hard for the full reasoning.
HARD_ORDERING_RULES: tuple[str, ...] = (
    "a module cannot leave a closed container",
    "a lid cannot be stowed before it is detached",
)


class ProtocolLoadError(ValueError):
    """Raised for structurally invalid config that the validator should
    have caught earlier. The loader is not a substitute for
    scripts/validate_protocol.py — it does the minimal checking needed
    to resolve constraints and build the step graph safely."""


# --------------------------------------------------------------------------
# Raw loading
# --------------------------------------------------------------------------


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Step/group tree
# --------------------------------------------------------------------------


@dataclass
class StepDef:
    id: str
    action: str
    target: str
    source: str | None = None
    dest: str | None = None
    zone: str | None = None
    after: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    condition: str | None = None
    optional: bool = False
    min_duration_s: float | None = None
    timeout_s: float | None = None
    on_timeout: str | None = None
    prompt: str | None = None
    success: str | None = None
    is_group: bool = False


@dataclass
class GroupDef:
    id: str
    after: list[str] = field(default_factory=list)
    concurrency: str = "forbidden"
    condition: str | None = None
    children: list[str] = field(default_factory=list)
    prompt: str | None = None
    success: str | None = None
    is_group: bool = True


Node = StepDef | GroupDef


@dataclass
class ParsedProtocol:
    protocol_id: str
    version: str
    roles: dict[str, Any]
    zones: dict[str, Any]
    nodes: dict[str, Node]
    parent: dict[str, str | None]
    order: list[str]  # declaration order, leaf steps only
    top_level: list[str]  # ids at the root of the steps array
    object_profile: dict[str, Any] | None
    strict_mode: dict[str, Any]
    raw: dict[str, Any]

    def leaf_steps(self, node_id: str) -> list[str]:
        n = self.nodes.get(node_id)
        if n is None:
            return []
        if not n.is_group:
            return [node_id]
        out: list[str] = []
        for child in n.children:  # type: ignore[union-attr]
            out.extend(self.leaf_steps(child))
        return out

    def required_leaf_steps(self, node_id: str) -> list[str]:
        return [
            s
            for s in self.leaf_steps(node_id)
            if not self.nodes[s].optional  # type: ignore[union-attr]
        ]

    def ancestors(self, node_id: str) -> list[str]:
        """Enclosing group ids, innermost first."""
        out = []
        p = self.parent.get(node_id)
        while p is not None:
            out.append(p)
            p = self.parent.get(p)
        return out

    def effective_after_leaf_ids(self, node_id: str) -> set[str]:
        """All leaf-step ids that must be COMPLETE-or-SKIPPED before
        node_id becomes satisfiable: node_id's own `after` (expanded
        through any group ids it names) UNION the same for every
        enclosing group, transitively.

        This is the mechanism, not group membership, that produces
        ordering — per the addendum, "groups are not atomic."
        """
        result: set[str] = set()
        for chain_id in [node_id, *self.ancestors(node_id)]:
            node = self.nodes.get(chain_id)
            if node is None:
                continue
            for ref in node.after:
                result |= set(self.leaf_steps(ref)) if ref in self.nodes else set()
        return result - {node_id}


def _parse_node(
    raw: dict[str, Any],
    nodes: dict[str, Node],
    parent: dict[str, str | None],
    order: list[str],
    parent_id: str | None,
) -> str:
    node_id = raw["id"]
    parent[node_id] = parent_id
    if raw.get("type") == "group":
        children = [
            _parse_node(child, nodes, parent, order, node_id)
            for child in raw["steps"]
        ]
        nodes[node_id] = GroupDef(
            id=node_id,
            after=list(raw.get("after", [])),
            concurrency=raw.get("concurrency", "forbidden"),
            condition=raw.get("condition"),
            children=children,
            prompt=raw.get("prompt"),
            success=raw.get("success"),
        )
    else:
        nodes[node_id] = StepDef(
            id=node_id,
            action=raw["action"],
            target=raw["target"],
            source=raw.get("source"),
            dest=raw.get("dest"),
            zone=raw.get("zone"),
            after=list(raw.get("after", [])),
            requires=list(raw.get("requires", [])),
            condition=raw.get("condition"),
            optional=bool(raw.get("optional", False)),
            min_duration_s=raw.get("min_duration_s"),
            timeout_s=raw.get("timeout_s"),
            on_timeout=raw.get("on_timeout"),
            prompt=raw.get("prompt"),
            success=raw.get("success"),
        )
        order.append(node_id)
    return node_id


def parse_protocol(raw: dict[str, Any]) -> ParsedProtocol:
    nodes: dict[str, Node] = {}
    parent: dict[str, str | None] = {}
    order: list[str] = []
    top_level = [
        _parse_node(step_raw, nodes, parent, order, None)
        for step_raw in raw["steps"]
    ]
    return ParsedProtocol(
        protocol_id=raw["protocol_id"],
        version=raw.get("version", ""),
        roles=raw.get("roles", {}),
        zones=raw.get("zones", {}),
        nodes=nodes,
        parent=parent,
        order=order,
        top_level=top_level,
        object_profile=None,
        strict_mode=raw.get("strict_mode", {}) or {},
        raw=raw,
    )


# --------------------------------------------------------------------------
# Constraint resolution
# --------------------------------------------------------------------------

# strict_mode key -> (default constraint id, semantics)
_STRICT_MODE_TOGGLES = {
    "require_lid_stow": "lid_stow_required",
    "require_sealed_before_return": "sealed_before_return",
    "require_orientation": "correct_insertion_orientation",
}


@dataclass
class ResolvedConstraint:
    id: str
    tier: str  # "non_overridable" | "overridable" | "protocol"
    origin: str  # "default" | "protocol"
    enabled: bool
    type: str | None
    severity: str | None
    violation_code: str | None
    basis: str | None
    note: str | None = None
    # Full merged constraint dict (timeout_s, grace_s, scope, permitted_zones,
    # expression, ...) so the engine can pull whatever a given constraint
    # type needs without the loader having to know every field in advance.
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedProtocol:
    parsed: ParsedProtocol
    constraints: list[ResolvedConstraint]
    alert_policy: dict[str, Any]
    timing: dict[str, Any]
    module_order: str
    warnings: list[str]


def resolve_constraints(
    defaults: dict[str, Any], protocol_raw: dict[str, Any]
) -> tuple[list[ResolvedConstraint], list[str]]:
    warnings: list[str] = []
    default_constraints: dict[str, Any] = defaults.get("default_constraints", {})
    protocol_constraints: dict[str, Any] = {
        c["id"]: c for c in protocol_raw.get("constraints", [])
    }
    strict_mode: dict[str, Any] = protocol_raw.get("strict_mode", {}) or {}

    non_overridable_ids = {
        cid
        for cid, cdef in default_constraints.items()
        if cdef.get("overridable") is False
    }

    resolved: list[ResolvedConstraint] = []

    for cid, cdef in default_constraints.items():
        tier = "non_overridable" if cid in non_overridable_ids else "overridable"
        enabled = cdef.get("enabled_by_default", True)
        origin = "default"
        note = None

        if cid in protocol_constraints:
            pc = protocol_constraints[cid]
            if cid in non_overridable_ids and pc.get("disabled"):
                warnings.append(
                    f"protocol tried to disable non-overridable default "
                    f"'{cid}' - ignored, kept enabled."
                )
                note = "protocol attempted disable; rejected"
            else:
                origin = "protocol"
                enabled = not pc.get("disabled", False)
                cdef = {**cdef, **pc}

        # strict_mode toggle applies only if the protocol didn't already
        # give this id an explicit entry (tier 3 outranks tier 4).
        toggle_key = next(
            (k for k, v in _STRICT_MODE_TOGGLES.items() if v == cid), None
        )
        if toggle_key and toggle_key in strict_mode and cid not in protocol_constraints:
            enabled = bool(strict_mode[toggle_key])
            origin = "protocol"
            note = f"via strict_mode.{toggle_key}"

        resolved.append(
            ResolvedConstraint(
                id=cid,
                tier=tier,
                origin=origin,
                enabled=enabled,
                type=cdef.get("type"),
                severity=cdef.get("severity"),
                violation_code=cdef.get("violation_code"),
                basis=cdef.get("basis"),
                note=note,
                params=cdef,
            )
        )

    # Protocol constraints with no matching default id are additions.
    for cid, pc in protocol_constraints.items():
        if cid in default_constraints:
            continue
        resolved.append(
            ResolvedConstraint(
                id=cid,
                tier="protocol",
                origin="protocol",
                enabled=not pc.get("disabled", False),
                type=pc.get("type"),
                severity=pc.get("severity"),
                violation_code=pc.get("violation_code"),
                basis=pc.get("basis"),
                params=pc,
            )
        )

    return resolved, warnings


def resolve_alert_policy(
    defaults: dict[str, Any], protocol_raw: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(defaults.get("default_alert_policy", {}))
    merged.pop("note", None)
    merged.update(protocol_raw.get("alert_policy", {}) or {})
    return merged


def resolve_timing(
    defaults: dict[str, Any], protocol_raw: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(defaults.get("default_timing", {}))
    merged.pop("calibration_note", None)
    merged.update(protocol_raw.get("timing", {}) or {})
    return merged


def resolve_module_order(defaults: dict[str, Any], parsed: ParsedProtocol) -> str:
    """This is THE check that tells you whether group membership is
    being (mis)treated as ordering: it reports free vs strict from the
    same two sources apply_force_module_order() itself reads
    (defaults.yaml's default_ordering, and strict_mode.force_module_order)
    — not a guess, not derived from group declaration order.
    """
    forced = parsed.strict_mode.get("force_module_order")
    if forced:
        return (
            f"strict - '{forced}' must fully complete before its top-level "
            f"sibling groups (strict_mode.force_module_order)"
        )
    default_free = defaults.get("default_ordering", {}).get("module_order", "free")
    return (
        f"{default_free} - top-level groups may interleave; group "
        f"membership alone implies no ordering, only explicit `after` "
        f"edges do (see configs/defaults.yaml default_ordering)"
    )


def apply_force_module_order(parsed: ParsedProtocol) -> None:
    """strict_mode.force_module_order: the named group id must complete
    before every other top-level group that is not itself and not
    already ordered relative to it. Implemented as a synthetic `after`
    edge injected into the other groups — same mechanism explicit
    protocol authors use, just injected rather than written by hand.
    """
    forced = parsed.strict_mode.get("force_module_order")
    if not forced:
        return
    for tid in parsed.top_level:
        if tid == forced:
            continue
        node = parsed.nodes[tid]
        if forced not in node.after:
            node.after.append(forced)


def resolve(
    protocol_path: str | Path,
    defaults_path: str | Path = DEFAULT_DEFAULTS_PATH,
) -> ResolvedProtocol:
    defaults = load_yaml(defaults_path)
    protocol_raw = load_json(protocol_path)

    parsed = parse_protocol(protocol_raw)
    apply_force_module_order(parsed)

    if protocol_raw.get("object_profile"):
        try:
            parsed.object_profile = load_yaml(protocol_raw["object_profile"])
        except FileNotFoundError:
            parsed.object_profile = None

    constraints, warnings = resolve_constraints(defaults, protocol_raw)
    alert_policy = resolve_alert_policy(defaults, protocol_raw)
    timing = resolve_timing(defaults, protocol_raw)
    module_order = resolve_module_order(defaults, parsed)

    return ResolvedProtocol(
        parsed=parsed,
        constraints=constraints,
        alert_policy=alert_policy,
        timing=timing,
        module_order=module_order,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Startup printout — an author who never opened defaults.yaml must still
# see what is being enforced.
# --------------------------------------------------------------------------


def format_resolved_report(
    resolved: ResolvedProtocol, implemented_ids: frozenset[str] | None = None
) -> str:
    lines: list[str] = []
    p = resolved.parsed
    lines.append(f"Protocol: {p.protocol_id} v{p.version}")
    lines.append("")
    lines.append("Hard ordering [engine] (non-negotiable, not in any config file):")
    for rule in HARD_ORDERING_RULES:
        lines.append(f"  [engine]   {rule}")
    lines.append("")
    lines.append(f"Ordering: {resolved.module_order}")
    lines.append("")
    lines.append("Resolved constraints:")
    header = (
        f"  {'id':<28} {'tier':<16} {'origin':<10} {'enabled':<8} "
        f"{'code':<26} {'severity':<10} {'status':<28} basis"
    )
    lines.append(header)
    for c in sorted(resolved.constraints, key=lambda c: c.id):
        tag = "[protocol]" if c.origin == "protocol" else "[default]"
        if implemented_ids is None:
            status = "-"
        elif c.id in implemented_ids:
            status = "evaluated"
        else:
            status = "declared, NOT evaluated (needs kinematics)"
        lines.append(
            f"  {c.id:<28} {c.tier:<16} {tag:<10} {str(c.enabled):<8} "
            f"{(c.violation_code or '-'):<26} {(c.severity or '-'):<10} {status:<28} {c.basis or '-'}"
        )
    if resolved.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in resolved.warnings:
            lines.append(f"  ! {w}")
    lines.append("")
    lines.append("Alert policy (resolved):")
    for k, v in resolved.alert_policy.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Timing (resolved):")
    for k, v in resolved.timing.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def print_resolved_constraints(
    resolved: ResolvedProtocol, implemented_ids: frozenset[str] | None = None
) -> None:
    print(format_resolved_report(resolved, implemented_ids))
