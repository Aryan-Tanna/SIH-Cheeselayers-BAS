#!/usr/bin/env python3
"""Hear the co-pilot: play a synthetic detection stream through the real
session (engine -> announcer -> audio worker), paced in (scaled) real
time, optionally with live "Hey BAS" voice control from the microphone.

This is the audio stage's end-to-end check before any video exists. It
is NOT the harness: harness/replay.py stays headless and faster than
real time; this sleeps on purpose so you can listen to interruptions,
suppression and prompt pacing as an operator would.

    python scripts/audio_demo.py harness/synthetic/cascade.json
    python scripts/audio_demo.py --all --speed 3
    python scripts/audio_demo.py --all --silent        # no device, no sleep
    python scripts/audio_demo.py harness/synthetic/clean_run.json --speed 0.3 --listen
        # say "Hey BAS, pause" / "Hey BAS, resume" / "Hey BAS, quiet mode"
    python scripts/audio_demo.py harness/synthetic/clean_run.json --mode quiet

Stream entries may also be {"t": .., "command": "pause"|"resume"|"quiet"|
"voice"|"repeat"} or {"t": .., "anomaly": "foreign_object", "label": ..}.
With --listen, a voice "pause" also holds the scripted operator until
you say "Hey BAS, resume".

Prints what was spoken per stream and a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.protocol.events import ActionEvent, AnomalyEvent  # noqa: E402
from src.protocol.loader import resolve  # noqa: E402
from src.runtime.announcer import AnnouncerSettings, AudioRequest, speakable_phrases  # noqa: E402
from src.runtime.audio_out import RecordingSink  # noqa: E402
from src.runtime.clock import VirtualClock  # noqa: E402
from src.runtime.config import build_audio_stage, load_runtime_config  # noqa: E402
from src.runtime.session import Session  # noqa: E402
from src.runtime.voice_control import build_listener  # noqa: E402

SYNTHETIC_DIR = REPO_ROOT / "harness" / "synthetic"


def _describe(r: AudioRequest) -> str:
    what = r.text if r.text else f"({r.earcon or 'silent'} tone)"
    sev = f" {r.severity}" if r.severity else ""
    flag = " INTERRUPT" if r.interrupt else (" FLUSH" if r.flush_all else "")
    return f"{r.kind}{sev}{flag}: {what}"


class StreamPlayer:
    """Drives one stream into a Session.

    The session clock always runs (so a pause has a real duration in the
    log). Stream time -- when the scripted operator acts next -- stops
    while the session is paused BY VOICE (--listen), so the script waits
    for you to say resume. A pause scripted in the stream itself runs on
    to the stream's own scripted resume.
    """

    def __init__(self, session: Session, clock: VirtualClock, speed: float,
                 silent: bool, hold_on_pause: bool) -> None:
        self.session = session
        self.clock = clock
        self.speed = speed
        self.silent = silent
        self.hold_on_pause = hold_on_pause
        self.stream_t = 0.0

    def _advance_to(self, t: float) -> None:
        if self.silent:
            self.clock.advance_to(max(self.clock.now(), t))
            self.stream_t = t
            self.session.tick()
            return
        last = time.perf_counter()
        while self.stream_t < t:
            time.sleep(0.02)
            now = time.perf_counter()
            dt = (now - last) * self.speed
            last = now
            self.clock.advance_by(dt)
            if not (self.hold_on_pause and self.session.paused):
                self.stream_t = min(t, self.stream_t + dt)
            self.session.tick()

    def play(self, stream: dict[str, Any]) -> None:
        for raw in sorted(stream.get("events", []), key=lambda e: e["t"]):
            self._advance_to(raw["t"])
            ts = self.clock.now()
            if "command" in raw:
                self.session.command(raw["command"], ts)
            elif "anomaly" in raw:
                self.session.on_event(AnomalyEvent(ts=ts, kind=raw["anomaly"], label=raw.get("label")))
            else:
                self.session.on_event(ActionEvent(
                    ts=ts, action=raw["action"], target=raw["target"],
                    source=raw.get("source"), dest=raw.get("dest"), zone=raw.get("zone"),
                    confidence=raw.get("confidence", 1.0),
                ))
        tail = stream.get("clip_duration_s")
        if tail is not None:
            self._advance_to(tail)
        self.session.tick()


def run_stream(path: Path, runtime_cfg: dict[str, Any], stage: Any, args: argparse.Namespace) -> dict[str, Any]:
    stream = json.loads(path.read_text(encoding="utf-8"))
    resolved = resolve(
        REPO_ROOT / "configs" / "protocols" / f"{stream['protocol_id']}.json",
        REPO_ROOT / "configs" / "defaults.yaml",
    )
    prompts_cfg = dict(runtime_cfg["audio"].get("prompts", {}))
    if args.mode:
        prompts_cfg["mode"] = args.mode
    clock = VirtualClock()
    worker = stage.worker
    spoken: list[AudioRequest] = []

    stage.prewarm_async(speakable_phrases(resolved))
    stage.wait_prewarm()

    def show(r: AudioRequest) -> None:
        spoken.append(r)
        print(f"  t={clock.now():6.2f}  {_describe(r)}", flush=True)

    session = Session(
        resolved, clock=clock,
        audio_submit=worker.submit if worker is not None else None,
        settings=AnnouncerSettings.from_config(prompts_cfg),
        audio_listeners=[show],
    )

    listener = None
    if args.listen:
        listener, warn = build_listener(
            runtime_cfg, REPO_ROOT,
            lambda p: (print(f"  [voice] heard: {p.text!r} -> {p.command}", flush=True),
                       session.command(p.command)),
        )
        if warn:
            print(f"WARNING: {warn}")
        elif listener is not None:
            listener.start()
            print('  [voice] listening -- say "Hey BAS, pause" / "resume" / "quiet mode" / "voice mode" / "repeat"')

    try:
        StreamPlayer(session, clock, args.speed, args.silent, hold_on_pause=listener is not None).play(stream)
        if worker is not None:
            worker.drain(timeout=60.0)
    finally:
        if listener is not None:
            listener.stop()

    out = session.engine.out
    return {
        "violations": sum(1 for e in out if e.event_type == "violation"),
        "anomalies": sum(1 for e in out if e.event_type == "anomaly"),
        "alerts_spoken": sum(1 for r in spoken if r.kind == "alert" and r.segments),
        "prompts": sum(1 for r in spoken if r.kind == "prompt"),
        "step_ticks": sum(1 for r in spoken if r.kind == "step"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("streams", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true", help="every harness/synthetic/*.json")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    ap.add_argument("--silent", action="store_true", help="record instead of play, no sleeping")
    ap.add_argument("--mode", choices=("voice", "quiet"), default=None, help="override start-up mode")
    ap.add_argument("--listen", action="store_true", help='live "Hey BAS" voice commands from the mic')
    args = ap.parse_args()
    if args.listen and args.silent:
        ap.error("--listen needs real-time pacing; drop --silent")

    paths = sorted(SYNTHETIC_DIR.glob("*.json")) if args.all else args.streams
    if not paths:
        ap.error("give stream paths or --all")

    runtime_cfg = load_runtime_config()
    stage = build_audio_stage(runtime_cfg, sink=RecordingSink() if args.silent else None)
    for w in stage.warnings:
        print(f"WARNING: {w}")
    print(f"audio: tts={stage.tts_backend} sink={stage.sink_name}")
    if stage.worker is not None:
        stage.worker.start()

    rows = []
    try:
        for path in paths:
            print(f"\n== {path.stem} ==")
            rows.append((path.stem, run_stream(path, runtime_cfg, stage, args)))
    finally:
        if stage.worker is not None:
            stage.worker.stop()

    print("\n" + "-" * 78)
    print(f"{'stream':26s} {'violations':>10s} {'anomalies':>9s} {'spoken':>7s} {'prompts':>8s} {'ticks':>6s}")
    for name, r in rows:
        print(f"{name:26s} {r['violations']:10d} {r['anomalies']:9d} {r['alerts_spoken']:7d} "
              f"{r['prompts']:8d} {r['step_ticks']:6d}")
    if stage.worker is not None:
        s = stage.worker.stats
        print(f"worker: played={s.played} interrupted={s.interrupted} "
              f"superseded_prompts={s.superseded_prompts} flushed={s.flushed_by_warning} "
              f"dropped_overflow={s.dropped_overflow} text_only={s.text_only}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
