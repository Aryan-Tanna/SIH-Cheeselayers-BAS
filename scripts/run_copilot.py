#!/usr/bin/env python3
"""Run the co-pilot headless: camera -> recording + stream, protocol
session with voice alerts and "Hey BAS" commands, hash-chained log.

    python scripts/run_copilot.py                         # until Ctrl+C
    python scripts/run_copilot.py --seconds 60
    python scripts/run_copilot.py --events harness/synthetic/clean_run.json
        # drive the protocol with a scripted event stream (no detector yet)
    python scripts/run_copilot.py --source 1 --no-voice-control
    python scripts/run_copilot.py --source path/to/clip.mp4

Edit the protocol JSON while it runs to hot-reload it. For the GUI, use
scripts/run_gui.py. Prints a session summary table on exit.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.runtime.app import AppOptions, CopilotApp  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402


def build_options(args: argparse.Namespace) -> AppOptions:
    source = None
    if args.source is not None:
        source = int(args.source) if str(args.source).isdigit() else args.source
    stream_url = None
    if args.stream_to:
        host, _, port = args.stream_to.partition(":")
        stream_url = f"udp://{host}:{port or 5000}?pkt_size=1316"
    return AppOptions(
        protocol=args.protocol, source=source, events=args.events, stream_url=stream_url,
        object_profile=args.profile,
        voice_control=not args.no_voice_control, capture=not args.no_capture,
        record=not args.no_record, audio=not args.no_audio,
        perception=not args.no_perception,
        downlink=args.downlink, link_delay_s=args.link_delay,
    )


def add_common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--protocol", type=Path, default=None)
    ap.add_argument("--profile", default=None,
                    help="object profile for the props on the rig, e.g. "
                         "configs/objects/profile_rect.yaml (slabs) or profile_mixed.yaml")
    ap.add_argument("--source", default=None, help="camera index, video file or stream URL")
    ap.add_argument("--events", type=Path, default=None, help="scripted event stream JSON")
    ap.add_argument("--no-voice-control", action="store_true")
    ap.add_argument("--no-capture", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-perception", action="store_true",
                    help="no detector: steps only via voice/GUI/--events")
    ap.add_argument("--stream-to", default=None, metavar="IP[:PORT]",
                    help="stream to this receiver (UDP, default port 5000) instead of stream.url")
    ap.add_argument("--downlink", default=None, metavar="IP[:PORT]",
                    help="send the log + event snapshots to a ground station "
                         "(scripts/ground_station.py; default port 5055)")
    ap.add_argument("--link-delay", type=float, default=None, metavar="S",
                    help="simulate a one-way light-time on the downlink (Moon ~1.3)")


def print_summary(summary: dict) -> None:
    print("\n" + "-" * 66)
    for k, v in summary.items():
        print(f"{k:22s} {v}")


def main() -> int:
    ap = argparse.ArgumentParser()
    add_common_args(ap)
    ap.add_argument("--seconds", type=float, default=None, help="stop after this long")
    ap.add_argument("--allow-internet", action="store_true", help="switch OFF the offline guard")
    args = ap.parse_args()
    if not args.allow_internet:
        from src.runtime.offline import install_offline_guard

        earth = (args.downlink or "").rpartition(":")[0] or args.downlink
        install_offline_guard({earth} if earth else set())

    app = CopilotApp(load_runtime_config(), build_options(args))
    print(f"\nsession {app.session_id}: log -> {app.log_path}")
    app.start()
    t0 = time.monotonic()
    try:
        while True:
            time.sleep(0.2)
            if args.seconds is not None and time.monotonic() - t0 >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    print_summary(app.stop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
