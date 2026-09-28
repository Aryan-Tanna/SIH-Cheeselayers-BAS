from pathlib import Path

from scripts.validate_protocol import validate

VALID = Path("configs/protocols/bas_specimen_v1.json")
DEFAULTS = Path("configs/defaults.yaml")
MALFORMED_DIR = Path("tests/fixtures/malformed")


def test_reference_protocol_is_valid():
    findings = validate(VALID, DEFAULTS)
    assert findings == []


def test_cyclic_after_detected():
    findings = validate(MALFORMED_DIR / "cyclic_after.json", DEFAULTS)
    assert any("cycle" in f.message for f in findings)


def test_dangling_after_detected():
    findings = validate(MALFORMED_DIR / "dangling_after.json", DEFAULTS)
    assert any("undefined id" in f.message for f in findings)


def test_unbound_role_detected():
    findings = validate(MALFORMED_DIR / "unbound_role.json", DEFAULTS)
    assert any("not bound in object profile" in f.message for f in findings)


def test_image_frame_zone_detected():
    findings = validate(MALFORMED_DIR / "image_frame_zone.json", DEFAULTS)
    assert any("frame: image" in f.message for f in findings)


def test_colour_name_detected():
    findings = validate(MALFORMED_DIR / "colour_name.json", DEFAULTS)
    assert any("colour/shape" in f.message for f in findings)


def test_disabled_non_overridable_detected():
    findings = validate(MALFORMED_DIR / "disabled_non_overridable.json", DEFAULTS)
    assert any("non-overridable" in f.message for f in findings)


def test_missing_basis_detected():
    findings = validate(MALFORMED_DIR / "missing_basis.json", DEFAULTS)
    assert any("no basis field" in f.message for f in findings)


def test_findings_carry_line_numbers():
    findings = validate(MALFORMED_DIR / "cyclic_after.json", DEFAULTS)
    assert any(f.line is not None for f in findings)


def test_step_repeating_a_state_already_reached_detected():
    findings = validate(MALFORMED_DIR / "state_already_reached.json", DEFAULTS)
    hits = [f for f in findings if "reopen_container" in f.message and "open_container" in f.message]
    assert hits and hits[0].line is not None


def test_repeated_action_after_a_reversal_is_valid(tmp_path):
    """open -> close -> open again is a real protocol shape, not a finding."""
    import json

    raw = json.loads(VALID.read_text(encoding="utf-8"))
    raw["steps"] += [
        {"id": "reopen_container", "action": "open", "target": "container",
         "after": ["close_container"], "prompt": "Open the payload container again."},
    ]
    p = tmp_path / "reopen.json"
    p.write_text(json.dumps(raw, indent=4), encoding="utf-8")
    assert [f for f in validate(p, DEFAULTS) if "never happen" in f.message] == []


def test_repeated_remove_return_cycles_stay_valid():
    assert validate(Path("configs/protocols/repeatable_action_test.json"), DEFAULTS) == []
