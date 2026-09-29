#!/usr/bin/env python3
"""Send stored sessions to Earth -- the fully offline mode's link window.

    python scripts/send_to_earth.py 192.168.1.42            # every session not yet sent
    python scripts/send_to_earth.py 100.64.0.7:5055 --session session_20260929_193209
    python scripts/send_to_earth.py 127.0.0.1 --all          # re-send all (the ground skips what it has)

Same as the "Send to Earth" buttons in the start screen's Sessions tab.
Each session: its hash-chained log, one image per step / alert, the
report -- verified at Mission Control exactly like the live link.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.link.upload import sent_info, upload_session  # noqa: E402
from src.runtime.offline import install_offline_guard  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("earth", help="Earth IP[:port] (Mission Control), default port 5055")
    ap.add_argument("--session", action="append", default=[], help="session id (repeatable)")
    ap.add_argument("--all", action="store_true", help="also sessions already sent")
    ap.add_argument("--logs", type=Path, default=REPO_ROOT / "logs")
    args = ap.parse_args()
    host, _, port = args.earth.rpartition(":") if ":" in args.earth else (args.earth, "", "5055")
    install_offline_guard({host}, printer=print)

    logs = sorted(args.logs.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if args.session:
        logs = [p for p in logs if p.stem in set(args.session)]
    elif not args.all:
        logs = [p for p in logs if sent_info(p) is None]
    if not logs:
        print("nothing to send")
        return 0
    print(f"{'session':32s} {'lines':>6s} {'images':>6s} {'bytes':>9s}  result")
    failed = 0
    for log in logs:
        r = upload_session(log, host, int(port), timeout_s=45.0)
        print(f"{r['session_id']:32s} {r['log_lines']:6d} {r['images']:6d} {r['bytes_sent']:9d}  "
              + ("sent, verified at Earth" if r["ok"] else f"FAILED: {r['error']}"))
        if not r["ok"]:
            failed += 1
            break  # the link is down: stop here, nothing is lost
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
