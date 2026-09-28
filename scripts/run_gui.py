#!/usr/bin/env python3
"""Run the co-pilot with the monitoring GUI.

    python scripts/run_gui.py                       # start screen: pick experiment, props, camera
    python scripts/run_gui.py --no-dashboard        # straight into configs/runtime.yaml's protocol
    python scripts/run_gui.py --events harness/synthetic/clean_run.json
    python scripts/run_gui.py --source 1 --no-voice-control

Same options as scripts/run_copilot.py. Passing --protocol, --events or
--seconds skips the start screen (scripted runs). In a session: Space
pause/resume, N next step, R repeat, Q quiet/voice, F5 reload protocol;
Restart and End session are buttons only (they ask first). Ending a
session prints its summary and returns to the start screen; closing the
start screen quits.
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_copilot import add_common_args, build_options, print_summary  # noqa: E402
from src.runtime.app import CopilotApp  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402
from src.runtime.gui import BG, FG, FONT_BIG, CopilotGUI, make_dpi_aware, setup_window  # noqa: E402


def bring_to_front(root: tk.Tk) -> None:
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.focus_force()


def run_scripted(args: argparse.Namespace) -> int:
    """No start screen: one session from the command line (demos, tests)."""
    app = CopilotApp(load_runtime_config(), build_options(args))
    root = tk.Tk()
    gui = CopilotGUI(root, app)
    bring_to_front(root)
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


def run_with_dashboard(args: argparse.Namespace) -> int:
    from tkinter import messagebox

    from src.runtime.dashboard import Dashboard

    cfg = load_runtime_config()
    base = build_options(args)
    root = tk.Tk()
    root.title("BAS Co-Pilot")
    setup_window(root)
    state: dict[str, Any] = {"app": None, "summary": None, "dash": None}

    def show_dashboard() -> None:
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        state["dash"] = Dashboard(root, cfg, on_start=start, last_summary=state["summary"],
                                  source=base.source, object_profile=base.object_profile)

    def start(choice: Any) -> None:
        state["dash"].destroy()
        busy = tk.Label(root, text="Starting the co-pilot...\n(loading the detector and the voice)",
                        bg=BG, fg=FG, font=FONT_BIG)
        busy.pack(expand=True)
        root.update()
        opts = replace(base, protocol=choice.protocol, object_profile=choice.object_profile,
                       source=choice.source if choice.source is not None else base.source,
                       voice_control=base.voice_control and choice.voice_control,
                       record=base.record and choice.record,
                       perception=base.perception and choice.perception)
        try:
            app = CopilotApp(cfg, opts)
        except Exception as exc:  # noqa: BLE001 -- show it, go back; never a dead window
            busy.destroy()
            messagebox.showerror("Could not start", f"{type(exc).__name__}: {exc}", parent=root)
            show_dashboard()
            return
        busy.destroy()
        state["app"] = app
        CopilotGUI(root, app, on_end=finish)
        app.start()

    def finish() -> None:
        app, state["app"] = state["app"], None
        if app is not None:
            state["summary"] = app.stop()
            print_summary(state["summary"])
        show_dashboard()

    show_dashboard()
    bring_to_front(root)
    try:
        root.mainloop()
    finally:
        if state["app"] is not None:  # window killed mid-session
            print_summary(state["app"].stop())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    add_common_args(ap)
    ap.add_argument("--seconds", type=float, default=None, help="close the window after this long")
    ap.add_argument("--screenshot", type=Path, default=None,
                    help="save a PNG of the window just before closing (with --seconds)")
    ap.add_argument("--no-dashboard", action="store_true", help="skip the start screen")
    args = ap.parse_args()

    make_dpi_aware()
    if args.no_dashboard or args.seconds is not None or args.events is not None or args.protocol is not None:
        return run_scripted(args)
    return run_with_dashboard(args)


if __name__ == "__main__":
    raise SystemExit(main())
