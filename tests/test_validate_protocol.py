"""validate_protocol.py regression: this is the live hot-reload path
(CLAUDE.md: "protocols reloadable at runtime without restart... a judge
edits the JSON, we reload"), so a bad comma or a typo'd path must
produce a clean FAIL finding, never a raw traceback -- the original
implementation let json.JSONDecodeError and OSError propagate straight
out of validate()."""

from pathlib import Path

from scripts.validate_protocol import validate

DEFAULTS_PATH = Path("configs/defaults.yaml")


def test_malformed_json_is_a_clean_finding_not_a_crash(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json{{{", encoding="utf-8")

    findings = validate(bad, DEFAULTS_PATH)

    assert len(findings) == 1
    assert "malformed JSON" in findings[0].message


def test_missing_file_is_a_clean_finding_not_a_crash(tmp_path):
    missing = tmp_path / "does_not_exist.json"

    findings = validate(missing, DEFAULTS_PATH)

    assert len(findings) == 1
    assert "cannot read" in findings[0].message


def test_valid_protocol_still_passes():
    findings = validate(Path("configs/protocols/bas_specimen_v1.json"), DEFAULTS_PATH)
    assert findings == []
