"""Start screen: choose the experiment, the props on the rig and the
camera, then start. Also the way in to writing a new experiment.

Before this, the co-pilot started straight into whatever protocol
configs/runtime.yaml named, and a new experiment could only be made from
inside a running session. Now one window answers, in order: which
experiment, which props, which camera -- and a protocol that would fail
at startup (validator findings, placeholder prompts) is shown with its
problems and cannot be started.

The dashboard builds nothing heavy: it returns a StartChoice and the
caller (scripts/run_gui.py) builds the CopilotApp, so the resolved
constraint set is still printed at startup exactly as before.

List/validation helpers are pure functions, unit-testable without a
display.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

import yaml

from src.protocol.loader import DEFAULT_DEFAULTS_PATH, REPO_ROOT
from src.runtime.gui import ACCENT, BAD, BG, FG, FONT, FONT_BIG, FONT_BOLD, MUTED, OK, PANEL, PANEL_2, WARN

PROTOCOL_DIR = REPO_ROOT / "configs" / "protocols"
PROFILE_DIR = REPO_ROOT / "configs" / "objects"
# the editor's scratch files; never experiments
SCRATCH_SUFFIXES = (".editing.json", ".saving.json")

# What the operator sees for each prop profile. Anything else found in
# configs/objects/ is listed by its own description.
PROFILE_LABELS = {
    "profile_jar.yaml": "Jars with screw caps (red + yellow)",
    "profile_rect.yaml": "Slabs, no lids (red + yellow)",
    "profile_mixed.yaml": "Mixed: red jar with cap + yellow slab",
}
HIDDEN_PROFILES = {"profile_repeatable_test.yaml"}  # synthetic, not a real rig


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------

@dataclass
class ExperimentInfo:
    path: Path
    protocol_id: str
    title: str
    description: str = ""
    steps: list[str] = field(default_factory=list)  # prompts in protocol order
    problems: list[str] = field(default_factory=list)
    reference: bool = False  # the harness is built on it: never edited in place

    @property
    def ready(self) -> bool:
        return not self.problems


def experiment_info(path: Path, defaults_path: Path = DEFAULT_DEFAULTS_PATH,
                    object_profile: str | None = None) -> ExperimentInfo:
    """One protocol file -> what the dashboard shows. Problems = the real
    validator's findings plus unfinished (placeholder) prompts, i.e.
    exactly what would stop it at startup or be spoken wrongly."""
    import json

    from scripts.validate_protocol import validate
    from src.protocol.editing import PLACEHOLDER_PROMPT, flatten
    from src.runtime.protocol_editor_gui import REFERENCE_PROTOCOLS

    path = Path(path)
    info = ExperimentInfo(path=path, protocol_id=path.stem, title=path.stem,
                          reference=path.name in REFERENCE_PROTOCOLS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        info.problems = [f"cannot read: {exc}"]
        return info
    info.protocol_id = str(raw.get("protocol_id", path.stem))
    info.title = str(raw.get("title") or info.protocol_id)
    info.description = str(raw.get("description") or "")
    try:
        rows = flatten(raw)
        info.steps = [r.prompt or r.id for r in rows if r.kind == "step"]
        info.problems += [f"step '{r.id}' still has the placeholder prompt"
                          for r in rows if r.kind == "step" and r.prompt.strip() == PLACEHOLDER_PROMPT]
    except (KeyError, ValueError, TypeError):
        pass  # the validator reports the structure
    info.problems += [str(f).strip() for f in validate(path, defaults_path, object_profile)]
    return info


def list_experiments(folder: Path = PROTOCOL_DIR, defaults_path: Path = DEFAULT_DEFAULTS_PATH,
                     object_profile: str | None = None) -> list[ExperimentInfo]:
    """Every protocol in the folder, ready ones first, reference first."""
    paths = [p for p in sorted(Path(folder).glob("*.json"))
             if not p.name.endswith(SCRATCH_SUFFIXES) and not _test_only(p)]
    infos = [experiment_info(p, defaults_path, object_profile) for p in paths]
    return sorted(infos, key=lambda i: (not i.ready, not i.reference, i.title.lower()))


def _test_only(path: Path) -> bool:
    """Harness-only protocols (bound to a synthetic prop profile)."""
    import json

    try:
        ref = str(json.loads(path.read_text(encoding="utf-8")).get("object_profile") or "")
    except (OSError, ValueError, AttributeError):
        return False
    return Path(ref).name in HIDDEN_PROFILES


def display_names(infos: list[ExperimentInfo]) -> list[str]:
    """Titles, plus the file name where two experiments share a title (a
    copy keeps its original's title until renamed)."""
    from collections import Counter

    n = Counter(i.title for i in infos)
    return [f"{i.title}   ({i.path.stem})" if n[i.title] > 1 else i.title for i in infos]


def list_profiles(folder: Path = PROFILE_DIR) -> list[tuple[str, str | None]]:
    """(label, profile path relative to the repo) -- first entry = the
    protocol's own profile (None)."""
    out: list[tuple[str, str | None]] = [("As the experiment specifies", None)]
    for p in sorted(Path(folder).glob("profile_*.yaml")):
        if p.name in HIDDEN_PROFILES:
            continue
        label = PROFILE_LABELS.get(p.name)
        if label is None:
            try:
                label = str((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("description") or p.stem)
            except (OSError, yaml.YAMLError):
                label = p.stem
        out.append((label, p.relative_to(REPO_ROOT).as_posix() if p.is_relative_to(REPO_ROOT) else str(p)))
    return out


def parse_source(text: str) -> int | str | None:
    """Camera field -> capture source: '' = runtime.yaml default, digits =
    camera index, anything else = file path or stream URL."""
    t = text.strip()
    if not t:
        return None
    first = t.split()[0]
    if first.isdigit():
        return int(first)
    return t


@dataclass
class StartChoice:
    protocol: Path
    object_profile: str | None
    source: int | str | None
    voice_control: bool = True
    record: bool = True
    perception: bool = True
    downlink: str | None = None  # ground station "ip[:port]", None = no Earth link
    link_delay_s: float | None = None  # simulated light-time


# ----------------------------------------------------------------------
# Offline host for the protocol editor (no session running yet)
# ----------------------------------------------------------------------

class EditorHost:
    """What ProtocolEditor needs from the app, without a session: it saves
    through the validator itself; 'applying' here only means the file
    resolves, so the dashboard can select it afterwards."""

    def __init__(self, protocol_path: Path, object_profile: str | None) -> None:
        from src.runtime.app import load_validated

        self.protocol_path = Path(protocol_path)
        self.defaults_path = DEFAULT_DEFAULTS_PATH
        self.object_profile = object_profile
        self.resolved = load_validated(self.protocol_path, self.defaults_path, object_profile)
        self.saved: Path | None = None

    def use_protocol(self, path: Path) -> bool:
        from src.runtime.app import load_validated

        try:
            self.resolved = load_validated(Path(path), self.defaults_path, self.object_profile)
        except Exception:  # noqa: BLE001 -- validator findings are shown by the editor
            return False
        self.protocol_path = self.saved = Path(path)
        return True


# ----------------------------------------------------------------------
# Window
# ----------------------------------------------------------------------

class Dashboard:
    """Lives in its own frame inside `root`; calls on_start(choice) when the
    operator presses Start (the caller destroys the dashboard)."""

    def __init__(self, root: tk.Tk, cfg: dict[str, Any], on_start: Callable[[StartChoice], None],
                 last_summary: dict[str, Any] | None = None,
                 source: int | str | None = None, object_profile: str | None = None,
                 downlink: str | None = None, role: str = "space",
                 on_receive: Callable[[int], None] | None = None) -> None:
        """source / object_profile: command-line --source / --profile. They
        prefill the setup fields and win over configs/runtime.yaml, so
        `run_gui.py --source http://<phone>:4747/video` still means the phone."""
        self.root = root
        self.cfg = cfg
        self.on_start = on_start
        self._cli_source = source
        self._cli_profile = object_profile
        self._cli_downlink = downlink
        # Which end of the link this PC is: "space" runs the experiment and
        # sends; "earth" receives (Mission Control). on_receive(port) starts it.
        self.role = role if role in ("space", "earth") else "space"
        self.on_receive = on_receive
        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill="both", expand=True)
        self.infos: list[ExperimentInfo] = []
        self.profiles = list_profiles()
        if object_profile and object_profile not in [p for _, p in self.profiles]:
            self.profiles.append((object_profile, object_profile))  # a profile outside the list
        sess = cfg.get("session") or {}
        self._default_protocol = (REPO_ROOT / sess.get("protocol", "")).resolve()
        self._build(last_summary)
        self.refresh()
        self.set_role(self.role)

    # --- layout ------------------------------------------------------------

    def _build(self, last_summary: dict[str, Any] | None) -> None:
        f = self.frame
        head = tk.Frame(f, bg=PANEL)
        head.pack(side="top", fill="x")
        tk.Label(head, text="BAS Co-Pilot", bg=PANEL, fg=FG, font=FONT_BIG).pack(side="left", padx=16, pady=10)
        self.steps_hint = tk.Label(head, text="", bg=PANEL, fg=MUTED, font=FONT_BOLD)
        self.steps_hint.pack(side="left", padx=20)
        # role switch: which end of the space-to-Earth link this PC is
        # packed right-to-left: reads "This PC is: [SPACE STATION] [EARTH]"
        self.role_btns: dict[str, tk.Button] = {}
        for key, text in (("earth", "🌍  EARTH  (receiver)"), ("space", "🛰  SPACE STATION  (sender)")):
            b = tk.Button(head, text=text, command=lambda k=key: self.set_role(k), relief="flat",
                          font=FONT_BOLD, padx=14, pady=6, cursor="hand2")
            b.pack(side="right", padx=(4, 16 if key == "earth" else 4), pady=8)
            self.role_btns[key] = b
        tk.Label(head, text="This PC is:", bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(side="right", padx=(0, 6))

        self.space_view = tk.Frame(f, bg=BG)
        self.earth_view = tk.Frame(f, bg=BG)
        self._build_earth(self.earth_view)
        f = self.space_view

        if last_summary:
            row = tk.Frame(f, bg=PANEL_2)
            row.pack(side="top", fill="x", padx=16, pady=(10, 0))
            tk.Label(row, text=summary_text(last_summary), bg=PANEL_2, fg=FG, font=FONT, anchor="w",
                     justify="left", padx=12, pady=8).pack(side="left", fill="x", expand=True)
            report = last_summary.get("report")
            if report:
                self._button(row, "Open report", lambda: _open_path(Path(report))).pack_configure(
                    side="right", padx=8, pady=6)
            if last_summary.get("log"):
                self._button(row, "Logs folder", lambda: _open_path(Path(last_summary["log"]).parent)
                             ).pack_configure(side="right", pady=6)

        body = tk.Frame(f, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=16, pady=10)

        # left: experiments | past sessions
        style = ttk.Style(self.root)
        style.configure("Dash.TNotebook", background=BG, borderwidth=0)
        style.configure("Dash.TNotebook.Tab", font=FONT_BOLD, padding=(14, 6))
        tabs = ttk.Notebook(body, style="Dash.TNotebook")
        tabs.pack(side="left", fill="both", expand=True)
        left = tk.Frame(tabs, bg=PANEL)
        sessions_tab = tk.Frame(tabs, bg=PANEL)
        tabs.add(left, text="  Experiments  ")
        tabs.add(sessions_tab, text="  Sessions (this station)  ")
        self.local_sessions = SessionsTable(sessions_tab, self._local_rows, earth=False,
                                            earth_target=lambda: self.link_target.get().strip())
        tabs.bind("<<NotebookTabChanged>>", lambda _e: self.local_sessions.refresh())
        style.configure("Dash.Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=FG,
                        rowheight=30, font=FONT)
        style.configure("Dash.Treeview.Heading", font=FONT_BOLD)
        style.map("Dash.Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])
        self.tree = ttk.Treeview(left, columns=("steps", "status"), show="tree headings",
                                 selectmode="browse", style="Dash.Treeview")
        self.tree.heading("#0", text="experiment")
        self.tree.heading("steps", text="steps")
        self.tree.heading("status", text="status")
        self.tree.column("#0", width=380)
        self.tree.column("steps", width=60, anchor="center", stretch=False)
        self.tree.column("status", width=230, stretch=False)
        self.tree.tag_configure("problem", foreground=BAD)
        self.tree.pack(side="top", fill="both", expand=True, padx=10)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())
        self.tree.bind("<Double-1>", lambda _e: self.start())
        btns = tk.Frame(left, bg=PANEL)
        btns.pack(side="top", fill="x", padx=10, pady=10)
        self._button(btns, "New experiment...", self.new_experiment)
        self.edit_btn = self._button(btns, "Edit...", self.edit_experiment)
        self._button(btns, "Refresh", self.refresh)

        # right: details + setup + start
        right = tk.Frame(body, bg=PANEL, width=640)
        right.pack(side="right", fill="both", padx=(12, 0))
        right.pack_propagate(False)
        tk.Label(right, text="SELECTED", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").pack(
            side="top", fill="x", padx=12, pady=(10, 2))
        self.detail = tk.Text(right, bg=PANEL, fg=FG, font=FONT, relief="flat", wrap="word", height=12,
                              highlightthickness=0, cursor="arrow")
        self.detail.pack(side="top", fill="both", expand=True, padx=10)
        for c in (OK, BAD, WARN, MUTED, FG):
            self.detail.tag_configure(c, foreground=c)
        self.detail.tag_configure("title", font=FONT_BOLD)

        setup = tk.Frame(right, bg=PANEL)
        setup.pack(side="top", fill="x", padx=10, pady=(8, 0))
        tk.Label(setup, text="SETUP", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        tk.Label(setup, text="Props on the rig", bg=PANEL, fg=FG, font=FONT_BOLD).grid(row=1, column=0, sticky="w")
        self.profile_var = tk.StringVar(value=self._default_profile_label())
        props = ttk.Combobox(setup, textvariable=self.profile_var, values=[lbl for lbl, _ in self.profiles],
                             state="readonly", width=38)
        props.grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=3)
        # other props can make a protocol invalid (unbound roles): re-check
        props.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        tk.Label(setup, text="Camera", bg=PANEL, fg=FG, font=FONT_BOLD).grid(row=2, column=0, sticky="w")
        src = self._cli_source if self._cli_source is not None else (
            (self.cfg.get("capture") or {}).get("source", 0))
        self.source_var = tk.StringVar(value=f"{src}  (webcam)" if isinstance(src, int) else str(src))
        ttk.Combobox(setup, textvariable=self.source_var, width=30,
                     values=["0  (webcam)", "1  (second camera)", "http://PHONE-IP:4747/video"]).grid(
            row=2, column=1, sticky="we", padx=6, pady=3)
        self._button(setup, "Video file...", self._pick_video, pack=False).grid(row=2, column=2, sticky="w")
        cam = tk.Frame(setup, bg=PANEL)
        cam.grid(row=3, column=1, columnspan=2, sticky="we", padx=6, pady=(2, 0))
        cam_btns = tk.Frame(cam, bg=PANEL)
        cam_btns.pack(side="top", fill="x")
        self._button(cam_btns, "IP camera...", self._ip_camera)
        self._button(cam_btns, "Test camera", self._test_camera)
        self.cam_msg = tk.Label(cam, text="webcam number, IP camera (phone) or a video file", bg=PANEL, fg=MUTED,
                                font=FONT, anchor="w", justify="left", wraplength=480)
        self.cam_msg.pack(side="top", fill="x", pady=(2, 0))
        self.voice_var = tk.BooleanVar(value=bool((self.cfg.get("voice_control") or {}).get("enabled", True)))
        self.record_var = tk.BooleanVar(value=bool((self.cfg.get("recording") or {}).get("enabled", True)))
        self.detect_var = tk.BooleanVar(value=bool((self.cfg.get("perception") or {}).get("enabled", True)))
        opts = tk.Frame(setup, bg=PANEL)
        opts.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for text, var in (("Voice commands (\"Hey BAS\")", self.voice_var), ("Record video", self.record_var),
                          ("Watch with the camera (detector)", self.detect_var)):
            tk.Checkbutton(opts, text=text, variable=var, bg=PANEL, fg=FG, selectcolor=PANEL_2,
                           activebackground=PANEL, activeforeground=FG, font=FONT).pack(side="top", anchor="w")
        # Earth link: log + event images to a ground station (src/link/)
        dl = self.cfg.get("downlink") or {}
        target = self._cli_downlink or (f"{dl.get('host', '127.0.0.1')}:{dl.get('port', 5055)}")
        self.link_var = tk.BooleanVar(value=bool(self._cli_downlink or dl.get("enabled", False)))
        self.link_target = tk.StringVar(value=target)
        self.moon_var = tk.BooleanVar(value=float(dl.get("simulate_delay_s", 0) or 0) > 0)
        link = tk.Frame(setup, bg=PANEL)
        link.grid(row=5, column=0, columnspan=3, sticky="we", pady=(8, 0))
        tk.Checkbutton(link, text="Send to Earth - ground station at", variable=self.link_var, bg=PANEL, fg=FG,
                       selectcolor=PANEL_2, activebackground=PANEL, activeforeground=FG,
                       font=FONT).pack(side="left")
        tk.Entry(link, textvariable=self.link_target, bg=PANEL_2, fg=FG, insertbackground=FG, relief="flat",
                 font=FONT, width=18).pack(side="left", padx=6)
        link2 = tk.Frame(setup, bg=PANEL)
        link2.grid(row=6, column=0, columnspan=3, sticky="we")
        tk.Checkbutton(link2, text="simulate Moon light-time (1.3 s)", variable=self.moon_var, bg=PANEL, fg=FG,
                       selectcolor=PANEL_2, activebackground=PANEL, activeforeground=FG,
                       font=FONT).pack(side="left", padx=(24, 0))
        self._button(link2, "Start Mission Control", self._launch_ground).pack_configure(side="right", padx=0)
        tk.Label(setup, text="Sends the log + one image per step / alert, never video. "
                             "Run Mission Control on the ground PC (or this one).", bg=PANEL, fg=MUTED,
                 font=FONT, wraplength=520, justify="left").grid(row=7, column=0, columnspan=3, sticky="w",
                                                                 padx=(24, 0), pady=(2, 0))
        setup.columnconfigure(1, weight=1)

        self.start_btn = tk.Button(right, text="Start experiment  ▶", command=self.start, bg=OK, fg=BG,
                                   activebackground=ACCENT, relief="flat", font=FONT_BIG, pady=8,
                                   cursor="hand2")
        self.start_btn.pack(side="bottom", fill="x", padx=10, pady=10)
        self.msg = tk.Label(right, text="", bg=PANEL, fg=WARN, font=FONT, anchor="w", justify="left",
                            wraplength=490)
        self.msg.pack(side="bottom", fill="x", padx=12)

    # --- role: which end of the link this PC is ----------------------------

    def set_role(self, role: str) -> None:
        self.role = role
        for key, b in self.role_btns.items():
            on = key == role
            b.configure(bg=ACCENT if on else PANEL_2, fg=BG if on else FG,
                        activebackground=ACCENT, activeforeground=BG)
        if role == "earth":
            self.space_view.pack_forget()
            self.earth_view.pack(side="top", fill="both", expand=True)
            self.steps_hint.configure(text="1  Give the space station this PC's IP     2  Start receiving")
            self.ground_sessions.refresh()
        else:
            self.earth_view.pack_forget()
            self.space_view.pack(side="top", fill="both", expand=True)
            self.steps_hint.configure(text="1  Choose an experiment     2  Check the setup     3  Start")

    def _build_earth(self, v: tk.Frame) -> None:
        from src.link.ground_gui import local_ips

        dl = self.cfg.get("downlink") or {}
        card = tk.Frame(v, bg=PANEL)
        card.pack(side="top", fill="x", padx=16, pady=(12, 0))
        tk.Label(card, text="🌍  This PC is EARTH - Mission Control", bg=PANEL, fg=FG, font=FONT_BIG,
                 anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(card, text="It receives, live, everything the space station sends: the hash-chained log line by "
                            "line, one image per completed step and per alert, and the report at the end - "
                            "never raw video. Every line and every image is verified as it arrives.",
                 bg=PANEL, fg=MUTED, font=FONT, anchor="w", justify="left", wraplength=1100).pack(
            fill="x", padx=16)
        tk.Label(card, text='1   On the space station, tick "Send to Earth" and type:', bg=PANEL, fg=FG,
                 font=FONT_BOLD, anchor="w").pack(fill="x", padx=16, pady=(14, 4))
        self.port_var = tk.StringVar(value=str(dl.get("port", 5055)))
        self.ip_lbl = tk.Label(card, text="", bg=PANEL_2, fg=OK, font=FONT_BIG, anchor="w", padx=14, pady=8)
        self.ip_lbl.pack(fill="x", padx=16, pady=(0, 4))
        ips = local_ips()

        def show_ips(*_: Any) -> None:
            self.ip_lbl.configure(text="      or      ".join(f"{ip}:{self.port_var.get().strip()}" for ip in ips))

        self.port_var.trace_add("write", show_ips)
        show_ips()
        prow = tk.Frame(card, bg=PANEL)
        prow.pack(fill="x", padx=16, pady=(2, 4))
        tk.Label(prow, text="Port", bg=PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        tk.Entry(prow, textvariable=self.port_var, bg=PANEL_2, fg=FG, insertbackground=FG, relief="flat",
                 font=FONT, width=8).pack(side="left", padx=8)
        tk.Label(prow, text="Testing on one PC? The station types 127.0.0.1:" + str(dl.get("port", 5055))
                 + "   Windows may ask to allow Python through the firewall: allow it (private network).",
                 bg=PANEL, fg=MUTED, font=FONT).pack(side="left", padx=10)
        tk.Label(card, text="2   Start receiving, then start the experiment on the space station.", bg=PANEL,
                 fg=FG, font=FONT_BOLD, anchor="w").pack(fill="x", padx=16, pady=(10, 4))
        self.receive_btn = tk.Button(card, text="Start receiving  ▶", command=self._start_receiving, bg=OK, fg=BG,
                                     activebackground=ACCENT, relief="flat", font=FONT_BIG, pady=8,
                                     cursor="hand2")
        self.receive_btn.pack(fill="x", padx=16, pady=(0, 6))
        self.earth_msg = tk.Label(card, text="", bg=PANEL, fg=WARN, font=FONT, anchor="w")
        self.earth_msg.pack(fill="x", padx=16, pady=(0, 8))

        box = tk.Frame(v, bg=PANEL)
        box.pack(side="top", fill="both", expand=True, padx=16, pady=12)
        tk.Label(box, text="SESSIONS RECEIVED FROM THE STATION", bg=PANEL, fg=MUTED, font=FONT_BOLD,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        self.ground_sessions = SessionsTable(box, self._ground_rows, earth=True)

    def _start_receiving(self) -> None:
        try:
            port = int(self.port_var.get())
        except ValueError:
            self.earth_msg.configure(text="Port must be a number, e.g. 5055", fg=BAD)
            return
        if self.on_receive is None:
            self.earth_msg.configure(text="Receiving is not available here: run scripts/ground_station.py",
                                     fg=WARN)
            return
        self.on_receive(port)

    def _local_rows(self) -> list[dict[str, Any]]:
        from src.runtime.sessions import list_local_sessions

        return list_local_sessions(REPO_ROOT / ((self.cfg.get("session") or {}).get("log_dir", "logs")))

    def _ground_rows(self) -> list[dict[str, Any]]:
        from src.runtime.sessions import list_ground_sessions

        return list_ground_sessions(ground_archive_dir(self.cfg))

    def _launch_ground(self) -> None:
        """Mission Control on THIS PC (same-machine demo). On a second PC:
        python scripts/ground_station.py there."""
        import subprocess
        import sys

        script = REPO_ROOT / "scripts" / "run_gui.py"
        if getattr(sys, "frozen", False) or not script.is_file():
            self.msg.configure(text="Start Mission Control with: python scripts/ground_station.py", fg=WARN)
            return
        port = self.link_target.get().rpartition(":")[2] or "5055"
        subprocess.Popen([sys.executable, str(script), "--role", "earth", "--receive",
                          "--port", port if port.isdigit() else "5055"], cwd=str(REPO_ROOT))
        self.link_var.set(True)
        if not self.link_target.get().strip():
            self.link_target.set("127.0.0.1:5055")
        self.msg.configure(text="Mission Control started. The Earth link connects when the experiment starts.",
                           fg=OK)

    def _button(self, parent: tk.Widget, text: str, cmd: Any, pack: bool = True) -> tk.Button:
        b = tk.Button(parent, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      activeforeground=BG, relief="flat", font=FONT_BOLD, padx=12, pady=5, cursor="hand2")
        if pack:
            b.pack(side="left", padx=(0, 8))
        return b

    def _default_profile_label(self) -> str:
        want = self._cli_profile or (self.cfg.get("session") or {}).get("object_profile")
        for label, path in self.profiles:
            if path == want:
                return label
        return self.profiles[0][0]

    # --- data --------------------------------------------------------------

    def selected_profile(self) -> str | None:
        return dict(self.profiles).get(self.profile_var.get())

    def refresh(self, select: Path | None = None) -> None:
        cur = select or (self.selected().path if self.selected() else self._default_protocol)
        self.infos = list_experiments(object_profile=self.selected_profile())
        self.tree.delete(*self.tree.get_children())
        for i, (info, name) in enumerate(zip(self.infos, display_names(self.infos))):
            status = ("ready" if info.ready else f"{len(info.problems)} problem(s)") + (
                "  (reference)" if info.reference else "")
            self.tree.insert("", "end", iid=str(i), text=name, values=(len(info.steps), status),
                             tags=() if info.ready else ("problem",))
        pick = next((str(i) for i, x in enumerate(self.infos) if x.path.resolve() == Path(cur).resolve()),
                    "0" if self.infos else None)
        if pick is not None:
            self.tree.selection_set(pick)
            self.tree.see(pick)
        self._show_selected()

    def selected(self) -> ExperimentInfo | None:
        sel = self.tree.selection() if hasattr(self, "tree") else ()
        return self.infos[int(sel[0])] if sel and int(sel[0]) < len(self.infos) else None

    def _show_selected(self) -> None:
        info = self.selected()
        t = self.detail
        t.configure(state="normal")
        t.delete("1.0", "end")
        if info is None:
            t.insert("end", "No experiments found in configs/protocols/.", (MUTED,))
        else:
            t.insert("end", info.title + "\n", ("title",))
            t.insert("end", f"{info.path.name}\n", (MUTED,))
            if info.description:
                t.insert("end", info.description + "\n", (FG,))
            if info.problems:
                t.insert("end", "\nCannot start -- fix these in Edit:\n", (BAD,))
                for p in info.problems[:8]:
                    t.insert("end", f"  • {p}\n", (BAD,))
            t.insert("end", "\nSteps:\n", (MUTED,))
            for n, prompt in enumerate(info.steps, 1):
                t.insert("end", f"  {n:2d}. {prompt}\n", (FG,))
        t.configure(state="disabled")
        self.start_btn.configure(state="normal" if info is not None and info.ready else "disabled",
                                 bg=OK if info is not None and info.ready else PANEL_2)
        self.edit_btn.configure(text="Copy & edit..." if info is not None and info.reference else "Edit...")
        self.msg.configure(text="")

    def _pick_video(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Video file to run the co-pilot on",
                                          filetypes=[("Video", "*.mp4 *.avi *.mov *.mkv *.ts"), ("All", "*.*")])
        if path:
            self.source_var.set(path)

    # --- actions -----------------------------------------------------------

    # --- camera -------------------------------------------------------------

    def _ip_camera(self) -> None:
        IpCameraDialog(self.root, self.source_var, self.cam_msg)

    def _test_camera(self) -> None:
        import threading

        from src.runtime.camera_setup import probe_source

        src = parse_source(self.source_var.get())
        if src is None:
            src = (self.cfg.get("capture") or {}).get("source", 0)
        self.cam_msg.configure(text=f"testing {src} ...", fg=ACCENT)

        def work() -> None:
            res = probe_source(src)
            self.root.after(0, lambda: self.cam_msg.configure(text=res.message, fg=OK if res.ok else BAD))

        threading.Thread(target=work, daemon=True).start()

    def start(self) -> None:
        from src.runtime.camera_setup import check_local

        src = parse_source(self.source_var.get())
        if isinstance(src, str) and "://" in src:
            why = check_local(src)
            if why:
                self.msg.configure(text=f"Camera refused: {why}", fg=BAD)
                return
        info = self.selected()
        if info is None or not info.ready:
            self.msg.configure(text="Pick an experiment marked 'ready'.", fg=BAD)
            return
        self.on_start(StartChoice(
            protocol=info.path, object_profile=self.selected_profile(),
            source=parse_source(self.source_var.get()), voice_control=self.voice_var.get(),
            record=self.record_var.get(), perception=self.detect_var.get(),
            downlink=self.link_target.get().strip() or None if self.link_var.get() else None,
            link_delay_s=1.3 if (self.link_var.get() and self.moon_var.get()) else None))

    def new_experiment(self) -> None:
        base = self.selected()
        name = simpledialog.askstring(
            "New experiment", "Name for the new experiment (letters, digits, _):\n"
            f"It starts as a copy of \"{base.title if base else 'the reference experiment'}\".",
            parent=self.root)
        if name:
            self._copy_and_edit(base, name)

    def edit_experiment(self) -> None:
        info = self.selected()
        if info is None:
            return
        if info.reference:  # never edited in place: the harness is built on it
            name = simpledialog.askstring(
                "Copy the reference experiment",
                f"\"{info.title}\" is the reference experiment and is never changed.\n"
                "Name for your copy:", parent=self.root)
            if name:
                self._copy_and_edit(info, name)
            return
        self._open_editor(info.path)

    def _copy_and_edit(self, base: ExperimentInfo | None, name: str) -> None:
        import json
        import re

        name = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_")
        if not name:
            return
        src = base.path if base is not None else PROTOCOL_DIR / "bas_specimen_v1.json"
        dst = PROTOCOL_DIR / f"{name}.json"
        if dst.exists():
            messagebox.showerror("Name taken", f"{dst.name} already exists. Pick another name.", parent=self.root)
            return
        raw = json.loads(src.read_text(encoding="utf-8"))
        raw["protocol_id"] = name
        raw["title"] = name.replace("_", " ").capitalize()
        dst.write_text(json.dumps(raw, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        self.refresh(select=dst)
        self._open_editor(dst)

    def _open_editor(self, path: Path) -> None:
        from src.runtime.protocol_editor_gui import ProtocolEditor

        try:
            host = EditorHost(path, self.selected_profile())
        except Exception as exc:  # noqa: BLE001 -- unreadable/invalid: say why
            messagebox.showerror("Cannot open", f"{path.name} does not load:\n\n{exc}", parent=self.root)
            return
        ed = ProtocolEditor(self.root, host)

        def closed(e: Any) -> None:
            # the operator may have pressed Start meanwhile: dashboard gone
            if e.widget is ed.win and self.frame.winfo_exists():
                self.refresh(select=host.protocol_path)

        ed.win.bind("<Destroy>", closed)
        self._editor = ed

    def destroy(self) -> None:
        ed = getattr(self, "_editor", None)
        if ed is not None and ed.win.winfo_exists():
            ed.win.destroy()  # an editor bound to no session would linger over the session screen
        self.frame.destroy()


class IpCameraDialog:
    """Phone / network camera: pick the app, type its IP, test, use."""

    def __init__(self, root: tk.Misc, target: tk.StringVar, status: tk.Label) -> None:
        from src.runtime.camera_setup import PRESETS

        self.target, self.status = target, status
        self.win = tk.Toplevel(root, bg=PANEL)
        self.win.title("IP camera")
        self.win.transient(root)
        pad = {"padx": 10, "pady": 5}
        self.preset = tk.StringVar(value=next(iter(PRESETS)))
        self.ip = tk.StringVar()
        self.port = tk.StringVar()
        self.path = tk.StringVar()
        rows = (("Camera app / type", ttk.Combobox(self.win, textvariable=self.preset, values=list(PRESETS),
                                                   state="readonly", width=28)),
                ("Camera IP", self._entry(self.ip)), ("Port", self._entry(self.port)),
                ("Path", self._entry(self.path)))
        for r, (label, w) in enumerate(rows):
            tk.Label(self.win, text=label, bg=PANEL, fg=FG, font=FONT_BOLD, anchor="w").grid(
                row=r, column=0, sticky="w", **pad)
            w.grid(row=r, column=1, sticky="we", **pad)
        tk.Label(self.win, text="The phone app shows its IP, e.g. 192.168.1.23. Phone and this PC on the same "
                                "Wi-Fi / hotspot. Local network only: nothing goes to the internet.",
                 bg=PANEL, fg=MUTED, font=FONT, wraplength=440, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", **pad)
        self.url_lbl = tk.Label(self.win, text="", bg=PANEL_2, fg=FG, font=FONT_BOLD, anchor="w", padx=8, pady=4)
        self.url_lbl.grid(row=5, column=0, columnspan=2, sticky="we", **pad)
        btns = tk.Frame(self.win, bg=PANEL)
        btns.grid(row=6, column=0, columnspan=2, sticky="w", **pad)
        for text, cmd in (("Test", self._test), ("Use this camera", self._use), ("Close", self.win.destroy)):
            tk.Button(btns, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT, relief="flat",
                      font=FONT_BOLD, padx=12, pady=4).pack(side="left", padx=(0, 6))
        self.msg = tk.Label(self.win, text="", bg=PANEL, fg=MUTED, font=FONT, wraplength=440, justify="left")
        self.msg.grid(row=7, column=0, columnspan=2, sticky="w", **pad)
        self.preview = tk.Label(self.win, bg=PANEL)
        self.preview.grid(row=8, column=0, columnspan=2, **pad)
        for v in (self.preset, self.ip, self.port, self.path):
            v.trace_add("write", lambda *_: self._show_url())
        self.preset.trace_add("write", lambda *_: self._fill_defaults())
        self._fill_defaults()

    def _entry(self, var: tk.StringVar) -> tk.Entry:
        return tk.Entry(self.win, textvariable=var, bg=PANEL_2, fg=FG, insertbackground=FG, relief="flat",
                        font=FONT, width=30)

    def _fill_defaults(self) -> None:
        from src.runtime.camera_setup import PRESETS

        _, port, path = PRESETS[self.preset.get()]
        self.port.set(str(port))
        self.path.set(path)

    def _url(self) -> str | None:
        from src.runtime.camera_setup import build_camera_url, check_local

        try:
            url = build_camera_url(self.preset.get(), self.ip.get(), self.port.get(), self.path.get())
        except ValueError as exc:
            self.msg.configure(text=str(exc), fg=WARN)
            return None
        why = check_local(url)
        if why:
            self.msg.configure(text=why, fg=BAD)
            return None
        self.msg.configure(text="", fg=MUTED)
        return url

    def _show_url(self) -> None:
        url = self._url() if self.ip.get().strip() else None
        self.url_lbl.configure(text=url or "")

    def _test(self) -> None:
        import threading

        from src.runtime.camera_setup import probe_source

        url = self._url()
        if url is None:
            return
        self.msg.configure(text=f"connecting to {url} ...", fg=ACCENT)

        def work() -> None:
            res = probe_source(url)
            self.win.after(0, lambda: self._tested(res))

        threading.Thread(target=work, daemon=True).start()

    def _tested(self, res: Any) -> None:
        if not self.win.winfo_exists():
            return
        self.msg.configure(text=res.message, fg=OK if res.ok else BAD)
        if res.ok and res.frame is not None:
            import cv2
            from PIL import Image, ImageTk

            im = Image.fromarray(cv2.cvtColor(res.frame, cv2.COLOR_BGR2RGB))
            im.thumbnail((420, 240))
            self._photo = ImageTk.PhotoImage(im)
            self.preview.configure(image=self._photo)

    def _use(self) -> None:
        url = self._url()
        if url is None:
            return
        self.target.set(url)
        self.status.configure(text=f"IP camera set: {url}  (press Test camera to check it)", fg=OK)
        self.win.destroy()


def ground_archive_dir(cfg: dict[str, Any]) -> Path:
    return REPO_ROOT / str((cfg.get("downlink") or {}).get("archive", "ground_archive"))


class SessionsTable:
    """Past sessions (station: local logs; Earth: what was received), each
    re-read from its log with the hash chain re-verified."""

    COLS = ("when", "experiment", "steps", "alerts", "log", "images")

    def __init__(self, parent: tk.Widget, rows: Callable[[], list[dict[str, Any]]], earth: bool,
                 earth_target: Callable[[], str] | None = None) -> None:
        """earth_target (station side): the Earth IP[:port] from the start
        screen, for "Send to Earth" -- the fully offline mode's link window."""
        self.rows_fn, self.earth, self.rows = rows, earth, []
        self.earth_target = earth_target
        self._busy = False
        cols = self.COLS if earth else self.COLS + ("earth",)
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse", style="Dash.Treeview")
        widths = {"when": 140, "experiment": 300, "steps": 90, "alerts": 70, "log": 170, "images": 70,
                  "earth": 150}
        heads = {"steps": "steps done", "log": "log (hash chain)", "earth": "sent to Earth"}
        for c in cols:
            self.tree.heading(c, text=heads.get(c, c))
            self.tree.column(c, width=widths[c], stretch=c == "experiment",
                             anchor="w" if c == "experiment" else "center")
        self.tree.tag_configure("bad", foreground=BAD)
        self.tree.pack(side="top", fill="both", expand=True, padx=10)
        self.tree.bind("<Double-1>", lambda _e: self._open("report"))
        btns = tk.Frame(parent, bg=PANEL)
        btns.pack(side="top", fill="x", padx=10, pady=10)
        for text, what in (("Open report", "report"), ("Open folder", "folder"), ("Refresh", None)):
            tk.Button(btns, text=text, command=(lambda w=what: self._open(w)) if what else self.refresh,
                      bg=PANEL_2, fg=FG, activebackground=ACCENT, activeforeground=BG, relief="flat",
                      font=FONT_BOLD, padx=12, pady=5, cursor="hand2").pack(side="left", padx=(0, 8))
        if earth_target is not None:
            for text, cmd in (("🌍 Send to Earth", self._send_selected), ("Send all unsent", self._send_unsent)):
                tk.Button(btns, text=text, command=cmd, bg=ACCENT, fg=BG, activebackground=OK,
                          relief="flat", font=FONT_BOLD, padx=12, pady=5, cursor="hand2").pack(
                    side="left", padx=(0, 8))
        self.msg = tk.Label(btns, text="", bg=PANEL, fg=MUTED, font=FONT)
        self.msg.pack(side="left", padx=8)

    def refresh(self) -> None:
        try:
            self.rows = self.rows_fn()
        except OSError:
            self.rows = []
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            vals = [r["when"], r["experiment"], r["steps_done"], r["violations"],
                    f"verified, {r['lines']} lines" if r["chain_ok"] else "BROKEN"]
            vals.append(r.get("images", 0))
            if not self.earth:
                s = r.get("sent")
                vals.append(f"✓ {s['target']}" if s else "not sent")
            self.tree.insert("", "end", iid=str(i), values=vals, tags=() if r["chain_ok"] else ("bad",))
        self.msg.configure(text=f"{len(self.rows)} session(s)" if self.rows else "no sessions yet")

    # --- fully offline mode: send stored sessions when a link is available --

    def _target(self) -> tuple[str, int] | None:
        raw = self.earth_target() if self.earth_target else ""
        host, _, port = raw.rpartition(":") if ":" in raw else (raw, "", "5055")
        if not host:
            self.msg.configure(text='type the Earth IP in "Send to Earth - ground station at" (Setup, right)',
                               fg=BAD)
            return None
        if not port.isdigit():
            self.msg.configure(text="Earth address must look like 192.168.1.42:5055", fg=BAD)
            return None
        return host, int(port)

    def _send_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.msg.configure(text="select a session first", fg=WARN)
            return
        self._send([self.rows[int(sel[0])]])

    def _send_unsent(self) -> None:
        todo = [r for r in self.rows if not r.get("sent")]
        if not todo:
            self.msg.configure(text="every session is already on Earth", fg=OK)
            return
        self._send(todo)

    def _send(self, rows: list[dict[str, Any]]) -> None:
        import threading

        from src.link.upload import upload_session
        from src.runtime.offline import allow_host

        target = self._target()
        if target is None or self._busy:
            return
        host, port = target
        allow_host(host)  # the one address outside the LAN the offline guard lets through
        self._busy = True
        widget = self.tree

        def work() -> None:
            done, failed = 0, []
            for i, r in enumerate(rows, 1):
                widget.after(0, lambda i=i, r=r: self.msg.configure(
                    text=f"sending {i}/{len(rows)}: {r['session_id']} to {host}:{port} ...", fg=ACCENT))
                try:
                    res = upload_session(Path(r["log"]), host, port, timeout_s=45.0)
                except OSError as exc:
                    res = {"ok": False, "error": str(exc)}
                if res["ok"]:
                    done += 1
                else:
                    failed.append(res.get("error", "failed"))
                    break  # link is down: stop, try again later

            def finish() -> None:
                self._busy = False
                self.refresh()
                if failed:
                    self.msg.configure(text=f"{done} sent; stopped: {failed[0]} (nothing is lost - "
                                            "send again when the link is up)", fg=BAD)
                else:
                    self.msg.configure(text=f"{done} session(s) on Earth - log verified there, images attested",
                                       fg=OK)
            widget.after(0, finish)

        threading.Thread(target=work, name="send_to_earth", daemon=True).start()

    def _open(self, what: str) -> None:
        sel = self.tree.selection()
        if not sel:
            self.msg.configure(text="select a session first")
            return
        path = self.rows[int(sel[0])].get(what)
        if not path:
            self.msg.configure(text="no report for this session (it did not end normally)")
            return
        _open_path(Path(path))


def _open_path(path: Path) -> None:
    """Open a file or folder with the OS default application."""
    import os
    import subprocess
    import sys

    if hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606 -- local file the co-pilot wrote
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def summary_text(s: dict[str, Any]) -> str:
    """The last session, in one line, for the top of the dashboard."""
    chain = "log verified" if s.get("log_chain_ok") else "LOG CHAIN BROKEN"
    return (f"Last session {s.get('session_id')}: {s.get('steps_done')}/{s.get('steps_total')} steps, "
            f"{s.get('violations')} violation(s), {chain}.  Log: {s.get('log')}")
