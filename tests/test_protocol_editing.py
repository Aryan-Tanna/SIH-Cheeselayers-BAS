"""Protocol editor model: steps + rules, always saved through the validator."""

import json
from pathlib import Path

import pytest
import yaml

from src.protocol.editing import (
    ACTIONS, StepRow, apply_rule_edit, build, flatten, load_raw, rule_rows, save_validated, targets,
)
from src.protocol.loader import resolve

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"
PROFILE = REPO / "configs" / "objects" / "profile_jar.yaml"


def _defaults():
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


def test_roundtrip_reference_protocol_is_lossless():
    raw = load_raw(PROTOCOL)
    assert build(raw, flatten(raw)) == raw


def test_actions_are_the_fixed_primitive_set():
    assert {"open", "close", "remove_from", "place_into", "move_to_zone"} <= set(ACTIONS)


def test_targets_offer_lids_only_for_detectable_lids():
    raw = load_raw(PROTOCOL)
    t = targets(raw, yaml.safe_load(PROFILE.read_text(encoding="utf-8")))
    assert "module_a.lid" in t and "module_b.lid" in t and "container.lid" not in t


def test_write_a_new_experiment_and_it_resolves(tmp_path):
    """A shorter experiment: only module B, lid never opened."""
    raw = load_raw(PROTOCOL)
    raw["protocol_id"], raw["title"] = "quick_check_b", "Quick check of module B"
    rows = [
        StepRow("step", "open_container", action="open", target="container", prompt="Open the payload container."),
        StepRow("step", "take_b", action="remove_from", target="module_b", source="container",
                after=["open_container"], prompt="Take out the second module."),
        StepRow("step", "put_b", action="place_into", target="module_b", dest="container",
                after=["take_b"], prompt="Put it back."),
        StepRow("step", "close_container", action="close", target="container", after=["put_b"],
                prompt="Close the container."),
    ]
    out = tmp_path / "quick_check_b.json"
    findings = save_validated(build(raw, rows), out, DEFAULTS, PROFILE)
    assert findings == []
    r = resolve(out, DEFAULTS, PROFILE)
    assert list(r.parsed.order) == ["open_container", "take_b", "put_b", "close_container"]


def test_invalid_edit_is_rejected_with_line_numbers_and_not_written(tmp_path):
    raw = load_raw(PROTOCOL)
    rows = flatten(raw)
    rows[0].after = ["no_such_step"]          # dangling after
    rows[5].id = "stow_red_lid"                # colour name in a step id (validator scans ids/targets)
    rows[6].after = ["stow_red_lid"]
    out = tmp_path / "bad.json"
    findings = save_validated(build(raw, rows), out, DEFAULTS, PROFILE)
    assert not out.exists()
    text = "\n".join(findings)
    assert "no_such_step" in text and "red" in text.lower()
    assert any("line" in f.lower() or ":" in f for f in findings)


def test_group_structure_kept_and_empty_group_refused():
    raw = load_raw(PROTOCOL)
    rows = flatten(raw)
    assert [r.id for r in rows if r.kind == "group"] == ["handle_a", "handle_b"]
    no_children = [r for r in rows if not (r.kind == "step" and r.group == "handle_b")]
    with pytest.raises(ValueError, match="no steps"):
        build(raw, no_children)


def test_rule_timer_edit_becomes_a_protocol_entry():
    d = _defaults()
    raw = apply_rule_edit(load_raw(PROTOCOL), d, "attended_while_open", timer=8.0, alert="Stay with the open module.")
    entry = next(c for c in raw["constraints"] if c["id"] == "attended_while_open")
    assert entry["grace_s"] == 8.0 and entry["basis"] and "severity" not in entry  # only changed fields
    row = next(r for r in rule_rows(d, raw) if r.id == "attended_while_open")
    assert row.timer == 8.0 and row.origin == "protocol" and row.alert == "Stay with the open module."
    # setting it back to the default value removes the entry again
    back = apply_rule_edit(raw, d, "attended_while_open", timer=5.0, alert=d["default_constraints"]["attended_while_open"]["alert"])
    assert "constraints" not in back


def test_locked_rule_cannot_be_switched_off():
    d = _defaults()
    rows = {r.id: r for r in rule_rows(d, load_raw(PROTOCOL))}
    assert rows["no_loose_objects"].locked and rows["container_empty_before_close"].locked
    with pytest.raises(ValueError, match="non-overridable"):
        apply_rule_edit(load_raw(PROTOCOL), d, "no_loose_objects", enabled=False)


def test_switch_off_rule_saves_and_engine_sees_it(tmp_path):
    d = _defaults()
    raw = apply_rule_edit(load_raw(PROTOCOL), d, "one_module_at_a_time", enabled=False)
    out = tmp_path / "p.json"
    assert save_validated(raw, out, DEFAULTS, PROFILE) == []
    c = {c.id: c for c in resolve(out, DEFAULTS, PROFILE).constraints}["one_module_at_a_time"]
    assert c.enabled is False and c.origin == "protocol"


def test_strict_mode_toggle_folds_into_the_explicit_entry():
    d = _defaults()
    raw = load_raw(PROTOCOL)
    raw["strict_mode"] = {"require_lid_stow": False}
    out = apply_rule_edit(raw, d, "lid_stow_required", timer=20.0)
    assert "require_lid_stow" not in out["strict_mode"]
    e = next(c for c in out["constraints"] if c["id"] == "lid_stow_required")
    assert e["disabled"] is True and e["timeout_s"] == 20.0
