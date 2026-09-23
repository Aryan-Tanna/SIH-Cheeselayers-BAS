#!/usr/bin/env python3
"""Replay harness: takes a clip's detection stream plus an (optional)
expected-event fixture, runs the pipeline headless — no camera, GUI,
audio, or sleep; faster than real time — and diffs actual events against
expected, reporting PASS/FAIL with the specific mismatch.

Works with --stub-detector before any clip or model exists. Two
detection-stream shapes are supported:

  "events" — already-discrete semantic actions (what CLAUDE.md calls
  "pre-computed detections"), fed to the engine directly, one per list
  entry:
    {
      "clip_id": "...",
      "protocol_id": "...",
      "events": [
        {"t": 1.0, "action": "open", "target": "container"},
        ...
      ]
    }

  "raw_observations" — noisy per-frame presence/absence observations
  for a given (action, target, ...) key, run through the SAME
  src.protocol.debounce.Debouncer the live pipeline uses (k/n from the
  resolved protocol's timing.step_debounce_frames / step_debounce_of_n),
  and only turned into an ActionEvent on a confirmed transition to
  present. This is what actually exercises the debouncer end-to-end
  through engine + alerts + logging, rather than only in its own unit
  tests:
    {
      "clip_id": "...",
      "protocol_id": "...",
      "raw_observations": [
        {"t": 1.00, "action": "open", "target": "container", "present": true},
        {"t": 1.03, "action": "open", "target": "container", "present": false},
        ...
      ]
    }

An "events" stream may also carry two non-action entry shapes:

    {"t": 5.0, "command": "pause"}        -- operator pause / resume
    {"t": 7.0, "anomaly": "foreign_object", "label": "pen"}
                                          -- something outside the experiment

A stream may use either key, not both. The engine, alerts, and logging
downstream of debouncing are identical either way — only what produces
the ActionEvent list differs.

Fixture format (harness/fixtures/*.json) — see CLAUDE.md for the full
spec: expected_events with tolerance_s, expected_alerts, partial.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.logging.session_log import SessionLogger, verify_chain  # noqa: E402
from src.protocol.alerts import AlertManager  # noqa: E402
from src.protocol.debounce import Debouncer  # noqa: E402
from src.protocol.engine import ProtocolEngine  # noqa: E402
from src.protocol.events import ActionEvent, AnomalyEvent, EngineEvent  # noqa: E402
from src.protocol.loader import ResolvedProtocol, resolve  # noqa: E402
from src.runtime.clock import VirtualClock  # noqa: E402

DEFAULT_PROTOCOL_ROOT = REPO_ROOT


@dataclass
class Mismatch:
    kind: str  # "missing" | "unexpected"
    detail: str


@dataclass
class ReplayResult:
    clip_id: str
    passed: bool | None  # None when run with no fixture (smoke mode)
    mismatches: list[Mismatch] = field(default_factory=list)
    expected_alerts: int | None = None
    actual_alerts: int = 0  # SPOKEN — passed the alert manager's suppression
    violations_logged: int = 0  # LOGGED — every violation, always, per "log completeness is unconditional"
    n_events_in: int = 0
    n_engine_events: int = 0
    n_anomalies: int = 0
    n_unmatched: int = 0
    missed_violations: int = 0
    false_alarms: int = 0
    wall_seconds: float = 0.0
    fps: float = 0.0
    mean_alert_processing_ms: float = 0.0
    actual_events: list[dict[str, Any]] = field(default_factory=list)


def _observation_key(obs: dict[str, Any]) -> str:
    return "|".join(str(obs.get(f)) for f in ("action", "target", "source", "dest", "zone"))


def debounce_raw_observations(
    raw_observations: list[dict[str, Any]], resolved: ResolvedProtocol
) -> list[dict[str, Any]]:
    """Runs noisy per-frame observations through the same k-of-n
    Debouncer the live pipeline would use, in chronological order across
    all keys (each key keeps its own independent window — see
    src/protocol/debounce.py), and returns one synthesized `events`-shape
    entry per CONFIRMED transition to present. A single flickered frame
    that never reaches k-of-n agreement produces no event at all.
    """
    k = resolved.timing["step_debounce_frames"]
    n = resolved.timing["step_debounce_of_n"]
    debouncer = Debouncer(k=k, n=n)

    confirmed_events: list[dict[str, Any]] = []
    for obs in sorted(raw_observations, key=lambda o: o["t"]):
        key = _observation_key(obs)
        state, transitioned = debouncer.update(key, bool(obs["present"]))
        if transitioned and state:
            confirmed_events.append({
                "t": obs["t"],
                "action": obs["action"],
                "target": obs["target"],
                "source": obs.get("source"),
                "dest": obs.get("dest"),
                "zone": obs.get("zone"),
                "confidence": obs.get("confidence", 1.0),
            })
    return confirmed_events


def _to_actual_shape(e: EngineEvent) -> dict[str, Any] | None:
    if e.event_type == "step_complete":
        return {"t": e.ts_monotonic, "type": "step_complete", "step": e.step_id}
    if e.event_type == "violation":
        return {
            "t": e.ts_monotonic,
            "type": "violation",
            "code": e.violation_type,
            "target": e.target,
            "root_cause_id": e.root_cause_id,
        }
    if e.event_type == "anomaly":
        return {
            "t": e.ts_monotonic,
            "type": "anomaly",
            "code": e.extra.get("kind"),
            "target": e.target,
        }
    if e.event_type in ("session_paused", "session_resumed"):
        return {"t": e.ts_monotonic, "type": e.event_type}
    return None


def _matches_expected(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if actual["type"] != expected["type"]:
        return False
    tol = expected.get("tolerance_s", 0.0)
    if abs(actual["t"] - expected["t"]) > tol:
        return False
    if expected["type"] == "step_complete":
        return actual["step"] == expected["step"]
    if expected["type"] in ("session_paused", "session_resumed"):
        return True
    if expected["type"] in ("violation", "anomaly"):
        if actual["code"] != expected["code"]:
            return False
        if "target" in expected and actual["target"] != expected["target"]:
            return False
        return True
    return False


def run_replay(
    detection_stream: dict[str, Any],
    fixture: dict[str, Any] | None,
    protocol_path: Path | None = None,
    defaults_path: Path | None = None,
    log_path: Path | None = None,
    operator: str | None = None,
) -> ReplayResult:
    clip_id = detection_stream.get("clip_id", "unknown_clip")
    protocol_id = detection_stream["protocol_id"]
    ppath = protocol_path or (DEFAULT_PROTOCOL_ROOT / "configs" / "protocols" / f"{protocol_id}.json")
    dpath = defaults_path or (DEFAULT_PROTOCOL_ROOT / "configs" / "defaults.yaml")

    resolved = resolve(ppath, dpath)
    clock = VirtualClock()
    engine = ProtocolEngine(resolved, clock=clock, operator=operator)
    alert_manager = AlertManager.from_policy(resolved.alert_policy, clock=clock)

    logger = SessionLogger(log_path, session_id=clip_id) if log_path else None

    if "raw_observations" in detection_stream:
        events_source = debounce_raw_observations(detection_stream["raw_observations"], resolved)
        n_observations_in = len(detection_stream["raw_observations"])
    else:
        events_source = detection_stream["events"]
        n_observations_in = len(events_source)

    raw_events = sorted(events_source, key=lambda e: e["t"])
    result = ReplayResult(clip_id=clip_id, passed=None, expected_alerts=(fixture or {}).get("expected_alerts"))
    result.n_events_in = n_observations_in

    wall_start = time.perf_counter()
    seen_out_idx = 0
    alert_latencies: list[float] = []

    def drain() -> None:
        nonlocal seen_out_idx
        for e in engine.out[seen_out_idx:]:
            if logger:
                logger.log_event(e)
            if e.event_type in ("violation", "anomaly"):
                if e.event_type == "violation":
                    result.violations_logged += 1
                t0 = time.perf_counter()
                decision = alert_manager.decide(e.severity or "advisory", e.root_cause_id or "")
                alert_latencies.append(time.perf_counter() - t0)
                if decision.speak:
                    result.actual_alerts += 1
            if e.event_type == "engine_anomaly":
                result.n_anomalies += 1
            if e.event_type == "unmatched_action":
                result.n_unmatched += 1
        seen_out_idx = len(engine.out)

    try:
        for raw in raw_events:
            clock.advance_to(raw["t"])
            if "command" in raw:
                if raw["command"] == "pause":
                    engine.pause_session(raw["t"])
                elif raw["command"] == "resume":
                    engine.resume_session(raw["t"])
                else:
                    raise ValueError(f"replay supports pause/resume commands, got {raw['command']!r}")
                drain()
                continue
            if "anomaly" in raw:
                engine.process(AnomalyEvent(ts=raw["t"], kind=raw["anomaly"], label=raw.get("label")))
                drain()
                continue
            action_event = ActionEvent(
                ts=raw["t"],
                action=raw["action"],
                target=raw["target"],
                source=raw.get("source"),
                dest=raw.get("dest"),
                zone=raw.get("zone"),
                confidence=raw.get("confidence", 1.0),
            )
            engine.process(action_event)
            drain()

        # A clip can end with a lid still detached and no further event
        # to trigger check_timeouts as a side effect of processing an
        # action — without this, a pending lid_unstowed timeout never
        # fires just because nothing else happened before the clip ended.
        # clip_duration_s is optional: it lets a detection stream declare
        # idle tail time after its last action (the real per-frame
        # pipeline gets this for free from continuous frame ticks; a
        # discrete-event stub-detector stream does not, unless told).
        clip_duration = detection_stream.get("clip_duration_s")
        if clip_duration is not None and clip_duration > clock.now():
            clock.advance_to(clip_duration)
        engine.check_timeouts(clock.now())
        drain()
    finally:
        if logger:
            logger.close()

    result.wall_seconds = time.perf_counter() - wall_start
    result.n_engine_events = len(engine.out)
    result.fps = result.n_events_in / result.wall_seconds if result.wall_seconds > 0 else float("inf")
    result.mean_alert_processing_ms = (
        1000 * sum(alert_latencies) / len(alert_latencies) if alert_latencies else 0.0
    )
    result.actual_events = [
        s for s in (_to_actual_shape(e) for e in engine.out) if s is not None
    ]

    if fixture is not None:
        result.passed = True
        expected_events = fixture.get("expected_events", [])
        # Multiset matching: each actual event can satisfy at most one
        # expected entry. Without this, N identical expected entries
        # (e.g. the cascade fixture's repeated {skip, module_b}) would
        # all be "found" by the SAME single actual event, silently
        # asserting nothing about how many actually occurred.
        consumed = [False] * len(result.actual_events)
        for exp in expected_events:
            match_idx = next(
                (i for i, act in enumerate(result.actual_events)
                 if not consumed[i] and _matches_expected(act, exp)),
                None,
            )
            if match_idx is None:
                result.mismatches.append(Mismatch(
                    "missing",
                    f"expected {exp['type']} at t={exp['t']} "
                    f"({exp.get('code') or exp.get('step')}) not found in actual events",
                ))
                result.passed = False
                if exp["type"] == "violation":
                    result.missed_violations += 1
            else:
                consumed[match_idx] = True

        if not fixture.get("partial", False):
            for act, was_consumed in zip(result.actual_events, consumed):
                if not was_consumed:
                    result.mismatches.append(Mismatch(
                        "unexpected",
                        f"actual {act['type']} at t={act['t']} "
                        f"({act.get('code') or act.get('step')}) not in expected_events",
                    ))
                    result.passed = False
                    if act["type"] == "violation":
                        result.false_alarms += 1

        if result.expected_alerts is not None and result.actual_alerts != result.expected_alerts:
            result.mismatches.append(Mismatch(
                "unexpected",
                f"expected_alerts={result.expected_alerts}, actual alerts spoken={result.actual_alerts}",
            ))
            result.passed = False

    if log_path is not None:
        verify = verify_chain(log_path)
        if not verify.ok:
            result.mismatches.append(Mismatch("unexpected", f"log hash chain broken: {verify.reason}"))
            result.passed = False

    return result


def format_result(result: ReplayResult) -> str:
    lines = []
    status = "SMOKE" if result.passed is None else ("PASS" if result.passed else "FAIL")
    lines.append(
        f"[{status}] {result.clip_id}  events_in={result.n_events_in} "
        f"violations_logged={result.violations_logged}  alerts_spoken={result.actual_alerts}"
        + (f"/{result.expected_alerts}" if result.expected_alerts is not None else "")
        + f"  fps={result.fps:.0f}  anomalies={result.n_anomalies} unmatched={result.n_unmatched}"
    )
    for m in result.mismatches:
        lines.append(f"    - {m.kind}: {m.detail}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub-detector", type=Path, required=True, help="detection stream JSON")
    ap.add_argument("--fixture", type=Path, default=None, help="expected-events fixture JSON")
    ap.add_argument(
        "--no-fixture", action="store_true",
        help="force smoke mode (alert count / FPS / error rate only, no PASS/FAIL), "
             "even if --fixture is also given",
    )
    ap.add_argument("--protocol", type=Path, default=None)
    ap.add_argument("--defaults", type=Path, default=None)
    ap.add_argument("--log", type=Path, default=None)
    args = ap.parse_args()

    detection_stream = json.loads(args.stub_detector.read_text(encoding="utf-8"))
    fixture = (
        None if args.no_fixture
        else json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture
        else None
    )

    result = run_replay(
        detection_stream,
        fixture,
        protocol_path=args.protocol,
        defaults_path=args.defaults,
        log_path=args.log,
    )
    print(format_result(result))
    return 0 if (result.passed is not False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
