"""Monitoring GUI (Tkinter): live video, the protocol checklist, the
current step, alerts and the operator controls.

Tkinter because it ships with Python on Windows, macOS and Linux -- no
extra dependency, nothing to install on the demo machine. The GUI is a
thin client of CopilotApp: it only reads app.status() / app.latest_frame()
and calls app.command() / app.reload_protocol(), all thread-safe, polled
from Tk's own loop (Tk must only be touched from its main thread). So
the toolkit can be swapped without touching anything else.

The voice is still the primary interface -- an astronaut mid-task is not
looking at a screen. The GUI is for monitoring (crew or ground) and for
the same commands by hand: every button maps 1:1 to a voice command.

Formatting helpers are pure functions so they are unit-testable without
a display.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Any

# --- palette (dark: sits next to a glovebox window, not a white page) -----
BG = "#11151c"
PANEL = "#1a202b"
PANEL_2 = "#222a37"
FG = "#e6e9ef"
MUTED = "#8b93a3"
ACCENT = "#4aa3ff"
OK = "#3ecf8e"
CONFIRMED = "#a78bfa"
WARN = "#ffb020"
BAD = "#ff5c5c"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BIG = ("Segoe UI", 16, "bold")
FONT_MONO = ("Consolas", 9)

STATUS_STYLE = {
    # status -> (glyph, colour, label)
    "done": ("✓", OK, "done"),
    "confirmed": ("✓", CONFIRMED, "confirmed by operator"),
    "missed": ("✗", BAD, "missed"),
    "not_applicable": ("–", MUTED, "not applicable"),
    "open": ("▶", ACCENT, "due now"),
    "pending": ("·", MUTED, ""),
}
SEVERITY_COLOUR = {"warning": BAD, "caution": WARN, "advisory": ACCENT}
DET_BGR = {  # overlay colours per detector class (OpenCV BGR)
    "case_open": (255, 255, 255), "case_closed": (170, 170, 170),
    "red_module": (60, 60, 255), "yellow_module": (0, 220, 255),
    "red_lid": (200, 60, 255), "yellow_lid": (0, 150, 255),
    "hand_bare": (80, 220, 80), "hand_gloved": (255, 200, 0),
}


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------

def fit_size(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Largest size with the source aspect ratio inside max_w x max_h."""
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return (0, 0)
    scale = min(max_w / src_w, max_h / src_h)
    return (max(1, int(src_w * scale)), max(1, int(src_h * scale)))


@dataclass(frozen=True)
class StepLine:
    glyph: str
    text: str
    colour: str
    is_current: bool


def step_lines(snapshot: dict[str, Any]) -> list[StepLine]:
    current = snapshot.get("current_step")
    out = []
    for s in snapshot.get("steps", []):
        glyph, colour, label = STATUS_STYLE.get(s["status"], ("?", MUTED, s["status"]))
        is_current = s["id"] == current and s["status"] == "open"
        # the green tick already says "done"; words only where the glyph can't
        suffix = f"   ({label})" if label and s["status"] not in ("pending", "open", "done") else ""
        # Prompts repeat across objects ("Unseal the module." for both
        # modules), so name the object, exactly as the voice does.
        obj = f"{s['object']}:  " if s.get("object") else ""
        if s.get("optional") and s["status"] not in ("done", "confirmed"):
            suffix, colour = "   (optional)", MUTED
        out.append(StepLine(glyph, f"{obj}{s['prompt']}{suffix}",
                            ACCENT if is_current else colour, is_current))
    return out


def current_step_text(snapshot: dict[str, Any]) -> str:
    if snapshot.get("paused"):
        return "PAUSED  -  say \"Hey BAS, resume\""
    cur = snapshot.get("current_step")
    for s in snapshot.get("steps", []):
        if s["id"] == cur:
            obj = f"   ({s['object']})" if s.get("object") else ""
            return f"NOW:  {s['prompt']}{obj}"
    if snapshot.get("steps") and all(
        s["status"] in ("done", "confirmed", "missed", "not_applicable") or s.get("optional")
        for s in snapshot["steps"]
    ):
        return "Experiment complete."
    return "Waiting..."


def det_badge(st: Any) -> tuple[str, str]:
    """Detector rate and camera-to-detections latency, measured live."""
    if not getattr(st, "perception", False):
        return "DET off", PANEL_2
    return (f"DET {st.detector_fps:4.1f} fps  {st.frame_latency_ms:4.0f} ms  [D]",
            WARN if st.detector_fps and st.detector_fps < 5 else PANEL_2)


def rack_badge(st: Any) -> tuple[str, str]:
    """ArUco rack geometry: is the tub floor frame known right now?
    Grey when off, amber when holding or not calibrated, red when lost."""
    status = getattr(st, "rack_status", "off")
    ids = ",".join(str(i) for i in (getattr(st, "rack_markers_seen", ()) or ())) or "-"
    if status == "ok":
        err = getattr(st, "rack_reproj_px", None)
        return (f"RACK ok  [{ids}]" + (f"  {err:.1f}px" if err is not None else "") + "  [K]", OK)
    if status == "held":
        return f"RACK held  [{ids}]  [K]", WARN
    if status == "uncalibrated":
        return f"RACK not calibrated  [{ids}]  [K]", WARN
    if status == "none":
        return "RACK lost - image space  [K]", BAD
    return "RACK off  [K]", PANEL_2


def attend_badge(snapshot: dict[str, Any]) -> tuple[str, str] | None:
    """The attended_while_open timer. None (badge hidden) unless a module
    is open. Amber while hands are away and the grace clock runs, red once
    it has run out (the alert fired)."""
    a = snapshot.get("attendance") or {}
    mods = a.get("open_modules") or []
    if not a.get("enabled") or not mods:
        return None
    names = ", ".join(mods)
    if a.get("hands_in_view", True) or a.get("away_s") is None:
        return f"OPEN {names}  hands in view", PANEL_2
    grace = a.get("grace_s") or 0
    text = f"OPEN {names}  hands away {a['away_s']:.1f}/{grace:g} s"
    return text, BAD if (a.get("alerted") or a["away_s"] >= grace) else WARN


def mic_badge(st: Any) -> tuple[str, str]:
    """(text, background) for the MIC badge. Names the device, and turns
    red when it is delivering pure silence (a virtual or muted mic)."""
    if not st.voice_control:
        return "MIC off", PANEL_2
    short = (st.mic_name or "?").split("(")[-1].rstrip(")")[:22]
    if getattr(st, "mic_silent", False):
        return f"MIC SILENT: {short}", BAD
    if st.listening_armed:
        return f"MIC listening...  ({short})", ACCENT
    return f"MIC \"Hey BAS\"  ({short})", PANEL_2


# Violation codes in words, for the event feed (the log keeps the codes).
VIOLATION_TEXT = {
    "skip": "Missed step",
    "out_of_order": "Out of order",
    "wrong_object": "Wrong object",
    "mutual_exclusion_breach": "Two modules out at once",
    "lid_unstowed": "Lid not stowed",
    "module_not_sealed": "Module not sealed",
    "module_not_returned": "Module not returned",
    "premature_close": "Closed too early",
    "loose_object": "Loose object",
    "wrong_orientation": "Wrong orientation",
    "unattended_open_module": "Open module left unattended",
    "step_overdue": "Step over its time limit",
    "extra_step": "Extra step, not in the procedure",
}


def progress_text(snapshot: dict[str, Any]) -> str:
    """'Step 4 of 12' -- conditional steps skipped for these props don't count."""
    # optional steps count only once done: they are allowed, never required
    steps = [s for s in snapshot.get("steps", []) if s["status"] != "not_applicable"
             and not (s.get("optional") and s["status"] not in ("done", "confirmed"))]
    if not steps:
        return ""
    done = sum(s["status"] in ("done", "confirmed") for s in steps)
    missed = sum(s["status"] == "missed" for s in steps)
    return f"{done} of {len(steps)} steps done" + (f",  {missed} missed" if missed else "")


HAND_LINKS = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
              (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
              (18, 19), (19, 20), (0, 17))


def object_names(snapshot: dict[str, Any]) -> dict[str, str]:
    """role -> spoken object name ("module_a" -> "red module"), from the
    protocol snapshot, plus "<role>.lid" -> "<name> cap"."""
    names: dict[str, str] = {}
    for s in snapshot.get("steps", []):
        role = (s.get("target") or "").split(".", 1)[0]
        if role and s.get("object") and role not in names:
            names[role] = s["object"]
    names.update({f"{r}.lid": f"{n} cap" for r, n in list(names.items())})
    return names


def hand_cue_text(cues: list[dict[str, Any]], names: dict[str, str], gloved: int = 0) -> str:
    """One line for the hand cues. Reach is a prediction that is right
    about a third of the time (measured), so it says 'maybe'."""
    parts = []
    for c in cues:
        n = names.get(c["obj"], c["obj"])
        if c["state"] == "holding":
            parts.append(f"Holding: {n}")
        elif c["state"] == "reaching":
            eta = f" ({c['eta_s']:.1f} s)" if c.get("eta_s") is not None else ""
            parts.append(f"Maybe reaching for: {n}{eta}")
    if gloved:
        parts.append(f"{gloved} gloved hand{'s' if gloved > 1 else ''} (no skeleton)")
    return "   ·   ".join(parts)


def activity_text(activity: str, cues: list[dict[str, Any]], names: dict[str, str], gloved: int = 0) -> str:
    """The 'now doing' line: the derived activity, plus the reach hint
    (a guess -- measured right about a third of the time -- so 'maybe')."""
    parts = [f"Now doing:  {activity}"] if activity else []
    for c in cues:
        if c["state"] == "reaching":
            eta = f" ({c['eta_s']:.1f} s)" if c.get("eta_s") is not None else ""
            parts.append(f"maybe reaching for the {names.get(c['obj'], c['obj'])}{eta}")
    if gloved:
        parts.append(f"{gloved} gloved hand{'s' if gloved > 1 else ''} (no skeleton)")
    return "   ·   ".join(parts)


def earth_badge(st: Any) -> tuple[str, str] | None:
    """Downlink to the ground station: None when not configured."""
    d = getattr(st, "downlink", None)
    if not d:
        return None
    sent = d["bytes_sent"]
    size = f"{sent / 1024:.0f} KB" if sent < 1 << 20 else f"{sent / (1 << 20):.1f} MB"
    if d["connected"]:
        waiting = d["queued"]
        return (f"EARTH ● {size} sent" + (f", {waiting} queued" if waiting > 3 else ""), OK)
    return (f"EARTH: no link, {d['unacked']} buffered", WARN)


def offline_badge() -> tuple[str, str] | None:
    """OFFLINE when the guard is on (src/runtime/offline.py); how many
    attempts to leave the local network it refused. None = guard off."""
    from src.runtime.offline import blocked_attempts, guard_installed

    if not guard_installed():
        return None
    n = len(blocked_attempts())
    return ("OFFLINE ✓", OK) if n == 0 else (f"OFFLINE - {n} blocked", WARN)


HELP_TEXT = """WHAT THE SCREEN SHOWS
  Right panel - PROTOCOL: every step.  ✓ done   ✓ (purple) confirmed by you   ▶ due now
                ✗ missed   –  not applicable to these props   ·  later.  (optional) = allowed, never required.
  EVENTS: steps done and every alert, with the time since the session started.
  Big bar: the step to do NOW.  "Now doing": what the camera sees you doing.

BADGES (top)
  VOICE / QUIET   whether steps are spoken             RUNNING / PAUSED
  MIC             the microphone "Hey BAS" listens on   DET  detector speed and delay
  RACK            ArUco markers seen (rack geometry)    REC  local recording
  STREAM          live video to an IP                   EARTH  log + images sent to the ground station
  OFFLINE         nothing may leave the local network except the Earth IP (blocked attempts are counted)
  OPEN MODULE     a module is open with no hands in view (timer)

KEYS                                   VOICE ("Hey BAS, ...")
  Space  pause / resume                pause, resume
  N      next step (camera missed it)  next step
  R      repeat the current step       repeat
  Q      quiet / voice prompts         quiet mode, voice mode
  D      show detections               restart experiment (say it twice)
  E      protocol editor   K rack setup   F5 reload protocol   H / F1 this help

ALERTS: one alert per root cause; everything is in the log (logs/<session>.jsonl, hash-chained)
and a readable report is written when the session ends (logs/<session>.report.txt)."""


def event_line(e: dict[str, Any], t0: float | None,
               step_names: dict[str, str] | None = None) -> tuple[str, str] | None:
    """(text, colour) for the event feed, or None for internal noise.
    step_names: step id -> the words shown for it (object + prompt)."""
    rel = "" if t0 is None else f"{e['ts'] - t0:7.1f}s  "
    kind = e["type"]
    names = step_names or {}
    if kind == "violation":
        what = VIOLATION_TEXT.get(e.get("code") or "", e.get("code") or "violation")
        on = names.get(e.get("step") or "") or e.get("target") or ""
        return (f"{rel}{(e.get('severity') or '').upper():8s} {what}" + (f":  {on}" if on else ""),
                SEVERITY_COLOUR.get(e.get("severity") or "", WARN))
    if kind == "anomaly":
        return (f"{rel}ANOMALY  {e.get('message') or ''}", WARN)
    if kind == "step_complete":
        how = "  (confirmed by operator)" if e.get("status") == "operator_confirmed" else ""
        return (f"{rel}✓ done   {names.get(e.get('step') or '', e.get('step'))}{how}", OK)
    if kind in ("session_paused", "session_resumed"):
        return (f"{rel}{kind.replace('session_', '').upper()}", MUTED)
    if kind == "protocol_reloaded":
        return (f"{rel}PROTOCOL RELOADED  {e.get('message') or ''}", ACCENT)
    if kind == "operator_command":
        return (f"{rel}operator: {e.get('message')}", MUTED)
    if kind == "session_start":
        return (f"{rel}session start", MUTED)
    return None  # next_step_suggested, unmatched_action, engine_anomaly: log only


# ----------------------------------------------------------------------
# Window
# ----------------------------------------------------------------------

def make_dpi_aware() -> None:
    """Call BEFORE tk.Tk(). Without it Windows bitmap-stretches the whole
    window on a scaled display (125% on the dev laptop): blurry text and
    window coordinates that disagree with the screen's."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def setup_window(root: tk.Tk) -> None:
    """Size the one main window (dashboard and session share it)."""
    if getattr(root, "_bas_sized", False):
        return
    root._bas_sized = True  # type: ignore[attr-defined]
    root.configure(bg=BG)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = int(sw * 0.9), int(sh * 0.86)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
    root.minsize(min(1000, sw), min(620, sh))


class CopilotGUI:
    # ~25 fps display. A redraw measured 15.6 ms (1080p -> 1500x850, boxes +
    # skeletons) after reusing the Tk image; 40 ms keeps the GUI thread free
    # more than half the time. The recording is independent of this.
    VIDEO_MS = 40
    PANEL_MS = 250

    def __init__(self, root: tk.Tk, app: Any, on_end: Any = None) -> None:
        """on_end: called when the operator ends the session (the dashboard
        takes over again). Without it, ending closes the window."""
        self.root = root
        self.app = app
        self.on_end = on_end
        self._photo: Any = None
        self._last_steps: tuple | None = None
        self._last_event_count = -1
        self._t0: float | None = None
        self._session_id: str | None = None
        self._closed = False

        root.title("BAS Co-Pilot")
        root.configure(bg=BG)
        setup_window(root)
        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill="both", expand=True)
        self._build()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.end_session)
        self._tick_video()
        self._tick_panels()

    # --- layout --------------------------------------------------------------

    def _build(self) -> None:
        r = self.frame
        header = tk.Frame(r, bg=PANEL, height=44)
        header.pack(side="top", fill="x")
        self.title_lbl = tk.Label(header, text="", bg=PANEL, fg=FG, font=FONT_BOLD)
        self.title_lbl.pack(side="left", padx=12, pady=8)
        self.badges: dict[str, tk.Label] = {}
        self.show_dets = True
        for key in ("net", "earth", "stream", "rec", "rack", "det", "mic", "attend", "paused", "mode"):
            lbl = tk.Label(header, text="", bg=PANEL_2, fg=FG, font=FONT_BOLD, padx=8, pady=2)
            lbl.pack(side="right", padx=4, pady=8)
            self.badges[key] = lbl

        body = tk.Frame(r, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=PANEL, width=560)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        # Banner and last-spoken line are packed at the BOTTOM first so they
        # always keep their space; the video box takes what is left and
        # never grows to fit its image (pack_propagate off) -- otherwise
        # the label grows to the image, the image is sized to the label,
        # and the banner and controls are pushed off the window.
        self.spoken_lbl = tk.Label(left, text="", bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.spoken_lbl.pack(side="bottom", fill="x", pady=(4, 0))
        self.now_lbl = tk.Label(left, text="", bg=PANEL, fg=FG, font=FONT_BIG, anchor="w",
                                padx=14, pady=10, justify="left")
        self.now_lbl.pack(side="bottom", fill="x", pady=(8, 0))
        self.hands_lbl = tk.Label(left, text="", bg=BG, fg=ACCENT, font=FONT_BOLD, anchor="w")
        self.hands_lbl.pack(side="bottom", fill="x", pady=(2, 0))
        self.progress_lbl = tk.Label(left, text="", bg=BG, fg=MUTED, font=FONT_BOLD, anchor="w")
        self.progress_lbl.pack(side="bottom", fill="x", pady=(6, 0))
        self.video_box = tk.Frame(left, bg="#000000")
        self.video_box.pack(side="top", fill="both", expand=True)
        self.video_box.pack_propagate(False)
        self.video = tk.Label(self.video_box, bg="#000000", fg=MUTED,
                              text="waiting for camera...", font=FONT)
        self.video.place(relx=0.5, rely=0.5, anchor="center")
        self.now_lbl.bind("<Configure>", lambda e: self.now_lbl.configure(wraplength=e.width - 30))

        tk.Label(right, text="PROTOCOL", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").pack(
            side="top", fill="x", padx=12, pady=(10, 2))
        self.steps_txt = tk.Text(right, bg=PANEL, fg=FG, font=FONT, relief="flat", wrap="word",
                                 height=16, cursor="arrow", highlightthickness=0)
        self.steps_txt.pack(side="top", fill="x", padx=8)
        tk.Label(right, text="EVENTS", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").pack(
            side="top", fill="x", padx=12, pady=(10, 2))
        self.events_txt = tk.Text(right, bg=PANEL_2, fg=FG, font=FONT_MONO, relief="flat",
                                  wrap="word", cursor="arrow", highlightthickness=0)
        self.events_txt.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))
        for colour in {OK, CONFIRMED, BAD, WARN, ACCENT, MUTED, FG}:
            self.steps_txt.tag_configure(colour, foreground=colour)
            self.events_txt.tag_configure(colour, foreground=colour)
        self.steps_txt.tag_configure("current", font=FONT_BOLD, background=PANEL_2)
        # hanging indent: a wrapped step lines up under its text, not the glyph
        self.steps_txt.tag_configure("step", lmargin1=4, lmargin2=30, spacing1=2)
        # wrapped event lines hang under the text, not under the timestamp
        self.events_txt.tag_configure("event", lmargin1=2, lmargin2=110)

        # Two rows: what the operator uses during the experiment (each one a
        # voice command too), and setup tools nobody needs mid-experiment.
        tools = tk.Frame(r, bg=BG)
        tools.pack(side="bottom", fill="x", padx=10, pady=(0, 8), before=body)
        controls = tk.Frame(r, bg=BG)
        controls.pack(side="bottom", fill="x", padx=10, pady=(10, 6), before=tools)
        self.pause_btn = self._button(controls, "⏸  Pause  [Space]", self._toggle_pause, big=True)
        self._button(controls, "↻  Repeat  [R]", lambda: self.app.command("repeat"), big=True)
        self._button(controls, "✓  Next step  [N]", lambda: self.app.command("next"), big=True)
        if hasattr(self.app, "restart_session"):
            self._button(controls, "⟲  Restart", self._restart, big=True)
        self.mode_btn = self._button(controls, "Quiet mode  [Q]", self._toggle_mode, big=True)
        end = self._button(controls, "End session", self.end_session, big=True)
        end.pack_configure(side="right", padx=0)
        end.configure(bg=BAD, fg=BG)

        tk.Label(tools, text="Setup:", bg=BG, fg=MUTED, font=FONT_BOLD).pack(side="left", padx=(0, 6))
        self._button(tools, "Show detections  [D]", self._toggle_dets)
        self._button(tools, "Reload protocol  [F5]", self.app.reload_protocol)
        if hasattr(self.app, "rack_config"):
            self._button(tools, "Rack setup  [K]", self._open_rack)
        if hasattr(self.app, "use_protocol"):
            self._button(tools, "Protocol editor  [E]", self._open_editor)
        self._button(tools, "?  Help  [H]", self._open_help)
        self.hint_lbl = tk.Label(
            tools, bg=BG, fg=MUTED, font=FONT, anchor="w",
            text='Voice: "Hey BAS, pause / resume / repeat / next step / restart experiment (say twice)"')
        self.hint_lbl.pack(side="left", padx=10)
        self.warn_lbl = tk.Label(tools, text="", bg=BG, fg=WARN, font=FONT, anchor="e")
        self.warn_lbl.pack(side="right", fill="x", expand=True)

    def _button(self, parent: tk.Widget, text: str, cmd: Any, big: bool = False) -> tk.Button:
        b = tk.Button(parent, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      activeforeground=BG, relief="flat", font=FONT_BOLD,
                      padx=16 if big else 10, pady=9 if big else 4, cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    KEYS = ("<space>", "<n>", "<r>", "<q>", "<F5>", "<d>", "<k>", "<e>", "<h>", "<F1>")

    def _bind_keys(self) -> None:
        self.root.bind("<space>", lambda _e: self._toggle_pause())
        self.root.bind("<n>", lambda _e: self.app.command("next"))
        self.root.bind("<r>", lambda _e: self.app.command("repeat"))
        self.root.bind("<q>", lambda _e: self._toggle_mode())
        self.root.bind("<F5>", lambda _e: self.app.reload_protocol())
        self.root.bind("<d>", lambda _e: self._toggle_dets())
        self.root.bind("<k>", lambda _e: self._open_rack())
        self.root.bind("<e>", lambda _e: self._open_editor())
        self.root.bind("<h>", lambda _e: self._open_help())
        self.root.bind("<F1>", lambda _e: self._open_help())

    # --- actions ----------------------------------------------------------------

    def _toggle_dets(self) -> None:
        self.show_dets = not self.show_dets

    def _restart(self) -> None:
        """Button restart: a dialog is the confirmation (voice: say it twice).
        No keyboard shortcut on purpose -- one stray key must not wipe a run."""
        from tkinter import messagebox

        if not messagebox.askyesno(
                "Restart the experiment?",
                "Start again from step one?\n\nThis ends the current session (its log is kept "
                "and verified) and starts a new one.", parent=self.root):
            return
        self.app.restart_session()

    def end_session(self) -> None:
        from tkinter import messagebox

        if self.on_end is not None and not messagebox.askyesno(
                "End the session?", "Stop the co-pilot and go back to the start screen?\n\n"
                "The log and recording are saved.", parent=self.root):
            return
        self.close()

    def _toggle_pause(self) -> None:
        self.app.command("resume" if self.app.status().protocol["paused"] else "pause")

    def _toggle_mode(self) -> None:
        self.app.command("voice" if self.app.status().protocol["mode"] == "quiet" else "quiet")

    def _open_editor(self) -> None:
        if not hasattr(self.app, "use_protocol"):
            return
        ed = getattr(self, "_editor", None)
        if ed is not None and ed.win.winfo_exists():
            ed.win.lift()
            return
        from src.runtime.protocol_editor_gui import ProtocolEditor

        self._editor = ProtocolEditor(self.root, self.app)

    def _open_help(self) -> None:
        win = getattr(self, "_help_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title("BAS Co-Pilot - help")
        win.transient(self.root)
        tk.Label(win, text=HELP_TEXT, bg=PANEL, fg=FG, font=FONT_MONO, justify="left", anchor="w").pack(
            padx=16, pady=(14, 8))
        tk.Button(win, text="Close", command=win.destroy, bg=PANEL_2, fg=FG, relief="flat",
                  font=FONT_BOLD, padx=14, pady=4).pack(pady=(0, 12))
        self._help_win = win

    def _open_rack(self) -> None:
        if not hasattr(self.app, "rack_config"):
            return
        win = getattr(self, "_rack_win", None)
        if win is not None and win.win.winfo_exists():
            win.win.lift()
            return
        self._rack_win = RackDialog(self.root, self.app)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.on_end is None:
            self.root.destroy()
            return
        for key in self.KEYS:
            self.root.unbind(key)
        for child in ("_editor", "_rack_win"):
            w = getattr(self, child, None)
            if w is not None and w.win.winfo_exists():
                w.win.destroy()
        hw = getattr(self, "_help_win", None)
        if hw is not None and hw.winfo_exists():
            hw.destroy()
        self.frame.destroy()
        self.on_end()

    # --- refresh loops ------------------------------------------------------------

    def _tick_video(self) -> None:
        if self._closed:
            return
        try:
            self._draw_frame()
        finally:
            self.root.after(self.VIDEO_MS, self._tick_video)

    def _draw_frame(self) -> None:
        frame = self.app.latest_frame()
        if frame is None:
            return
        import cv2
        from PIL import Image, ImageTk

        img = frame.payload
        h, w = img.shape[:2]
        tw, th = fit_size(w, h, self.video_box.winfo_width(), self.video_box.winfo_height())
        if tw < 2 or th < 2:
            return
        # INTER_LINEAR: a display downscale; INTER_AREA cost several ms more per frame
        small = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
        latest = getattr(self.app, "latest_detections", None)
        if self.show_dets and latest is not None:
            import numpy as np

            sx, sy = tw / w, th / h
            for d in latest()[1]:
                c = DET_BGR.get(d.cls, (255, 0, 255))
                pts = np.array([(x * sx, y * sy) for x, y in d.corners], dtype=np.int32)
                cv2.polylines(small, [pts.reshape(-1, 1, 2)], True, c, 2)
                x0, y0 = int(pts[:, 0].min()), int(pts[:, 1].min())
                cv2.putText(small, f"{d.cls} {d.conf:.2f}", (x0, max(14, y0 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
        hand = getattr(self.app, "latest_hand_frame", None)
        hf = hand() if hand is not None else None
        if self.show_dets and hf is not None:
            sx, sy = tw / w, th / h
            for pose in hf.poses:
                pts = [(int(x * sx), int(y * sy)) for x, y in pose.landmarks]
                for a, b in HAND_LINKS:
                    cv2.line(small, pts[a], pts[b], (80, 255, 160), 2, cv2.LINE_AA)
                for i in (4, 8, 12, 16, 20):  # fingertips
                    cv2.circle(small, pts[i], 4, (255, 255, 255), -1, cv2.LINE_AA)
        markers = getattr(self.app, "latest_rack_markers", None)
        if self.show_dets and markers is not None:
            import numpy as np

            sx, sy = tw / w, th / h
            for mid, c in markers().items():
                pts = (np.asarray(c) * [sx, sy]).astype(np.int32)
                cv2.polylines(small, [pts.reshape(-1, 1, 2)], True, (255, 255, 0), 2)
                cv2.putText(small, f"ID{mid}", (int(pts[:, 0].max()) + 3, int(pts[:, 1].mean())),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)
        rgb = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        # Reuse the Tk image while the size is unchanged: paste() is several
        # times cheaper than building a new PhotoImage every frame, and this
        # runs on the GUI thread (a slow redraw makes the buttons lag).
        if self._photo is not None and (self._photo.width(), self._photo.height()) == (tw, th):
            self._photo.paste(rgb)
        else:
            self._photo = ImageTk.PhotoImage(rgb)
            self.video.configure(image=self._photo, text="")

    def _tick_panels(self) -> None:
        if self._closed:
            return
        try:
            self.refresh(self.app.status())
        finally:
            self.root.after(self.PANEL_MS, self._tick_panels)

    def refresh(self, st: Any) -> None:
        snap = st.protocol
        if st.session_id != self._session_id:  # started, or restarted as a new session
            self._session_id = st.session_id
            self._t0, self._last_event_count, self._last_steps = None, -1, None
        self.title_lbl.configure(text=f"{snap['title']}    |    {st.session_id}")
        self.progress_lbl.configure(text=progress_text(snap))
        self.hands_lbl.configure(text=activity_text(getattr(st, "activity", ""), getattr(st, "hand_cues", []) or [],
                                                    object_names(snap), getattr(st, "gloved_hands", 0)))
        net = offline_badge()
        if net is None:
            self.badges["net"].pack_forget()
        else:
            self._badge("net", *net)
        earth = earth_badge(st)
        if earth is None:
            self.badges["earth"].pack_forget()
        else:
            self._badge("earth", *earth)
        self._badge("mode", "QUIET" if snap["mode"] == "quiet" else "VOICE", PANEL_2)
        self._badge("paused", "PAUSED" if snap["paused"] else "RUNNING", WARN if snap["paused"] else OK)
        self._badge("mic", *mic_badge(st))
        self._badge("det", *det_badge(st))
        self._badge("rack", *rack_badge(st))
        att = attend_badge(snap)
        if att is None:
            self.badges["attend"].pack_forget()
        else:
            if not self.badges["attend"].winfo_ismapped():
                self.badges["attend"].pack(side="right", padx=4, pady=8, before=self.badges["paused"])
            self._badge("attend", *att)
        self._badge("rec", f"● REC  {st.capture_fps:4.1f} fps" if st.recording else "REC off",
                    BAD if st.recording else PANEL_2)
        self._badge("stream", f"STREAM {st.stream_url.split('?')[0]}" if st.stream_url else "STREAM off",
                    PANEL_2)
        self.pause_btn.configure(
            text="▶  Resume  [Space]" if snap["paused"] else "⏸  Pause  [Space]",
            bg=WARN if snap["paused"] else PANEL_2, fg=BG if snap["paused"] else FG)
        self.mode_btn.configure(text="Voice mode  [Q]" if snap["mode"] == "quiet" else "Quiet mode  [Q]")
        self.now_lbl.configure(text=current_step_text(snap),
                               fg=WARN if snap["paused"] else FG)
        self.spoken_lbl.configure(
            text=f"last announced: \"{st.recent_speech[-1]['text']}\"" if st.recent_speech else "")
        pending = getattr(self.app, "restart_pending", None)
        if pending is not None and pending():
            self.warn_lbl.configure(text="Restart asked by voice - say it again to confirm", fg=BAD)
        else:
            self.warn_lbl.configure(text=st.warnings[-1].splitlines()[0][:110] if st.warnings else "",
                                    fg=WARN)

        lines = step_lines(snap)
        key = tuple((ln.glyph, ln.text, ln.colour, ln.is_current) for ln in lines)
        if key != self._last_steps:
            self._last_steps = key
            t = self.steps_txt
            t.configure(state="normal")
            t.delete("1.0", "end")
            current_line = None
            for n, ln in enumerate(lines, 1):
                tags = (ln.colour, "step", "current") if ln.is_current else (ln.colour, "step")
                t.insert("end", f" {ln.glyph}  {ln.text}\n", tags)
                if ln.is_current and current_line is None:
                    current_line = n
            t.configure(state="disabled")
            # long protocols don't fit: keep the step due now in view
            t.see(f"{current_line or len(lines)}.0")

        if st.recent_events and self._t0 is None:
            self._t0 = st.recent_events[0]["ts"]
        if len(st.recent_events) != self._last_event_count or (
            st.recent_events and self._last_event_count == len(st.recent_events) == 50
        ):
            self._last_event_count = len(st.recent_events)
            t = self.events_txt
            names = {s["id"]: (f"{s['object']}: " if s.get("object") else "") + s["prompt"]
                     for s in snap.get("steps", [])}
            t.configure(state="normal")
            t.delete("1.0", "end")
            for e in st.recent_events:
                line = event_line(e, self._t0, names)
                if line is not None:
                    t.insert("end", line[0] + "\n", (line[1], "event"))
            t.see("end")
            t.configure(state="disabled")

    def _badge(self, key: str, text: str, bg: str) -> None:
        self.badges[key].configure(text=text, bg=bg, fg=BG if bg in (OK, WARN, BAD, ACCENT) else FG)


class RackDialog:
    """Rack setup: which ArUco markers are on the rig (type, IDs, printed
    size) and the layout calibration from the live camera. Saved to
    configs/rack.yaml and applied live -- no restart."""

    CALIBRATE_MS = 4000

    def __init__(self, root: tk.Tk, app: Any) -> None:
        from src.perception.rack import ARUCO_DICTIONARIES

        self.app = app
        self.cfg = app.rack_config()
        self.calibrated_now = False  # a calibration in this window, not yet saved
        self.win = tk.Toplevel(root, bg=PANEL)
        self.win.title("Rack setup - ArUco markers")
        self.win.transient(root)
        pad = {"padx": 10, "pady": 4}

        def row(r: int, label: str, widget: tk.Widget, hint: str) -> None:
            tk.Label(self.win, text=label, bg=PANEL, fg=FG, font=FONT_BOLD, anchor="w").grid(
                row=r, column=0, sticky="w", **pad)
            widget.grid(row=r, column=1, sticky="we", **pad)
            tk.Label(self.win, text=hint, bg=PANEL, fg=MUTED, font=FONT, anchor="w").grid(
                row=r, column=2, sticky="w", **pad)

        self.dict_var = tk.StringVar(value=self.cfg.dictionary)
        menu = tk.OptionMenu(self.win, self.dict_var, *ARUCO_DICTIONARIES)
        menu.configure(bg=PANEL_2, fg=FG, activebackground=ACCENT, relief="flat", font=FONT,
                       highlightthickness=0)
        row(0, "ArUco type", menu, "not sure? use Auto-detect")
        self.size_var = tk.StringVar(value=f"{self.cfg.marker_size_mm:g}")
        row(1, "Marker size (mm)", self._entry(self.size_var), "black border edge to edge")
        self.ids_var = tk.StringVar(value=",".join(str(i) for i in self.cfg.marker_ids))
        row(2, "Marker IDs", self._entry(self.ids_var), "e.g. 1,2,3,4")

        btns = tk.Frame(self.win, bg=PANEL)
        btns.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        for text, cmd in (("Auto-detect from camera", self._autodetect),
                          ("Calibrate layout (4 s)", self._calibrate),
                          ("Save & apply", self._save),
                          ("Close", self.win.destroy)):
            tk.Button(btns, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      relief="flat", font=FONT_BOLD, padx=10, pady=4).pack(side="left", padx=(0, 6))
        self.live_lbl = tk.Label(self.win, text="", bg=PANEL, fg=MUTED, font=FONT_MONO, anchor="w")
        self.live_lbl.grid(row=4, column=0, columnspan=3, sticky="we", **pad)
        self.msg = tk.Label(self.win, text=layout_text(self.cfg), bg=PANEL, fg=FG, font=FONT,
                            anchor="w", justify="left", wraplength=620)
        self.msg.grid(row=5, column=0, columnspan=3, sticky="we", padx=10, pady=(4, 10))
        self._tick()

    def _entry(self, var: tk.StringVar) -> tk.Entry:
        return tk.Entry(self.win, textvariable=var, bg=PANEL_2, fg=FG, insertbackground=FG,
                        relief="flat", font=FONT, width=18)

    def _say(self, text: str, colour: str = FG) -> None:
        self.msg.configure(text=text, fg=colour)

    def _tick(self) -> None:
        if not self.win.winfo_exists():
            return
        seen = sorted(self.app.latest_rack_markers())
        self.live_lbl.configure(
            text=f"camera now: markers {seen or 'none'}   rack status: {self.app.status().rack_status}")
        self.win.after(300, self._tick)

    def _form_config(self) -> tuple[Any, str] | None:
        """Form -> (config, note), or None after showing the error."""
        from src.perception.rack import edit_config

        try:
            form = parse_rack_form(self.dict_var.get(), self.size_var.get(), self.ids_var.get())
        except ValueError as exc:
            self._say(str(exc), BAD)
            return None
        return edit_config(self.cfg, *form)

    def _autodetect(self) -> None:
        hits = self.app.autodetect_markers()
        if not hits:
            self._say("No ArUco markers found in the current camera frame (tried every type). "
                      "Are they in view and not covered?", BAD)
            return
        name, ids = hits[0]
        self.dict_var.set(name)
        self.ids_var.set(",".join(str(i) for i in ids))
        self._say(f"Found {name}, IDs {ids}. Check the size, then Calibrate and Save.", OK)

    def _calibrate(self) -> None:
        got = self._form_config()
        if got is None:
            return
        cfg, _ = got
        live = self.app.rack_config()
        if (cfg.dictionary, cfg.marker_ids) != (live.dictionary, live.marker_ids):
            # the live tracker must look for THESE markers while we collect
            err = self.app.apply_rack_config(cfg, save=False)
            if err:
                self._say(err, BAD)
                return
        sink = self.app.start_rack_calibration()
        self._say("Calibrating: keep the camera still and hands out of the tub for 4 s...", ACCENT)
        self.win.after(self.CALIBRATE_MS, lambda: self._finish(sink, cfg))

    def _finish(self, sink: list, cfg: Any) -> None:
        new, report = self.app.finish_rack_calibration(sink, cfg)
        if new is None:
            self._say("Calibration failed: " + report, BAD)
            return
        self.cfg, self.calibrated_now = new, True
        self._say(f"Calibrated: {report}.  Press Save & apply to keep it.\n{layout_text(new)}", OK)

    def _save(self) -> None:
        got = self._form_config()
        if got is None:
            return
        cfg, note = got
        err = self.app.apply_rack_config(
            cfg, save=True, note="calibrated from the live camera (GUI)" if self.calibrated_now else None)
        if err:
            self._say("Not saved: " + err, BAD)
            return
        self.cfg, self.calibrated_now = cfg, False
        self._say("Saved to configs/rack.yaml and applied." + (f"  ({note})" if note else "")
                  + "\n" + layout_text(cfg), OK)


def parse_rack_form(dictionary: str, size_text: str, ids_text: str) -> tuple[str, float, tuple[int, ...]]:
    """Rack dialog fields -> (dictionary, size mm, ids). ValueError with a
    message the operator can act on."""
    from src.perception.rack import ARUCO_DICTIONARIES, parse_ids

    if dictionary not in ARUCO_DICTIONARIES:
        raise ValueError(f"unknown ArUco type {dictionary!r}")
    try:
        size = float(size_text.strip().lower().removesuffix("mm"))
    except ValueError:
        raise ValueError("Marker size must be a number of millimetres, e.g. 49") from None
    if not size > 0:
        raise ValueError("Marker size must be > 0 mm")
    return dictionary, size, parse_ids(ids_text)


def layout_text(cfg: Any) -> str:
    if not cfg.layout:
        return "Layout: not calibrated -- the co-pilot runs in image space. Press Calibrate."
    return "Layout (mm, lowest ID at origin):  " + "   ".join(
        f"ID{i} ({p.x_mm:.0f}, {p.y_mm:.0f})" for i, p in sorted(cfg.layout.items()))
