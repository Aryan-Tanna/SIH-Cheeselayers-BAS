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
