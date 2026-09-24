#!/usr/bin/env python3
"""Run the co-pilot with the monitoring GUI.

    python scripts/run_gui.py
    python scripts/run_gui.py --events harness/synthetic/clean_run.json
    python scripts/run_gui.py --source 1 --no-voice-control

Same options as scripts/run_copilot.py. Keys: Space pause/resume,
N next step, R repeat, Q quiet/voice, F5 reload protocol. Closing the
window ends the session and prints its summary table.
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_copilot import add_common_args, build_options, print_summary  # noqa: E402
from src.runtime.app import CopilotApp  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402
from src.runtime.gui import CopilotGUI, make_dpi_aware  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    add_common_args(ap)
    ap.add_argument("--seconds", type=float, default=None, help="close the window after this long")
    ap.add_argument("--screenshot", type=Path, default=None,
                    help="save a PNG of the window just before closing (with --seconds)")
    args = ap.parse_args()

    app = CopilotApp(load_runtime_config(), build_options(args))
    make_dpi_aware()
    root = tk.Tk()
    gui = CopilotGUI(root, app)
    app.start()
    if args.seconds is not None:
        def finish() -> None:
            if args.screenshot is not None:
                from PIL import ImageGrab

                root.attributes("-topmost", True)  # grab the window, not whatever is on top
                root.lift()
                root.update()
                root.after(300)
                root.update()
                x, y = root.winfo_rootx(), root.winfo_rooty()
                w, h = root.winfo_width(), root.winfo_height()
                ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(args.screenshot)
            gui.close()
        root.after(int(args.seconds * 1000), finish)
    try:
        root.mainloop()
    finally:
        print_summary(app.stop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
