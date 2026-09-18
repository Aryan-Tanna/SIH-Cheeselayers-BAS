#!/usr/bin/env python3
"""Run every fixture in harness/fixtures/ against its matching detection
stream in harness/synthetic/, and print the headline metrics table.

This is our headline metric — it measures the SYSTEM (engine + alert
policy + logging), not the detector, which is exactly right for phase 0
where there is no detector yet.

Clips with a detection stream but no fixture run in --no-fixture smoke
mode: alert count / FPS / error rate only, no PASS/FAIL. Phase 0 has no
such clips (every synthetic stream has a matching fixture), but this
keeps run_all.py correct once phase 1 adds unfixtured clips to the
corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.replay import ReplayResult, run_replay  # noqa: E402

SYNTHETIC_DIR = REPO_ROOT / "harness" / "synthetic"
FIXTURES_DIR = REPO_ROOT / "harness" / "fixtures"


def discover() -> list[tuple[str, Path, Path | None]]:
    pairs = []
    for stream_path in sorted(SYNTHETIC_DIR.glob("*.json")):
        clip_id = stream_path.stem
        fixture_path = FIXTURES_DIR / f"{clip_id}.json"
        pairs.append((clip_id, stream_path, fixture_path if fixture_path.exists() else None))
    return pairs


def run_all() -> list[ReplayResult]:
    results = []
    for clip_id, stream_path, fixture_path in discover():
        detection_stream = json.loads(stream_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8")) if fixture_path else None
        results.append(run_replay(detection_stream, fixture))
    return results


def print_report(results: list[ReplayResult]) -> bool:
    fixtured = [r for r in results if r.passed is not None]
    smoke = [r for r in results if r.passed is None]

    n_pass = sum(1 for r in fixtured if r.passed)
    n_fail = sum(1 for r in fixtured if not r.passed)
    total_false_alarms = sum(r.false_alarms for r in fixtured)
    total_missed = sum(r.missed_violations for r in fixtured)
    total_expected_alerts = sum(r.expected_alerts or 0 for r in fixtured)
    total_actual_alerts = sum(r.actual_alerts for r in fixtured)
    total_violations_logged = sum(r.violations_logged for r in results)
    total_suppressed = total_violations_logged - sum(r.actual_alerts for r in results)
    mean_fps = sum(r.fps for r in results) / len(results) if results else 0.0
    mean_alert_ms = (
        sum(r.mean_alert_processing_ms for r in fixtured) / len(fixtured) if fixtured else 0.0
    )

    print("=" * 78)
    print("harness/run_all.py - synthetic fixture corpus")
    print("=" * 78)
    for r in results:
        from harness.replay import format_result
        print(format_result(r))
    print("-" * 78)
    print(f"sequences correct   : {n_pass}/{len(fixtured)}")
    print(f"sequences failed    : {n_fail}/{len(fixtured)}")
    print(f"false alarms        : {total_false_alarms}")
    print(f"missed violations   : {total_missed}")
    print(f"alerts fired/expected: {total_actual_alerts}/{total_expected_alerts}")
    print(
        f"violations logged vs alerts spoken: {total_violations_logged} logged, "
        f"{total_actual_alerts} spoken, {total_suppressed} suppressed by alert policy "
        f"(cooldown/rate-cap - log completeness and alert restraint are separate concerns)"
    )
    print(f"mean alert decision latency: {mean_alert_ms:.3f} ms (in-process, not glass-to-alert)")
    print(f"mean events/sec (replay, not real-time): {mean_fps:.0f}")
    if smoke:
        print(f"smoke-only clips (no fixture): {len(smoke)}")
    print("=" * 78)

    return n_fail == 0


def main() -> int:
    results = run_all()
    if not results:
        print("No synthetic clips found under harness/synthetic/.")
        return 1
    ok = print_report(results)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
