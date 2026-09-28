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
                 source: int | str | None = None, object_profile: str | None = None) -> None:
        """source / object_profile: command-line --source / --profile. They
        prefill the setup fields and win over configs/runtime.yaml, so
        `run_gui.py --source http://<phone>:4747/video` still means the phone."""
        self.root = root
        self.cfg = cfg
        self.on_start = on_start
        self._cli_source = source
        self._cli_profile = object_profile
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

    # --- layout ------------------------------------------------------------

    def _build(self, last_summary: dict[str, Any] | None) -> None:
        f = self.frame
        head = tk.Frame(f, bg=PANEL)
        head.pack(side="top", fill="x")
        tk.Label(head, text="BAS Co-Pilot", bg=PANEL, fg=FG, font=FONT_BIG).pack(side="left", padx=16, pady=10)
        tk.Label(head, text="1  Choose an experiment     2  Check the setup     3  Start",
                 bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(side="left", padx=20)

        if last_summary:
            tk.Label(f, text=summary_text(last_summary), bg=PANEL_2, fg=FG, font=FONT, anchor="w",
                     justify="left", padx=12, pady=8).pack(side="top", fill="x", padx=16, pady=(10, 0))

        body = tk.Frame(f, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=16, pady=10)

        # left: experiments
        left = tk.Frame(body, bg=PANEL)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="EXPERIMENTS", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").pack(
            side="top", fill="x", padx=12, pady=(10, 4))
        style = ttk.Style(self.root)
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
        tk.Label(setup, text="webcam number, phone (DroidCam) address, or a video file",
                 bg=PANEL, fg=MUTED, font=FONT, wraplength=420, justify="left").grid(
            row=3, column=1, columnspan=2, sticky="w", padx=6)
        self.voice_var = tk.BooleanVar(value=bool((self.cfg.get("voice_control") or {}).get("enabled", True)))
        self.record_var = tk.BooleanVar(value=bool((self.cfg.get("recording") or {}).get("enabled", True)))
        self.detect_var = tk.BooleanVar(value=bool((self.cfg.get("perception") or {}).get("enabled", True)))
        opts = tk.Frame(setup, bg=PANEL)
        opts.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for text, var in (("Voice commands (\"Hey BAS\")", self.voice_var), ("Record video", self.record_var),
                          ("Watch with the camera (detector)", self.detect_var)):
            tk.Checkbutton(opts, text=text, variable=var, bg=PANEL, fg=FG, selectcolor=PANEL_2,
                           activebackground=PANEL, activeforeground=FG, font=FONT).pack(side="top", anchor="w")
        setup.columnconfigure(1, weight=1)

        self.start_btn = tk.Button(right, text="Start experiment  ▶", command=self.start, bg=OK, fg=BG,
                                   activebackground=ACCENT, relief="flat", font=FONT_BIG, pady=8,
                                   cursor="hand2")
        self.start_btn.pack(side="bottom", fill="x", padx=10, pady=10)
        self.msg = tk.Label(right, text="", bg=PANEL, fg=WARN, font=FONT, anchor="w", justify="left",
                            wraplength=490)
        self.msg.pack(side="bottom", fill="x", padx=12)

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

    def start(self) -> None:
        info = self.selected()
        if info is None or not info.ready:
            self.msg.configure(text="Pick an experiment marked 'ready'.", fg=BAD)
            return
        self.on_start(StartChoice(
            protocol=info.path, object_profile=self.selected_profile(),
            source=parse_source(self.source_var.get()), voice_control=self.voice_var.get(),
            record=self.record_var.get(), perception=self.detect_var.get()))

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


def summary_text(s: dict[str, Any]) -> str:
    """The last session, in one line, for the top of the dashboard."""
    chain = "log verified" if s.get("log_chain_ok") else "LOG CHAIN BROKEN"
    return (f"Last session {s.get('session_id')}: {s.get('steps_done')}/{s.get('steps_total')} steps, "
            f"{s.get('violations')} violation(s), {chain}.  Log: {s.get('log')}")
