#!/usr/bin/env python3
"""Validate a protocol JSON against configs/protocol.schema.json and the
addendum's semantic rules. Run in CI and on every hot reload — a
malformed protocol must fail loudly at load, never silently mid-run.

Usage:
    python scripts/validate_protocol.py configs/protocols/bas_specimen_v1.json
    python scripts/validate_protocol.py configs/protocols/bas_specimen_v1.json --defaults configs/defaults.yaml

Exit code 0 = valid, 1 = errors found (all printed with line numbers).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.protocol.engine import evaluate_condition, split_target  # noqa: E402
from src.protocol.lineindex import LineIndex  # noqa: E402
from src.protocol.loader import (  # noqa: E402
    ParsedProtocol,
    load_yaml,
    parse_protocol,
    print_resolved_constraints,
    resolve,
    resolve_constraints,
)
from src.protocol.loader import REPO_ROOT  # noqa: E402,F811  frozen-aware (packaged app)

SCHEMA_PATH = REPO_ROOT / "configs" / "protocol.schema.json"

# Vocabulary a protocol must never name directly (addendum: "Roles, not
# colours" — a protocol that names a colour or a shape is a bug). Not
# exhaustive; extend as new prop families are added.
BANNED_COLOURS = {
    "red", "yellow", "blue", "green", "white", "black", "orange",
    "purple", "pink", "gray", "grey", "brown",
}
BANNED_SHAPES = {
    "jar", "box", "slab", "cylinder", "cylindrical", "rectangular",
    "rectangle", "round", "square", "cuboid", "cube",
}
BANNED_WORDS = BANNED_COLOURS | BANNED_SHAPES


class Finding:
    def __init__(self, line: int | None, message: str) -> None:
        self.line = line
        self.message = message

    def __str__(self) -> str:
        # "approx" because LineIndex is a regex heuristic over
        # conventionally-formatted JSON, not a position-tracking parser —
        # see src/protocol/lineindex.py's module docstring. It can point
        # at the wrong line on adversarially reformatted JSON.
        loc = f"approx line {self.line}" if self.line else "line unknown"
        return f"  [{loc}] {self.message}"


def check_schema(raw: dict, schema: dict) -> list[Finding]:
    validator = jsonschema.Draft7Validator(schema)
    findings = []
    for err in sorted(validator.iter_errors(raw), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in err.path) or "(root)"
        findings.append(Finding(None, f"schema: {path}: {err.message}"))
    return findings


def check_after_references(parsed: ParsedProtocol, idx: LineIndex) -> list[Finding]:
    findings = []
    for node_id, node in parsed.nodes.items():
        for ref in node.after:
            if ref not in parsed.nodes:
                findings.append(Finding(
                    idx.line_for_id(node_id),
                    f"'{node_id}'.after references undefined id '{ref}'",
                ))
    return findings


def check_cycles(parsed: ParsedProtocol, idx: LineIndex) -> list[Finding]:
    findings = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s: WHITE for s in parsed.order}
    stack_path: list[str] = []

    def edges(step_id: str) -> set[str]:
        # Only count references that actually resolve — check_after_references
        # already reports dangling ones; don't double-report as a cycle.
        return {
            leaf
            for leaf in parsed.effective_after_leaf_ids(step_id)
            if leaf in parsed.nodes
        }

    def visit(step_id: str) -> bool:
        color[step_id] = GRAY
        stack_path.append(step_id)
        for nxt in edges(step_id):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                cycle = " -> ".join([*stack_path, nxt])
                findings.append(Finding(
                    idx.line_for_id(step_id),
                    f"dependency cycle: {cycle}",
                ))
                stack_path.pop()
                color[step_id] = BLACK
                return True
            if color[nxt] == WHITE:
                if visit(nxt):
                    stack_path.pop()
                    color[step_id] = BLACK
                    return True
        stack_path.pop()
        color[step_id] = BLACK
        return False

    for s in parsed.order:
        if color[s] == WHITE:
            visit(s)
    return findings


def check_targets_resolve(parsed: ParsedProtocol, idx: LineIndex) -> list[Finding]:
    findings = []
    role_names = set(parsed.roles)
    zone_names = set(parsed.zones)
    for step_id in parsed.order:
        node = parsed.nodes[step_id]
        line = idx.line_for_id(step_id)
        for field_name, value in (
            ("target", node.target),
            ("source", node.source),
            ("dest", node.dest),
        ):
            if value is None:
                continue
            role, _sub = split_target(value)
            if role not in role_names:
                findings.append(Finding(
                    line, f"'{step_id}'.{field_name} '{value}' does not resolve to a declared role",
                ))
        if node.zone is not None and node.zone not in zone_names:
            findings.append(Finding(
                line, f"'{step_id}'.zone '{node.zone}' is not declared in this protocol's zones",
            ))
    return findings


def check_roles_bound_in_profile(parsed: ParsedProtocol, idx: LineIndex, profile: dict | None) -> list[Finding]:
    findings = []
    if profile is None:
        findings.append(Finding(
            idx.line_for_object_key("roles"),
            "object_profile is missing or failed to load; cannot verify roles are bound",
        ))
        return findings
    profile_roles = profile.get("roles", {})
    for role in parsed.roles:
        if role not in profile_roles:
            findings.append(Finding(
                idx.line_for_key_value("roles"),
                f"role '{role}' is not bound in object profile",
            ))
    return findings


def check_zones_rack_frame(raw: dict, idx: LineIndex) -> list[Finding]:
    findings = []
    zones = raw.get("zones", {})
    for zone_name, zone_def in zones.items():
        frame = zone_def.get("frame", "rack")
        zone_line = idx.line_for_object_key(zone_name)
        if frame == "image":
            frame_line = None
            if zone_line:
                # Bound the forward search so it can't spill into the
                # next zone's block.
                next_line = None
                for other_name in zones:
                    if other_name == zone_name:
                        continue
                    ol = idx.line_for_object_key(other_name)
                    if ol and ol > zone_line and (next_line is None or ol < next_line):
                        next_line = ol
                frame_line = idx.line_for_key_value(
                    "frame", "image", after_line=zone_line, before_line=next_line
                )
            findings.append(Finding(
                frame_line or zone_line,
                f"zone '{zone_name}' declares frame: image - must be frame: rack "
                f"(an image-frame zone breaks the moment the rig tilts)",
            ))
    return findings


def check_no_colour_or_shape_names(raw: dict, idx: LineIndex) -> list[Finding]:
    findings = []

    def scan(value: str, context: str) -> None:
        tokens = re.split(r"[^a-zA-Z]+", value.lower())
        hit = BANNED_WORDS.intersection(tokens)
        if hit:
            findings.append(Finding(
                idx.line_for_id(context) or idx.line_for_key_value(context),
                f"'{context}' = '{value}' names a colour/shape ({sorted(hit)}) - use an abstract role",
            ))

    for role in raw.get("roles", {}):
        scan(role, role)
    for step in _flatten_steps(raw.get("steps", [])):
        for field_name in ("id", "target", "source", "dest"):
            v = step.get(field_name)
            if v:
                scan(v, step["id"])
    return findings


def _flatten_steps(steps: list[dict]) -> list[dict]:
    out = []
    for s in steps:
        out.append(s)
        if s.get("type") == "group":
            out.extend(_flatten_steps(s.get("steps", [])))
    return out


def check_constraints_have_basis(raw: dict, idx: LineIndex) -> list[Finding]:
    findings = []
    for c in raw.get("constraints", []):
        if "basis" not in c:
            findings.append(Finding(
                idx.line_for_id(c["id"]),
                f"constraint '{c['id']}' has no basis field",
            ))
    return findings


def check_disabled_non_overridable(raw: dict, idx: LineIndex, defaults: dict) -> list[Finding]:
    findings = []
    default_constraints = defaults.get("default_constraints", {})
    non_overridable = {
        cid for cid, cdef in default_constraints.items() if cdef.get("overridable") is False
    }
    for c in raw.get("constraints", []):
        if c.get("disabled") and c["id"] in non_overridable:
            findings.append(Finding(
                idx.line_for_id(c["id"]),
                f"constraint '{c['id']}' is non-overridable and cannot be disabled",
            ))
    return findings


# Step fields the schema accepts but the engine never reads. Accepting them
# silently would let an author believe something is enforced that is not.
_UNENFORCED_STEP_FIELDS = ("requires", "min_duration_s", "on_timeout")  # on_timeout: only "alert" is real


def check_unenforced_fields(raw: dict, idx: LineIndex, defaults: dict) -> list[Finding]:
    """Refuse anything that would validate but never be enforced: a
    constraint with a NEW id (the engine enforces the built-in rules by
    id -- a protocol may change them, not invent new ones), step fields
    the engine ignores, concurrency 'required' (enforced no differently
    from 'permitted'), and a zero time limit."""
    findings = []
    default_ids = set(defaults.get("default_constraints", {}))
    for c in raw.get("constraints", []):
        if c["id"] not in default_ids:
            findings.append(Finding(
                idx.line_for_id(c["id"]),
                f"constraint '{c['id']}' is not a built-in rule, so the engine would never enforce it "
                f"-- change a built-in rule by using its id (built-in: {', '.join(sorted(default_ids))})",
            ))
    for s in _flatten_steps(raw.get("steps", [])):
        for key in _UNENFORCED_STEP_FIELDS:
            if key == "on_timeout" and s.get(key) == "alert":
                continue  # alerting IS what a time limit does
            if key in s:
                findings.append(Finding(
                    idx.line_for_id(s["id"]),
                    f"step '{s['id']}': '{key}' is not enforced by the engine -- remove it",
                ))
        if s.get("type") == "group" and s.get("concurrency") == "required":
            findings.append(Finding(
                idx.line_for_id(s["id"]),
                f"group '{s['id']}': concurrency 'required' is not enforced (it behaves as "
                "'permitted') -- use 'permitted'",
            ))
        if s.get("type") != "group" and "timeout_s" in s and not s["timeout_s"] > 0:
            findings.append(Finding(
                idx.line_for_id(s["id"]),
                f"step '{s['id']}': time limit (timeout_s) must be more than 0 seconds",
            ))
    return findings


def check_reachable(parsed: ParsedProtocol, idx: LineIndex, profile: dict | None) -> list[Finding]:
    """Fixpoint reachability: assuming every required, non-skipped step
    eventually completes, does every step (in particular the sink(s) —
    e.g. close_container) ever become satisfiable? A genuine cycle or a
    dangling reference already fails their own dedicated checks; this
    catches the remaining case — a step permanently blocked because one
    of its prerequisites can never resolve (e.g. it depends on a step
    that is itself skipped by condition AND required elsewhere in a way
    that can't be satisfied)."""
    skipped: set[str] = set()
    for step_id in parsed.order:
        node = parsed.nodes[step_id]
        if node.condition:
            role = split_target(node.target)[0]
            try:
                if not evaluate_condition(node.condition, role, profile):
                    skipped.add(step_id)
            except ValueError:
                pass  # reported elsewhere if malformed; don't crash validation
    resolved: set[str] = set(skipped)
    changed = True
    while changed:
        changed = False
        for step_id in parsed.order:
            if step_id in resolved:
                continue
            unmet = parsed.effective_after_leaf_ids(step_id) - resolved
            unmet = {u for u in unmet if u in parsed.nodes}  # ignore dangling (reported elsewhere)
            if not unmet:
                resolved.add(step_id)
                changed = True

    findings = []
    unreached = [s for s in parsed.order if s not in resolved]
    for step_id in unreached:
        findings.append(Finding(
            idx.line_for_id(step_id),
            f"'{step_id}' is never reachable: some prerequisite can never be satisfied",
        ))
    return findings


# action -> (state it puts its target in, the action that reverses it)
_STATE_ACTIONS = {
    "open": "close", "close": "open",
    "remove_from": "place_into", "place_into": "remove_from",
}


def check_state_already_reached(parsed: ParsedProtocol, idx: LineIndex) -> list[Finding]:
    """A step whose action a prerequisite already performed on the same
    target, with nothing in between reversing it: "open container" after
    the container was opened and never closed. It passes every structural
    check, but the engine waits for a state change that cannot happen,
    so the run ends with a spurious skip (a GUI-added placeholder step
    did exactly this to bas_specimen_v1). Conservative: only prerequisites
    count (steps that MUST come first), conditional steps are never the
    earlier one, and any reversing step between them clears it -- so
    repeated remove/return cycles stay valid."""
    ancestors: dict[str, set[str]] = {}

    def anc(step_id: str) -> set[str]:
        if step_id not in ancestors:
            ancestors[step_id] = set()  # cycle guard (cycles reported elsewhere)
            out: set[str] = set()
            for p in parsed.effective_after_leaf_ids(step_id):
                if p in parsed.nodes and not parsed.nodes[p].is_group:
                    out |= {p} | anc(p)
            ancestors[step_id] = out
        return ancestors[step_id]

    findings = []
    for step_id in parsed.order:
        node = parsed.nodes[step_id]
        undo = _STATE_ACTIONS.get(node.action or "")
        if node.is_group or undo is None:
            continue
        before = anc(step_id)
        for a in before:
            prev = parsed.nodes[a]
            if prev.action != node.action or prev.target != node.target or prev.condition:
                continue
            reversed_between = any(
                parsed.nodes[b].action == undo and parsed.nodes[b].target == node.target
                and a in anc(b)
                for b in before
            )
            if not reversed_between:
                findings.append(Finding(
                    idx.line_for_id(step_id),
                    f"'{step_id}' does '{node.action}' on '{node.target}', but prerequisite "
                    f"'{a}' already did and nothing in between reverses it -- this step can "
                    "never happen",
                ))
                break
    return findings


def validate(protocol_path: Path, defaults_path: Path,
             object_profile: str | Path | None = None) -> list[Finding]:
    # This is the live hot-reload path (CLAUDE.md: "protocols reloadable
    # at runtime without restart... a judge edits the JSON, we reload").
    # A bad comma or a typo'd path must produce a clean FAIL finding,
    # never a raw traceback on stage.
    try:
        raw_text = protocol_path.read_text(encoding="utf-8")
    except OSError as e:
        return [Finding(None, f"cannot read '{protocol_path}': {e}")]

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return [Finding(None, f"malformed JSON: {e.msg} (line {e.lineno}, column {e.colno})")]

    idx = LineIndex(raw_text)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defaults = load_yaml(defaults_path)

    findings: list[Finding] = []
    findings += check_schema(raw, schema)

    # If the schema itself is broken, the tree may not parse — stop here.
    if findings:
        return findings

    parsed = parse_protocol(raw)
    profile = None
    profile_ref = object_profile if object_profile is not None else raw.get("object_profile")
    if profile_ref:
        try:
            profile = load_yaml(REPO_ROOT / profile_ref)
        except FileNotFoundError:
            profile = None

    findings += check_after_references(parsed, idx)
    findings += check_cycles(parsed, idx)
    findings += check_targets_resolve(parsed, idx)
    findings += check_roles_bound_in_profile(parsed, idx, profile)
    findings += check_zones_rack_frame(raw, idx)
    findings += check_no_colour_or_shape_names(raw, idx)
    findings += check_constraints_have_basis(raw, idx)
    findings += check_disabled_non_overridable(raw, idx, defaults)
    findings += check_unenforced_fields(raw, idx, defaults)
    findings += check_reachable(parsed, idx, profile)
    findings += check_state_already_reached(parsed, idx)

    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("protocol", type=Path)
    ap.add_argument("--defaults", type=Path, default=REPO_ROOT / "configs" / "defaults.yaml")
    args = ap.parse_args()

    findings = validate(args.protocol, args.defaults)

    if not findings:
        print(f"OK: {args.protocol} is valid.")
    else:
        print(f"FAIL: {args.protocol} - {len(findings)} finding(s):")
        for f in findings:
            print(f)

    # CLAUDE.md: "The loader MUST print the resolved constraint set at
    # startup ... An author who has never opened defaults.yaml must
    # still be able to see what is being enforced." This script already
    # loads and resolves the same protocol to validate it, so it is the
    # natural single place for that printout to happen on every run, not
    # a separate untriggered code path. Only skipped if resolution
    # itself throws (typically because the findings above already
    # explain why the protocol can't even be parsed) -- the findings
    # are the actionable output in that case, not a traceback.
    try:
        resolved = resolve(args.protocol, args.defaults)
    except Exception as e:  # noqa: BLE001 - reported, not crashed on
        print(f"\n(resolved-constraint printout skipped: {e})")
    else:
        print()
        print_resolved_constraints(resolved)

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
