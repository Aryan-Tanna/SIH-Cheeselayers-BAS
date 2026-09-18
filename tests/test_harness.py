"""Runs the required synthetic fixture set through the replay harness as
part of the normal pytest suite (harness/run_all.py is the human-facing
summary; this is the CI gate)."""

import json
from pathlib import Path

import pytest

from harness.replay import run_replay

SYNTHETIC_DIR = Path("harness/synthetic")
FIXTURES_DIR = Path("harness/fixtures")

REQUIRED_SCENARIOS = {
    "clean_run",
    "skipped_step",
    "wrong_object",
    "out_of_order",
    "mutual_exclusion_breach",
    "cascade",
}


def test_all_required_synthetic_scenarios_exist():
    found = {p.stem for p in SYNTHETIC_DIR.glob("*.json")}
    assert REQUIRED_SCENARIOS <= found


@pytest.mark.parametrize("clip_id", sorted(REQUIRED_SCENARIOS))
def test_synthetic_fixture_passes(clip_id):
    stream = json.loads((SYNTHETIC_DIR / f"{clip_id}.json").read_text(encoding="utf-8"))
    fixture = json.loads((FIXTURES_DIR / f"{clip_id}.json").read_text(encoding="utf-8"))
    result = run_replay(stream, fixture)
    assert result.passed, result.mismatches


def test_root_cause_cooldown_suppresses_repeated_breach_from_same_root():
    """bas_specimen_v1 cannot exercise root_cause_cooldown_s at all — its
    remove_from steps each fire once, so mutual_exclusion_breach's
    constant root_cause_id ('one_module_at_a_time') never repeats.
    configs/protocols/repeatable_action_test.json (4 modules) can."""
    stream = json.loads((SYNTHETIC_DIR / "root_cause_cooldown.json").read_text(encoding="utf-8"))
    fixture = json.loads((FIXTURES_DIR / "root_cause_cooldown.json").read_text(encoding="utf-8"))
    result = run_replay(stream, fixture)
    assert result.passed, result.mismatches
    assert result.violations_logged == 3
    assert result.actual_alerts == 2


def test_debounce_raw_observations_confirms_flicker_and_rejects_noise():
    """The only fixture that runs raw per-frame observations through
    src.protocol.debounce.Debouncer end-to-end (harness/replay.py's
    "raw_observations" stream shape), rather than only in debounce's own
    unit tests. One key flickers (false, true, false, true...) but still
    reaches 5-of-8 true and confirms exactly once; a second key
    alternates true/false forever and never reaches 5-of-8 for either
    state, so it never reaches the engine at all."""
    stream = json.loads((SYNTHETIC_DIR / "debounce_raw_observations.json").read_text(encoding="utf-8"))
    fixture = json.loads((FIXTURES_DIR / "debounce_raw_observations.json").read_text(encoding="utf-8"))
    result = run_replay(stream, fixture)
    assert result.passed, result.mismatches
    assert result.n_events_in == 23
    assert result.violations_logged == 0
    assert result.actual_alerts == 0
    assert result.n_anomalies == 0
    assert result.n_unmatched == 0
    assert len(result.actual_events) == 1
    assert result.actual_events[0] == {"t": 1.3, "type": "step_complete", "step": "open_container"}


def test_debounce_raw_observations_down_transition_is_not_sticky():
    """A sticky-true debouncer -- one that confirms present but never
    releases -- would silently block every future re-confirmation of the
    same action, which is worse than one missed confirmation because
    nothing about it looks broken from the outside. harness/replay.py's
    "raw_observations" shape only synthesizes an ActionEvent on a
    confirmed transition TO present (see debounce_raw_observations()),
    so a genuine down-transition produces no event to assert on there --
    it has to be checked directly against the same Debouncer the harness
    uses, replaying the identical open/container observations."""
    from src.protocol.debounce import Debouncer
    from src.protocol.loader import resolve

    stream = json.loads((SYNTHETIC_DIR / "debounce_raw_observations.json").read_text(encoding="utf-8"))
    resolved = resolve(
        Path("configs/protocols/bas_specimen_v1.json"), Path("configs/defaults.yaml")
    )
    k = resolved.timing["step_debounce_frames"]
    n = resolved.timing["step_debounce_of_n"]
    debouncer = Debouncer(k=k, n=n)

    key = "open|container|None|None|None"
    transitions = []
    for obs in stream["raw_observations"]:
        if obs["action"] != "open" or obs["target"] != "container":
            continue
        state, transitioned = debouncer.update(key, obs["present"])
        if transitioned:
            transitions.append((obs["t"], state))

    assert transitions == [(1.30, True), (1.60, False)]
    assert debouncer.state(key) is False


def test_cascade_separates_violations_logged_from_alerts_spoken():
    """Counts matching (9/9 in the old run_all.py summary) proved nothing
    about whether suppression actually collapsed anything -- this checks
    the two numbers separately. Six violations fire from module_b never
    being touched; the 4/minute rate cap (not root_cause_cooldown_s,
    since each has a distinct root_cause_id) lets only 4 speak."""
    stream = json.loads((SYNTHETIC_DIR / "cascade.json").read_text(encoding="utf-8"))
    fixture = json.loads((FIXTURES_DIR / "cascade.json").read_text(encoding="utf-8"))
    result = run_replay(stream, fixture)
    assert result.violations_logged == 6
    assert result.actual_alerts == 4
