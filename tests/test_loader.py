from pathlib import Path

from src.protocol.loader import EXPECTED_NON_OVERRIDABLE_IDS, format_resolved_report, resolve

PROTOCOL = Path("configs/protocols/bas_specimen_v1.json")
DEFAULTS = Path("configs/defaults.yaml")


def test_resolve_loads_bas_specimen_v1():
    r = resolve(PROTOCOL, DEFAULTS)
    assert r.parsed.protocol_id == "bas_specimen_v1"
    assert set(r.parsed.roles) == {"container", "module_a", "module_b"}


def test_all_nine_default_constraints_present_and_unmodified_by_silent_protocol():
    r = resolve(PROTOCOL, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert set(by_id) == {
        "one_module_at_a_time",
        "no_loose_objects",
        "sealed_before_return",
        "container_empty_before_close",
        "lid_stow_required",
        "correct_insertion_orientation",
        "out_of_order",
        "skip",
        "wrong_object",
    }
    # bas_specimen_v1 declares no constraints/strict_mode of its own —
    # every entry must be [default], not [protocol].
    assert all(c.origin == "default" for c in r.constraints)


def test_engine_native_sequence_constraints_are_enabled_by_default():
    r = resolve(PROTOCOL, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert by_id["out_of_order"].enabled is True
    assert by_id["skip"].enabled is True
    assert by_id["wrong_object"].enabled is True
    assert by_id["out_of_order"].severity == "caution"
    assert by_id["skip"].severity == "warning"
    assert by_id["wrong_object"].severity == "caution"


def test_non_overridable_tier_matches_defaults_yaml_overridable_false():
    r = resolve(PROTOCOL, DEFAULTS)
    non_overridable = {c.id for c in r.constraints if c.tier == "non_overridable"}
    assert non_overridable == set(EXPECTED_NON_OVERRIDABLE_IDS)


def test_correct_insertion_orientation_disabled_by_default():
    r = resolve(PROTOCOL, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert by_id["correct_insertion_orientation"].enabled is False


def test_protocol_constraint_overrides_default_by_id(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["constraints"] = [{"id": "sealed_before_return", "disabled": True, "basis": "contamination_control"}]
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    r = resolve(p, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert by_id["sealed_before_return"].origin == "protocol"
    assert by_id["sealed_before_return"].enabled is False


def test_disabling_non_overridable_default_is_rejected_with_warning(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["constraints"] = [{"id": "no_loose_objects", "disabled": True, "basis": "microgravity_hazard"}]
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    r = resolve(p, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert by_id["no_loose_objects"].enabled is True
    assert any("no_loose_objects" in w for w in r.warnings)


def test_strict_mode_toggle_enables_orientation_check(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["strict_mode"] = {"require_orientation": True}
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    r = resolve(p, DEFAULTS)
    by_id = {c.id: c for c in r.constraints}
    assert by_id["correct_insertion_orientation"].enabled is True


def test_force_module_order_injects_after_edge(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["strict_mode"] = {"force_module_order": "handle_a"}
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    r = resolve(p, DEFAULTS)
    assert "handle_a" in r.parsed.nodes["handle_b"].after


def test_effective_after_propagates_group_after_to_children():
    r = resolve(PROTOCOL, DEFAULTS)
    eff = r.parsed.effective_after_leaf_ids("remove_a")
    assert "open_container" in eff


def test_resolved_report_marks_default_and_protocol_origin():
    r = resolve(PROTOCOL, DEFAULTS)
    report = format_resolved_report(r)
    assert "[default]" in report
    assert "one_module_at_a_time" in report
    assert "a lid cannot be stowed before it is detached" in report
    # The third hard-ordering item was miscategorised and removed — a
    # container closing over an outside module is policy, not physics.
    assert "a container cannot be closed while a module is outside it" not in report


def test_module_order_is_free_for_bas_specimen_v1():
    r = resolve(PROTOCOL, DEFAULTS)
    assert r.module_order.startswith("free")
    assert "Ordering: free" in format_resolved_report(r)


def test_module_order_reports_strict_when_forced(tmp_path):
    import json

    raw = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    raw["strict_mode"] = {"force_module_order": "handle_a"}
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    r = resolve(p, DEFAULTS)
    assert r.module_order.startswith("strict")
    assert "handle_a" in r.module_order
