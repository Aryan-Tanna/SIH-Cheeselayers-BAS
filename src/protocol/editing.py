"""Protocol editing model behind the GUI's protocol editor -- pure data,
no Tk, so every edit path is unit-testable.

What an operator can change, and what they cannot, by design:

* STEPS: add / edit / delete / reorder steps and groups, built ONLY from
  the fixed primitive set (src/protocol/events.py Action) and the
  protocol's own roles and zones. A new kind of physical action needs
  code, not a GUI (addendum: the engine implements types, protocols
  select them).
* RULES: every default constraint from configs/defaults.yaml, with its
  on/off switch, timer, severity and spoken alert. Non-overridable rules
  are shown LOCKED (the loader would reject disabling them anyway).
  An edit is written as a protocol `constraints` entry carrying only the
  changed fields (+ id, + basis: the validator requires one), so the
  startup printout marks it [protocol] -- nothing changes invisibly.
* SAVE: always through the real validator (line-numbered findings); an
  invalid protocol is never written. Keys the editor does not know about
  (notes, variant examples, per-step extras like `success`) are kept.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from src.protocol.events import Action

ACTIONS: tuple[str, ...] = get_args(Action)
# Which extra field an action needs, as the engine matches it.
ACTION_FIELD = {"remove_from": "source", "place_into": "dest", "move_to_zone": "zone"}
STEP_KEYS = ("id", "action", "target", "source", "dest", "zone", "after", "prompt", "condition")
# Rule fields the editor exposes (others stay as in defaults.yaml).
TIMER_KEYS = ("timeout_s", "grace_s")
SEVERITIES = ("advisory", "caution", "warning")
# Prompt text a freshly added step starts with. The prompt is spoken to the
# operator, so a step still carrying it is unfinished: saving is refused.
PLACEHOLDER_PROMPT = "Describe the step to the operator."


@dataclass
class StepRow:
    """One line of the steps table: a step, or a group header."""

    kind: str  # "step" | "group"
    id: str
    group: str = ""  # parent group id ("" = top level); groups are top level only
    action: str = ""
    target: str = ""
    source: str = ""
    dest: str = ""
    zone: str = ""
    after: list[str] = field(default_factory=list)
    prompt: str = ""
    condition: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, kept on save

    @property
    def place(self) -> str:
        """The from / to / zone column, whichever this action uses."""
        key = ACTION_FIELD.get(self.action)
        return getattr(self, key) if key else ""


def load_raw(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flatten(raw: dict[str, Any]) -> list[StepRow]:
    rows: list[StepRow] = []

    def one(node: dict[str, Any], group: str) -> StepRow:
        known = set(STEP_KEYS) | {"type", "steps"}
        return StepRow(
            kind="step", id=node["id"], group=group, action=node.get("action", ""),
            target=node.get("target", ""), source=node.get("source", ""), dest=node.get("dest", ""),
            zone=node.get("zone", ""), after=list(node.get("after", []) or []),
            prompt=node.get("prompt", ""), condition=node.get("condition", ""),
            extra={k: v for k, v in node.items() if k not in known})

    for node in raw.get("steps", []):
        if node.get("type") == "group":
            rows.append(StepRow(kind="group", id=node["id"], after=list(node.get("after", []) or []),
                                extra={k: v for k, v in node.items() if k not in ("id", "type", "after", "steps")}))
            for child in node.get("steps", []):
                if child.get("type") == "group":
                    raise ValueError(f"nested group {child['id']!r} inside {node['id']!r}: "
                                     "the editor supports one group level -- edit this file by hand")
                rows.append(one(child, node["id"]))
        else:
            rows.append(one(node, ""))
    return rows


def _step_json(r: StepRow) -> dict[str, Any]:
    out: dict[str, Any] = {"id": r.id, "action": r.action, "target": r.target}
    key = ACTION_FIELD.get(r.action)
    if key and getattr(r, key):
        out[key] = getattr(r, key)
    if r.condition:
        out["condition"] = r.condition
    if r.after:
        out["after"] = list(r.after)
    if r.prompt:
        out["prompt"] = r.prompt
    for k, v in r.extra.items():
        out.setdefault(k, v)
    return out


def build(raw: dict[str, Any], rows: list[StepRow]) -> dict[str, Any]:
    """rows -> a new raw protocol (a copy; `raw` is untouched). Steps keep
    table order; each step sits in its group."""
    groups = {r.id: r for r in rows if r.kind == "group"}
    steps: list[dict[str, Any]] = []
    group_nodes: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.kind == "group":
            node = {"id": r.id, "type": "group", **({"after": list(r.after)} if r.after else {}),
                    **r.extra, "steps": []}
            group_nodes[r.id] = node
            steps.append(node)
        elif r.group:
            if r.group not in groups:
                raise ValueError(f"step {r.id!r} is in unknown group {r.group!r}")
            group_nodes[r.group]["steps"].append(_step_json(r))
        else:
            steps.append(_step_json(r))
    empty = [g for g, n in group_nodes.items() if not n["steps"]]
    if empty:
        raise ValueError(f"group(s) {empty} have no steps -- add a step or delete the group")
    out = copy.deepcopy(raw)
    out["steps"] = steps
    return out


def targets(raw: dict[str, Any], profile: dict[str, Any] | None) -> list[str]:
    """What a step may act on: every role, plus <role>.lid for roles whose
    lid is a separate detectable object (profile lid_class_id)."""
    roles = list((raw.get("roles") or {}).keys())
    prof_roles = (profile or {}).get("roles") or {}
    lids = [f"{r}.lid" for r in roles if (prof_roles.get(r) or {}).get("lid_class_id")]
    return roles + lids


# ----------------------------------------------------------------------
# Rules
# ----------------------------------------------------------------------

@dataclass
class RuleRow:
    id: str
    type: str
    locked: bool  # non-overridable: cannot be switched off
    enabled: bool
    severity: str
    alert: str
    timer_key: str | None  # "timeout_s" / "grace_s" when the rule has a timer
    timer: float | None
    basis: str
    origin: str  # "default" | "protocol"
    note: str = ""


def rule_rows(defaults: dict[str, Any], raw: dict[str, Any]) -> list[RuleRow]:
    from src.protocol.loader import resolve_constraints

    resolved, _ = resolve_constraints(defaults, raw)
    rows = []
    for c in resolved:
        p = c.params
        tk = next((k for k in TIMER_KEYS if k in p), None)
        rows.append(RuleRow(
            id=c.id, type=str(c.type or ""), locked=c.tier == "non_overridable", enabled=c.enabled,
            severity=str(p.get("severity", c.severity or "")), alert=str(p.get("alert", "")),
            timer_key=tk, timer=float(p[tk]) if tk else None, basis=str(p.get("basis", c.basis or "")),
            origin=c.origin, note=" ".join(str(p.get("note", "")).split())))
    return rows


def apply_rule_edit(raw: dict[str, Any], defaults: dict[str, Any], rule_id: str, *,
                    enabled: bool | None = None, severity: str | None = None,
                    alert: str | None = None, timer: float | None = None) -> dict[str, Any]:
    """Returns a new raw protocol with the edit as a `constraints` entry.
    Only fields that DIFFER from the default are written; an entry that
    ends up equal to the default is removed (back to [default])."""
    dc = (defaults.get("default_constraints") or {}).get(rule_id)
    if dc is None:
        raise ValueError(f"unknown rule {rule_id!r}")
    if dc.get("overridable") is False and enabled is False:
        raise ValueError(f"{rule_id!r} is a non-overridable safety rule and cannot be switched off")
    if severity is not None and severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    tk = next((k for k in TIMER_KEYS if k in dc), None)
    if timer is not None:
        if tk is None:
            raise ValueError(f"{rule_id!r} has no timer")
        if not timer > 0:
            raise ValueError("timer must be > 0 seconds")

    out = copy.deepcopy(raw)
    entries = [c for c in out.get("constraints", []) if c.get("id") != rule_id]
    old = next((c for c in raw.get("constraints", []) if c.get("id") == rule_id), {})
    entry = {k: v for k, v in old.items() if k not in ("id", "basis")}
    if enabled is not None:
        entry.pop("disabled", None)
        if not enabled:
            entry["disabled"] = True
    for key, val in (("severity", severity), ("alert", alert), (tk, timer)):
        if val is None or key is None:
            continue
        if val == dc.get(key):
            entry.pop(key, None)
        else:
            entry[key] = val
    # The strict_mode toggle for this rule would be outranked by an explicit
    # entry anyway (loader tier 3 > tier 4); fold it in so there is one source.
    from src.protocol.loader import _STRICT_MODE_TOGGLES

    toggle = next((k for k, v in _STRICT_MODE_TOGGLES.items() if v == rule_id), None)
    sm = dict(out.get("strict_mode") or {})
    if toggle and toggle in sm:
        if enabled is None and not sm[toggle]:
            entry.setdefault("disabled", True)
        sm.pop(toggle)
        out["strict_mode"] = sm
    if entry:
        entries.append({"id": rule_id, **entry, "basis": dc.get("basis", "operator_edit")})
    if entries:
        out["constraints"] = entries
    else:
        out.pop("constraints", None)
    return out


# ----------------------------------------------------------------------
# Save (validated)
# ----------------------------------------------------------------------

def validate_raw(raw: dict[str, Any], near: Path, defaults_path: Path,
                 object_profile: str | Path | None = None) -> list[str]:
    """The real validator on an unsaved protocol. `near` = where it would be
    saved (relative paths inside it resolve from there). Findings name
    `near`, not the scratch file."""
    from scripts.validate_protocol import validate

    try:
        unfinished = [r.id for r in flatten(raw) if r.kind == "step" and r.prompt.strip() == PLACEHOLDER_PROMPT]
    except (KeyError, ValueError):  # malformed / nested groups: the real validator reports it
        unfinished = []
    if unfinished:  # it validates structurally but would speak the placeholder aloud
        return [f"{Path(near).name}: step '{sid}' has no real prompt (still the placeholder)"
                for sid in unfinished]
    near = Path(near)
    tmp = near.with_name(near.stem + ".editing.json")
    tmp.write_text(json.dumps(raw, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        findings = [str(f) for f in validate(tmp, defaults_path, object_profile)]
    except Exception as exc:  # noqa: BLE001 -- JSON/schema crash = a finding
        findings = [f"validator error: {exc}"]
    finally:
        tmp.unlink(missing_ok=True)
    return [f.replace(tmp.name, near.name) for f in findings]


def save_validated(raw: dict[str, Any], path: Path, defaults_path: Path,
                   object_profile: str | Path | None = None) -> list[str]:
    """Validate, then write atomically. Returns the validator's findings
    (line-numbered); non-empty = NOT written."""
    path = Path(path)
    findings = validate_raw(raw, path, defaults_path, object_profile)
    if findings:
        return findings
    tmp = path.with_name(path.stem + ".saving.json")
    tmp.write_text(json.dumps(raw, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return []


def rename_step(rows: list[StepRow], old: str, new: str) -> None:
    """Rename a step or group and every `after` / group reference to it."""
    for r in rows:
        if r.id == old:
            r.id = new
        r.after = [new if a == old else a for a in r.after]
        if r.group == old:
            r.group = new
