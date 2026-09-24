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
        suffix = f"   ({label})" if label and s["status"] not in ("pending", "open") else ""
        # Prompts repeat across objects ("Unseal the module." for both
        # modules), so name the object, exactly as the voice does.
        obj = f"{s['object']}:  " if s.get("object") else ""
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
        s["status"] in ("done", "confirmed", "missed", "not_applicable") for s in snapshot["steps"]
    ):
        return "Experiment complete."
    return "Waiting..."


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


def event_line(e: dict[str, Any], t0: float | None) -> tuple[str, str] | None:
    """(text, colour) for the event feed, or None for internal noise."""
    rel = "" if t0 is None else f"{e['ts'] - t0:7.1f}s  "
    kind = e["type"]
    if kind == "violation":
        return (f"{rel}{(e.get('severity') or '').upper():8s} {e.get('code')}  "
                f"{e.get('target') or ''}", SEVERITY_COLOUR.get(e.get("severity") or "", WARN))
    if kind == "anomaly":
        return (f"{rel}ANOMALY  {e.get('message') or ''}", WARN)
    if kind == "step_complete":
        how = "  (operator)" if e.get("status") == "operator_confirmed" else ""
        return (f"{rel}done     {e.get('step')}{how}", OK)
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

class CopilotGUI:
    VIDEO_MS = 66  # ~15 fps display; the recording is independent of this
    PANEL_MS = 250

    def __init__(self, root: tk.Tk, app: Any) -> None:
        self.root = root
        self.app = app
        self._photo: Any = None
        self._last_steps: tuple | None = None
        self._last_event_count = -1
        self._t0: float | None = None
        self._closed = False

        root.title("BAS Co-Pilot")
        root.configure(bg=BG)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = int(sw * 0.9), int(sh * 0.86)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        root.minsize(min(1000, sw), min(620, sh))
        self._build()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._tick_video()
        self._tick_panels()

    # --- layout --------------------------------------------------------------

    def _build(self) -> None:
        r = self.root
        header = tk.Frame(r, bg=PANEL, height=44)
        header.pack(side="top", fill="x")
        self.title_lbl = tk.Label(header, text="", bg=PANEL, fg=FG, font=FONT_BOLD)
        self.title_lbl.pack(side="left", padx=12, pady=8)
        self.badges: dict[str, tk.Label] = {}
        for key in ("stream", "rec", "mic", "paused", "mode"):
            lbl = tk.Label(header, text="", bg=PANEL_2, fg=FG, font=FONT_BOLD, padx=8, pady=2)
            lbl.pack(side="right", padx=4, pady=8)
            self.badges[key] = lbl

        body = tk.Frame(r, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=PANEL, width=430)
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
                                  wrap="none", cursor="arrow", highlightthickness=0)
        self.events_txt.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))
        for colour in {OK, CONFIRMED, BAD, WARN, ACCENT, MUTED, FG}:
            self.steps_txt.tag_configure(colour, foreground=colour)
            self.events_txt.tag_configure(colour, foreground=colour)
        self.steps_txt.tag_configure("current", font=FONT_BOLD, background=PANEL_2)
        # hanging indent: a wrapped step lines up under its text, not the glyph
        self.steps_txt.tag_configure("step", lmargin1=4, lmargin2=30, spacing1=2)

        controls = tk.Frame(r, bg=BG)
        controls.pack(side="bottom", fill="x", padx=10, pady=10, before=body)
        self.pause_btn = self._button(controls, "Pause  [Space]", self._toggle_pause)
        self._button(controls, "Next step  [N]", lambda: self.app.command("next"))
        self._button(controls, "Repeat  [R]", lambda: self.app.command("repeat"))
        self.mode_btn = self._button(controls, "Quiet mode  [Q]", self._toggle_mode)
        self._button(controls, "Reload protocol  [F5]", self.app.reload_protocol)
        self.warn_lbl = tk.Label(controls, text="", bg=BG, fg=WARN, font=FONT, anchor="e")
        self.warn_lbl.pack(side="right", fill="x", expand=True)

    def _button(self, parent: tk.Widget, text: str, cmd: Any) -> tk.Button:
        b = tk.Button(parent, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      activeforeground=BG, relief="flat", font=FONT_BOLD, padx=12, pady=6,
                      cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    def _bind_keys(self) -> None:
        self.root.bind("<space>", lambda _e: self._toggle_pause())
        self.root.bind("<n>", lambda _e: self.app.command("next"))
        self.root.bind("<r>", lambda _e: self.app.command("repeat"))
        self.root.bind("<q>", lambda _e: self._toggle_mode())
        self.root.bind("<F5>", lambda _e: self.app.reload_protocol())

    # --- actions ----------------------------------------------------------------

    def _toggle_pause(self) -> None:
        self.app.command("resume" if self.app.status().protocol["paused"] else "pause")

    def _toggle_mode(self) -> None:
        self.app.command("voice" if self.app.status().protocol["mode"] == "quiet" else "quiet")

    def close(self) -> None:
        self._closed = True
        self.root.destroy()

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
        rgb = cv2.cvtColor(cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
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
        self.title_lbl.configure(text=f"{snap['title']}    |    {st.session_id}")
        self._badge("mode", "QUIET" if snap["mode"] == "quiet" else "VOICE", PANEL_2)
        self._badge("paused", "PAUSED" if snap["paused"] else "RUNNING", WARN if snap["paused"] else OK)
        self._badge("mic", *mic_badge(st))
        self._badge("rec", f"● REC  {st.capture_fps:4.1f} fps" if st.recording else "REC off",
                    BAD if st.recording else PANEL_2)
        self._badge("stream", f"STREAM {st.stream_url.split('?')[0]}" if st.stream_url else "STREAM off",
                    PANEL_2)
        self.pause_btn.configure(text="Resume  [Space]" if snap["paused"] else "Pause  [Space]")
        self.mode_btn.configure(text="Voice mode  [Q]" if snap["mode"] == "quiet" else "Quiet mode  [Q]")
        self.now_lbl.configure(text=current_step_text(snap),
                               fg=WARN if snap["paused"] else FG)
        if st.recent_speech:
            self.spoken_lbl.configure(text=f"last announced: \"{st.recent_speech[-1]['text']}\"")
        self.warn_lbl.configure(text=st.warnings[-1].splitlines()[0][:110] if st.warnings else "")

        lines = step_lines(snap)
        key = tuple((ln.glyph, ln.text, ln.colour, ln.is_current) for ln in lines)
        if key != self._last_steps:
            self._last_steps = key
            t = self.steps_txt
            t.configure(state="normal")
            t.delete("1.0", "end")
            for ln in lines:
                tags = (ln.colour, "step", "current") if ln.is_current else (ln.colour, "step")
                t.insert("end", f" {ln.glyph}  {ln.text}\n", tags)
            t.configure(state="disabled")

        if st.recent_events and self._t0 is None:
            self._t0 = st.recent_events[0]["ts"]
        if len(st.recent_events) != self._last_event_count or (
            st.recent_events and self._last_event_count == len(st.recent_events) == 50
        ):
            self._last_event_count = len(st.recent_events)
            t = self.events_txt
            t.configure(state="normal")
            t.delete("1.0", "end")
            for e in st.recent_events:
                line = event_line(e, self._t0)
                if line is not None:
                    t.insert("end", line[0] + "\n", (line[1],))
            t.see("end")
            t.configure(state="disabled")

    def _badge(self, key: str, text: str, bg: str) -> None:
        self.badges[key].configure(text=text, bg=bg, fg=BG if bg in (OK, WARN, BAD, ACCENT) else FG)
