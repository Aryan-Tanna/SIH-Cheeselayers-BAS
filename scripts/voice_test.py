#!/usr/bin/env python3
"""Live check of "Hey BAS" voice commands on this machine's microphone.

Runs the production listener (src/runtime/voice_control.py) for a fixed
time and prints EVERY utterance the recognizer finalises -- including
the ones rejected as ordinary speech -- with the mic level while it was
spoken, so a miss can be told apart from "the mic heard nothing".
Recognised commands get the wake chime plus a spoken confirmation.

    python scripts/voice_test.py            # 60 s
    python scripts/voice_test.py --seconds 120 --no-speak

Say, for example:
    "Hey BAS, pause"   "Hey BAS, resume"   "Hey BAS, quiet mode"
    "Hey BAS" ... (chime) ... "repeat"
    and some ordinary sentences, which must be ignored.

Prints a summary table at the end.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.runtime.announcer import EARCON_WAKE, AudioRequest  # noqa: E402
from src.runtime.config import build_audio_stage, load_runtime_config  # noqa: E402
from src.runtime.voice_control import WAKE, ParsedCommand, build_listener  # noqa: E402

CONFIRM = {
    "pause": "Paused.",
    "resume": "Resuming.",
    "quiet": "Quiet mode. Alerts only.",
    "voice": "Voice prompts on.",
    "repeat": "Repeating the current step.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--no-speak", action="store_true", help="chime only, no spoken confirmation")
    args = ap.parse_args()

    import numpy as np

    cfg = load_runtime_config()
    stage = build_audio_stage(cfg)
    worker = stage.worker
    if worker is not None:
        worker.start()
        if not args.no_speak:
            worker.tts.prewarm(list(CONFIRM.values()))

    utterances: list[tuple[float, str, str | None, float]] = []
    level = {"peak_rms": 0.0}
    t_start = time.monotonic()

    def on_command(p: ParsedCommand) -> None:
        if worker is None:
            return
        if p.command == WAKE or args.no_speak:
            worker.submit([AudioRequest(kind="system", earcon=EARCON_WAKE)])
        else:
            worker.submit([AudioRequest(kind="system", earcon=EARCON_WAKE,
                                        segments=(CONFIRM[p.command],))])

    listener, warn = build_listener(cfg, REPO_ROOT, on_command)
    if listener is None:
        print(f"voice control unavailable: {warn or 'disabled in configs/runtime.yaml'}")
        return 1

    # Instrument the production listener without changing it: mic level
    # per audio block, and every finalised utterance (accepted or not).
    orig_put = listener._audio.put_nowait

    def put_with_level(chunk: bytes) -> None:
        a = np.frombuffer(chunk, dtype=np.int16).astype(np.float64)
        level["peak_rms"] = max(level["peak_rms"], float(np.sqrt(np.mean(a * a))) if len(a) else 0.0)
        orig_put(chunk)

    listener._audio.put_nowait = put_with_level  # type: ignore[method-assign]
    orig_feed = listener.feed_text

    def feed_and_log(text: str) -> ParsedCommand | None:
        parsed = orig_feed(text)
        rms = level["peak_rms"]
        level["peak_rms"] = 0.0
        if text:
            cmd = parsed.command if parsed else None
            utterances.append((time.monotonic() - t_start, text, cmd, rms))
            verdict = f"-> COMMAND {cmd}" if cmd else "-> ignored"
            print(f"  {time.monotonic() - t_start:6.1f}s  heard {text!r:28} {verdict:22} (mic peak rms {rms:.0f})",
                  flush=True)
        return parsed

    listener.feed_text = feed_and_log  # type: ignore[method-assign]

    print(f"audio out: {stage.sink_name}; listening for {args.seconds:.0f} s on the default mic.")
    print('Say "Hey BAS, pause" / "resume" / "quiet mode" / "voice mode" / "repeat", '
          'or "Hey BAS", wait for the chime, then the command.', flush=True)
    listener.start()
    try:
        stop = threading.Event()
        stop.wait(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        if worker is not None:
            worker.drain(5.0)
            worker.stop()

    print("\n" + "-" * 70)
    accepted = [u for u in utterances if u[2]]
    print(f"utterances finalised: {len(utterances)}   accepted: {len(accepted)}   "
          f"ignored: {len(utterances) - len(accepted)}")
    counts: dict[str, int] = {}
    for _, _, cmd, _ in accepted:
        counts[cmd] = counts.get(cmd, 0) + 1  # type: ignore[index]
    for cmd in ("wake", "pause", "resume", "quiet", "voice", "repeat"):
        print(f"  {cmd:8s} {counts.get(cmd, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
