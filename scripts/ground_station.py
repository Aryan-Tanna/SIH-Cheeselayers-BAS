#!/usr/bin/env python3
"""BAS Mission Control -- the ground station for the co-pilot's downlink.

    python scripts/ground_station.py                 # listen on 0.0.0.0:5055
    python scripts/ground_station.py --port 6000
    python scripts/ground_station.py --headless      # no window: print what arrives

On the co-pilot:  python scripts/run_gui.py --downlink <this-PC-ip>[:port]
(add --link-delay 1.3 to simulate Moon light-time). Same PC: 127.0.0.1.

What it shows, live: the link (LIVE / NO SIGNAL, how long since the last
message), whether the received log's hash chain verifies line by line,
data received (log vs images) against session time, the checklist as
the crew is executing it, the event feed, and the latest image of each
step / violation -- marked VERIFIED only when its sha256 is attested by a
line in the hash chain. Everything is archived to ground_archive/.
Windows asks once to allow the port through the firewall: allow it.
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.link.ground_gui import MissionControl, ground_feed_line  # noqa: E402
from src.link.receiver import GroundReceiver  # noqa: E402
from src.runtime.gui import make_dpi_aware, setup_window  # noqa: E402


def run_headless(rx: GroundReceiver, seconds: float | None) -> None:
    seen: dict[str, int] = {}
    t_end = None if seconds is None else time.monotonic() + seconds
    try:
        while t_end is None or time.monotonic() < t_end:
            time.sleep(0.25)
            with rx.lock:
                for sid in rx.order:
                    s = rx.sessions[sid]
                    for rec in s.events[seen.get(sid, 0):]:
                        line = ground_feed_line(rec, s.events[0]["ts_monotonic"], {})
                        if line:
                            print(f"[{sid}] {line[0]}")
                    seen[sid] = len(s.events)
    except KeyboardInterrupt:
        pass


def print_summary(rx: GroundReceiver) -> None:
    print("\n" + "-" * 66)
    for sid in rx.order:
        s = rx.sessions[sid]
        verified = sum(1 for x in s.snapshots if x["intact"] and x["attested"])
        print(f"{sid}: {len(s.events)} log lines, chain {'VERIFIED' if s.chain_ok else 'TAMPERED: ' + s.chain_error}, "
              f"{verified}/{len(s.snapshots)} images verified, bytes log {s.bytes['log']} "
              f"images {s.bytes['snapshot']} other {s.bytes['other']}, report {'yes' if s.report else 'no'}")
    print(f"archive: {rx.archive}   messages {rx.messages}, duplicates ignored {rx.duplicates}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--archive", type=Path, default=REPO_ROOT / "ground_archive")
    ap.add_argument("--headless", action="store_true", help="no window: print events as they arrive")
    ap.add_argument("--seconds", type=float, default=None, help="stop after this long")
    ap.add_argument("--screenshot", type=Path, default=None, help="PNG of the window at the end (with --seconds)")
    args = ap.parse_args()
    # Windows consoles / redirected output default to cp1252: printing a ✓
    # would crash the ground station mid-session (found in a headless run).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    from src.runtime.offline import install_offline_guard

    install_offline_guard()  # the ground only listens; it never connects out
    rx = GroundReceiver(args.archive, host=args.host, port=args.port)
    rx.start()
    try:
        if args.headless:
            run_headless(rx, args.seconds)
            return 0
        make_dpi_aware()
        root = tk.Tk()
        setup_window(root)
        MissionControl(root, rx)
        if args.seconds is not None:
            def finish() -> None:
                if args.screenshot is not None:
                    from PIL import ImageGrab

                    root.attributes("-topmost", True)
                    root.lift()
                    root.update()
                    x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
                    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(args.screenshot)
                root.destroy()
            root.after(int(args.seconds * 1000), finish)
        root.mainloop()
    finally:
        rx.stop()
        print_summary(rx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
