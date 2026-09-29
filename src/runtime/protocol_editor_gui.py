"""Protocol editor window (Tk): write or change an experiment -- its steps
and the rules enforced on it -- and apply it to the running session.

All logic lives in src/protocol/editing.py (pure, unit-tested); this file
is only widgets. Every save goes through the real validator, and applying
uses the same validated hot-reload path as editing the JSON by hand, so
an invalid experiment can never reach the running session.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

import yaml

from src.protocol.editing import (
    ACTION_FIELD,
    ACTIONS,
    CONCURRENCY,
    SEVERITIES,
    StepRow,
    apply_rule_edit,
    build,
    flatten,
    load_raw,
    rename_step,
    rule_rows,
    PLACEHOLDER_PROMPT,
    save_validated,
    targets,
    validate_raw,
)
from src.runtime.gui import ACCENT, BAD, BG, FG, FONT, FONT_BOLD, FONT_MONO, MUTED, OK, PANEL, PANEL_2, WARN

REFERENCE_PROTOCOLS = {"bas_specimen_v1.json"}  # harness fixtures depend on these: the editor never overwrites them
STEP_COLS = ("action", "target", "place", "after", "prompt", "condition", "limit")
RULE_COLS = ("on", "severity", "timer", "alert", "origin")
# What each primitive means, shown under the form. The camera perceives
# open/close, take out/put in and lid stowing today (src/perception/fusion.py);
# the rest are confirmed by the operator ("next step").
ACTION_HELP = {
    "open": "open it: the container, or a module's cap",
    "close": "close it: the container, or a module's cap",
    "remove_from": "take the object OUT of a container (pick the container in From / to)",
    "place_into": "put the object INTO a container (pick the container in From / to)",
    "move_to_zone": "put the object in a zone, e.g. a lid in the stow zone",
    "grasp": "hold the object -- not seen by the camera yet: the operator confirms it",
    "release": "let go of the object -- not seen by the camera yet: the operator confirms it",
    "dwell": "keep the object still for a while -- not seen by the camera yet: the operator confirms it",
}
HOW_TO = ("How to add a step:  1) click the step it comes after   2) Add step   3) choose Action and "
          "Object, write the Spoken prompt   4) Apply changes to step   5) Save as new experiment.  "
          "Order comes only from 'After' -- a group does not order its steps.  Time limit (s): alert once "
          "if the step is not done that long after it is due (blank = none).  A group's 'Out together': "
          "may its module be out at the same time as another module.  Optional: an allowed extra action -- "
          "never required or spoken; anything the procedure does not list is alerted as an extra step.")


def _fmt_limit(v: float | None) -> str:
    return "" if not v else f"{v:g}"


def _parse_after(text: str) -> list[str]:
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]


class ProtocolEditor:
    def __init__(self, root: tk.Misc, app: Any) -> None:
        self.app = app
        self.path = Path(app.protocol_path)
        self.defaults_path = Path(app.defaults_path)
        self.defaults = yaml.safe_load(self.defaults_path.read_text(encoding="utf-8"))
        self.profile_ref = app.object_profile
        self.profile = app.resolved.parsed.object_profile or {}
        self.raw = load_raw(self.path)
        self.rows = flatten(self.raw)
        self.dirty = False

        self.win = tk.Toplevel(root, bg=PANEL)
        self.win.title("Protocol editor")
        self.win.transient(root)
        self.win.geometry("1180x720")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build_header()
        self._build_footer()  # packed before the notebook so it keeps its space
        nb = ttk.Notebook(self.win)
        nb.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        self.steps_tab = tk.Frame(nb, bg=PANEL)
        self.rules_tab = tk.Frame(nb, bg=PANEL)
        nb.add(self.steps_tab, text="  Steps  ")
        nb.add(self.rules_tab, text="  Rules  ")
        self._build_steps()
        self._build_rules()
        self.refresh_steps()
        self.refresh_rules()

    # --- layout ---------------------------------------------------------------

    def _style(self) -> None:
        from tkinter import font as tkfont

        st = ttk.Style(self.win)
        # row height from the real font metrics: a fixed height clips the
        # descenders on a scaled display (underscores vanished at 125%)
        line = tkfont.Font(root=self.win, font=FONT).metrics("linespace")
        st.configure("Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=FG,
                     rowheight=line + 8, font=FONT)
        st.configure("Treeview.Heading", font=FONT_BOLD)
        st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])

    def _label(self, parent: tk.Widget, text: str, **kw: Any) -> tk.Label:
        return tk.Label(parent, text=text, bg=PANEL, fg=kw.pop("fg", FG), font=kw.pop("font", FONT), **kw)

    def _entry(self, parent: tk.Widget, var: tk.StringVar, width: int = 18) -> tk.Entry:
        return tk.Entry(parent, textvariable=var, bg=PANEL_2, fg=FG, insertbackground=FG, relief="flat",
                        font=FONT, width=width)

    def _button(self, parent: tk.Widget, text: str, cmd: Any) -> tk.Button:
        b = tk.Button(parent, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      relief="flat", font=FONT_BOLD, padx=10, pady=3, cursor="hand2")
        b.pack(side="left", padx=(0, 6))
        return b

    def _build_header(self) -> None:
        h = tk.Frame(self.win, bg=PANEL)
        h.pack(side="top", fill="x", padx=10, pady=(8, 0))
        self.title_var = tk.StringVar(value=self.raw.get("title", ""))
        self.pid_var = tk.StringVar(value=self.raw.get("protocol_id", ""))
        self._label(h, "Experiment title", font=FONT_BOLD).pack(side="left")
        self._entry(h, self.title_var, 40).pack(side="left", padx=6)
        self._label(h, "ID", font=FONT_BOLD).pack(side="left", padx=(12, 0))
        self._entry(h, self.pid_var, 22).pack(side="left", padx=6)
        self.file_lbl = self._label(h, f"file: {self.path.name}", fg=MUTED)
        self.file_lbl.pack(side="right")

    def _build_steps(self) -> None:
        t = self.steps_tab
        self.tree = ttk.Treeview(t, columns=STEP_COLS, show="tree headings", height=6, selectmode="browse")
        self.tree.heading("#0", text="step / group")
        self.tree.column("#0", width=190)
        widths = {"action": 110, "target": 120, "place": 120, "after": 170, "prompt": 330, "condition": 120,
                  "limit": 70}
        heads = {"place": "from / to / zone", "limit": "limit (s)"}
        for c in STEP_COLS:
            self.tree.heading(c, text=heads.get(c, c))
            self.tree.column(c, width=widths[c], stretch=c == "prompt")
        self.tree.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._load_form())

        form = tk.Frame(t, bg=PANEL)
        form.pack(side="top", fill="x", padx=6)
        self.f = {k: tk.StringVar() for k in ("id", "group", "action", "target", "place", "after", "prompt",
                                              "condition", "time_limit", "together", "optional")}
        roles = list((self.raw.get("roles") or {}).keys())
        zones = list((self.raw.get("zones") or {}).keys())
        self._place_values = {"source": roles, "dest": roles, "zone": zones}
        fields = [("id", "ID", None), ("group", "In group", []), ("action", "Action", list(ACTIONS)),
                  ("target", "Object", targets(self.raw, self.profile)), ("place", "From / to / zone", []),
                  ("after", "After (IDs)", None), ("condition", "Only if", ["", "target.has_lid"]),
                  ("prompt", "Spoken prompt", None), ("time_limit", "Time limit (s)", None),
                  ("together", "Group: out together", list(CONCURRENCY)),
                  ("optional", "Optional (allowed extra)", ["no", "yes"])]
        self.combos: dict[str, ttk.Combobox] = {}
        for i, (key, label, values) in enumerate(fields):
            r, c = divmod(i, 4)
            self._label(form, label, font=FONT_BOLD).grid(row=r * 2, column=c, sticky="w", padx=4)
            if values is None:
                w = self._entry(form, self.f[key], 58 if key == "prompt" else (8 if key == "time_limit" else 24))
            else:
                w = ttk.Combobox(form, textvariable=self.f[key], values=values, width=22,
                                 state="readonly" if key in ("action", "group", "together", "optional")
                                 else "normal")
                self.combos[key] = w
            w.grid(row=r * 2 + 1, column=c, columnspan=3 if key == "prompt" else 1, sticky="we", padx=4, pady=(0, 6))
        self.f["action"].trace_add("write", lambda *_: self._action_changed())

        btns = tk.Frame(t, bg=PANEL)
        btns.pack(side="top", fill="x", padx=6, pady=6)
        self._button(btns, "Apply changes to step", self.update_row)
        self._button(btns, "Add step", lambda: self.add_row("step"))
        self._button(btns, "Add group", lambda: self.add_row("group"))
        self._button(btns, "Delete", self.delete_row)
        self._button(btns, "Move up", lambda: self.move(-1))
        self._button(btns, "Move down", lambda: self.move(1))
        # form + buttons keep their space; the table takes what is left
        for w in (btns, form, self.tree):
            w.pack_forget()
        btns.pack(side="bottom", fill="x", padx=6, pady=6)  # buttons at the bottom, fields above them
        self.action_help = self._label(t, "", fg=ACCENT, anchor="w")
        self.action_help.pack(side="bottom", fill="x", padx=10)
        form.pack(side="bottom", fill="x", padx=6)
        self._label(t, HOW_TO, fg=MUTED, anchor="w", justify="left", wraplength=1100).pack(
            side="top", fill="x", padx=8, pady=(6, 0))
        self.tree.pack(side="top", fill="both", expand=True, padx=6, pady=6)

    def _build_rules(self) -> None:
        t = self.rules_tab
        self.rtree = ttk.Treeview(t, columns=RULE_COLS, show="tree headings", height=6, selectmode="browse")
        self.rtree.heading("#0", text="rule")
        self.rtree.column("#0", width=230)
        widths = {"on": 80, "severity": 90, "timer": 80, "alert": 520, "origin": 90}
        for c in RULE_COLS:
            self.rtree.heading(c, text=c)
            self.rtree.column(c, width=widths[c], stretch=c == "alert")
        self.rtree.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.rtree.bind("<<TreeviewSelect>>", lambda _e: self._load_rule())

        form = tk.Frame(t, bg=PANEL)
        form.pack(side="top", fill="x", padx=6)
        self.r_on = tk.BooleanVar(value=True)
        self.r_sev = tk.StringVar()
        self.r_timer = tk.StringVar()
        self.r_alert = tk.StringVar()
        self.on_chk = tk.Checkbutton(form, text="Enforced", variable=self.r_on, bg=PANEL, fg=FG,
                                     selectcolor=PANEL_2, activebackground=PANEL, font=FONT_BOLD)
        self.on_chk.grid(row=0, column=0, sticky="w", padx=4)
        self._label(form, "Severity", font=FONT_BOLD).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self.r_sev, values=list(SEVERITIES), state="readonly",
                     width=12).grid(row=0, column=2, padx=4)
        self.timer_lbl = self._label(form, "Timer (s)", font=FONT_BOLD)
        self.timer_lbl.grid(row=0, column=3, sticky="w", padx=4)
        self.timer_entry = self._entry(form, self.r_timer, 8)
        self.timer_entry.grid(row=0, column=4, padx=4)
        self._label(form, "Spoken alert", font=FONT_BOLD).grid(row=1, column=0, sticky="w", padx=4, pady=6)
        self._entry(form, self.r_alert, 80).grid(row=1, column=1, columnspan=5, sticky="we", padx=4)
        rb = tk.Frame(t, bg=PANEL)
        rb.pack(side="top", fill="x", padx=6, pady=6)
        self._button(rb, "Apply to rule", self.apply_rule)
        self.rule_note = self._label(rb, "", fg=MUTED, justify="left", wraplength=820)
        self.rule_note.pack(side="left", padx=10)
        for w in (rb, form, self.rtree):
            w.pack_forget()
        rb.pack(side="bottom", fill="x", padx=6, pady=6)  # buttons at the bottom, fields above them
        form.pack(side="bottom", fill="x", padx=6)
        self.rtree.pack(side="top", fill="both", expand=True, padx=6, pady=6)

    def _build_footer(self) -> None:
        f = tk.Frame(self.win, bg=PANEL)
        f.pack(side="bottom", fill="x", padx=10, pady=8)
        self.msg = tk.Text(self.win, height=5, bg=PANEL_2, fg=FG, font=FONT_MONO, relief="flat", wrap="word")
        self.msg.pack(side="bottom", fill="x", padx=10)
        for colour in (OK, BAD, WARN, FG):
            self.msg.tag_configure(colour, foreground=colour)
        self._button(f, "Validate", self.validate)
        self._button(f, "Save & apply", self.save_apply)
        self._button(f, "Save as new experiment...", self.save_as_new)
        self._button(f, "Close", self.close)

    # --- steps ---------------------------------------------------------------

    def refresh_steps(self, select: str | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            vals = ("", "", "", ", ".join(r.after), "", "", "") if r.kind == "group" else (
                r.action, r.target, r.place, ", ".join(r.after), r.prompt, r.condition, _fmt_limit(r.time_limit))
            parent = r.group if (r.kind == "step" and r.group) else ""
            together = " (out together)" if r.concurrency == "permitted" else ""
            text = f"[group] {r.id}{together}" if r.kind == "group" else (
                f"{r.id} (optional)" if r.optional else r.id)
            self.tree.insert(parent, "end", iid=r.id, text=text, values=vals, open=True)
        self.combos["group"].configure(values=[""] + [r.id for r in self.rows if r.kind == "group"])
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)

    def _row(self, rid: str) -> StepRow | None:
        return next((r for r in self.rows if r.id == rid), None)

    def _selected(self) -> StepRow | None:
        sel = self.tree.selection()
        return self._row(sel[0]) if sel else None

    def _load_form(self) -> None:
        r = self._selected()
        if r is None:
            return
        self.f["id"].set(r.id)
        self.f["group"].set(r.group)
        self.f["action"].set(r.action)
        self.f["target"].set(r.target)
        self.f["place"].set(r.place)
        self.f["after"].set(", ".join(r.after))
        self.f["prompt"].set(r.prompt)
        self.f["condition"].set(r.condition)
        self.f["time_limit"].set(_fmt_limit(r.time_limit) if r.kind == "step" else "")
        self.f["together"].set(r.concurrency if r.kind == "group" else "")
        self.f["optional"].set(("yes" if r.optional else "no") if r.kind == "step" else "")

    def _action_changed(self) -> None:
        action = self.f["action"].get()
        self.action_help.configure(text=f"{action}: {ACTION_HELP[action]}" if action in ACTION_HELP else "")
        key = ACTION_FIELD.get(action)
        self.combos["place"].configure(values=self._place_values.get(key, []) if key else [],
                                       state="normal" if key else "disabled")
        if not key:
            self.f["place"].set("")

    def _say(self, text: str, colour: str = FG) -> None:
        self.msg.configure(state="normal")
        self.msg.delete("1.0", "end")
        self.msg.insert("end", text, (colour,))
        self.msg.configure(state="disabled")

    def update_row(self) -> None:
        r = self._selected()
        if r is None:
            self._say("Select a step or group first.", WARN)
            return
        new_id = self.f["id"].get().strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new_id):
            self._say("ID: letters, digits and _ only, not starting with a digit.", BAD)
            return
        if new_id != r.id and self._row(new_id) is not None:
            self._say(f"ID '{new_id}' already exists.", BAD)
            return
        limit: float | None = None
        if r.kind == "step" and self.f["time_limit"].get().strip():
            try:
                limit = float(self.f["time_limit"].get())
            except ValueError:
                limit = -1.0
            if not limit > 0:
                self._say("Time limit: a number of seconds above 0, or blank for no limit.", BAD)
                return
        if new_id != r.id:
            rename_step(self.rows, r.id, new_id)
        r.after = _parse_after(self.f["after"].get())
        if r.kind == "group":
            together = self.f["together"].get()
            r.concurrency = together if together in CONCURRENCY else "forbidden"
        if r.kind == "step":
            group = self.f["group"].get()
            if group and group not in [g.id for g in self.rows if g.kind == "group"]:
                group = ""
            if group != r.group:  # moving into / out of a group: keep it next to its group
                self.rows.remove(r)
                r.group = group
                idx = max((i for i, x in enumerate(self.rows) if x.id == group or x.group == group),
                          default=len(self.rows) - 1) + 1 if group else len(self.rows)
                self.rows.insert(idx, r)
            r.action, r.target = self.f["action"].get(), self.f["target"].get()
            r.source = r.dest = r.zone = ""
            key = ACTION_FIELD.get(r.action)
            if key:
                setattr(r, key, self.f["place"].get())
            r.prompt, r.condition = self.f["prompt"].get().strip(), self.f["condition"].get().strip()
            r.time_limit = limit
            r.optional = self.f["optional"].get() == "yes"
        self.dirty = True
        self.refresh_steps(select=r.id)
        self._say(f"Updated '{r.id}'. Validate or Save to check it.", OK)

    def add_row(self, kind: str) -> None:
        base = "new_group" if kind == "group" else "new_step"
        n = 1
        while self._row(f"{base}_{n}"):
            n += 1
        sel = self._selected()
        row = StepRow(kind, f"{base}_{n}")
        if kind == "step":
            row.action, row.prompt = "open", PLACEHOLDER_PROMPT
            row.target = next(iter(self.raw.get("roles") or {}), "")
            if sel is not None:
                row.group = sel.id if sel.kind == "group" else sel.group
                row.after = [sel.id] if sel.kind == "step" else []
        idx = self.rows.index(sel) + 1 if sel is not None else len(self.rows)
        if kind == "group":
            idx = len(self.rows)
        self.rows.insert(idx, row)
        if kind == "group":  # a group needs a step to exist
            first = StepRow("step", f"{row.id}_step_1", group=row.id, action="open",
                            target=next(iter(self.raw.get("roles") or {}), ""), prompt=PLACEHOLDER_PROMPT)
            self.rows.insert(idx + 1, first)
        self.dirty = True
        self.refresh_steps(select=row.id)
        self._load_form()
        self._say(f"Added '{row.id}'. Fill in the fields below, then press Apply changes to step.", OK)

    def delete_row(self) -> None:
        r = self._selected()
        if r is None:
            return
        gone = {r.id} | ({x.id for x in self.rows if x.group == r.id} if r.kind == "group" else set())
        users = sorted({x.id for x in self.rows if x.id not in gone and set(x.after) & gone})
        self.rows = [x for x in self.rows if x.id not in gone]
        for x in self.rows:
            x.after = [a for a in x.after if a not in gone]
        self.dirty = True
        self.refresh_steps()
        note = f"  (removed it from 'after' of: {', '.join(users)})" if users else ""
        self._say(f"Deleted {', '.join(sorted(gone))}.{note}", WARN if users else OK)

    def move(self, d: int) -> None:
        r = self._selected()
        if r is None:
            return
        i = self.rows.index(r)
        j = i + d
        # stay among siblings (same group / top level); list order is display only
        while 0 <= j < len(self.rows) and self.rows[j].group != r.group:
            j += d
        if 0 <= j < len(self.rows):
            self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
            self.dirty = True
            self.refresh_steps(select=r.id)

    # --- rules ---------------------------------------------------------------

    def refresh_rules(self, select: str | None = None) -> None:
        self.rtree.delete(*self.rtree.get_children())
        self._rules = {r.id: r for r in rule_rows(self.defaults, self.raw)}
        for r in self._rules.values():
            on = "LOCKED" if r.locked else ("on" if r.enabled else "off")
            timer = "" if r.timer is None else f"{r.timer:g}"
            self.rtree.insert("", "end", iid=r.id, text=r.id,
                              values=(on, r.severity, timer, r.alert, r.origin))
        if select:
            self.rtree.selection_set(select)

    def _load_rule(self) -> None:
        sel = self.rtree.selection()
        if not sel:
            return
        r = self._rules[sel[0]]
        self.r_on.set(r.enabled)
        self.on_chk.configure(state="disabled" if r.locked else "normal")
        self.r_sev.set(r.severity)
        self.r_timer.set("" if r.timer is None else f"{r.timer:g}")
        self.timer_entry.configure(state="normal" if r.timer_key else "disabled")
        self.timer_lbl.configure(text=f"Timer ({r.timer_key})" if r.timer_key else "Timer (none)")
        self.r_alert.set(r.alert)
        lock = "LOCKED: a safety rule that cannot be switched off. " if r.locked else ""
        self.rule_note.configure(text=f"{lock}type {r.type}, basis {r.basis}. {r.note}")

    def apply_rule(self) -> None:
        sel = self.rtree.selection()
        if not sel:
            self._say("Select a rule first.", WARN)
            return
        r = self._rules[sel[0]]
        timer = None
        if r.timer_key:
            try:
                timer = float(self.r_timer.get())
            except ValueError:
                self._say("Timer must be a number of seconds.", BAD)
                return
        try:
            self.raw = apply_rule_edit(self.raw, self.defaults, r.id,
                                       enabled=None if r.locked else self.r_on.get(),
                                       severity=self.r_sev.get() or None,
                                       alert=self.r_alert.get().strip() or None, timer=timer)
        except ValueError as exc:
            self._say(str(exc), BAD)
            return
        self.dirty = True
        self.refresh_rules(select=r.id)
        self._say(f"Rule '{r.id}' changed (marked [protocol] at startup). Save to apply.", OK)

    # --- save ----------------------------------------------------------------

    def current_raw(self) -> dict[str, Any] | None:
        try:
            raw = build(self.raw, self.rows)
        except ValueError as exc:
            self._say(str(exc), BAD)
            return None
        raw["title"] = self.title_var.get().strip() or raw.get("title", "")
        raw["protocol_id"] = self.pid_var.get().strip() or raw.get("protocol_id", "")
        return raw

    def unapplied_step(self) -> str | None:
        """The selected step's id if the form holds edits not yet applied to
        it -- saving would silently drop them, the editor's most confusing
        failure. None when the form matches the step."""
        r = self._selected()
        if r is None:
            return None
        key = ACTION_FIELD.get(r.action)
        now = {"id": r.id, "group": r.group, "after": ", ".join(r.after)}
        if r.kind == "step":
            now.update(action=r.action, target=r.target, place=getattr(r, key) if key else "",
                       prompt=r.prompt, condition=r.condition, time_limit=_fmt_limit(r.time_limit),
                       optional="yes" if r.optional else "no")
        else:
            now.update(together=r.concurrency)
        differs = [k for k, v in now.items() if self.f[k].get().strip() != (v or "").strip()]
        return r.id if differs else None

    def _refuse_if_unapplied(self) -> bool:
        sid = self.unapplied_step()
        if sid is not None:
            self._say(f"Step '{sid}' has changes in the form that are not applied yet. Press "
                      "'Apply changes to step' first (or click the step again to discard them).", WARN)
        return sid is not None

    def validate(self) -> bool:
        if self._refuse_if_unapplied():
            return False
        raw = self.current_raw()
        if raw is None:
            return False
        findings = validate_raw(raw, self.path, self.defaults_path, self.profile_ref)
        if findings:
            self._say("NOT valid -- fix these:\n" + "\n".join(findings), BAD)
            return False
        self._say("Valid: steps resolve, no cycles, every rule has a basis, reachable from the start.", OK)
        return True

    def _write_and_apply(self, path: Path) -> None:
        if self._refuse_if_unapplied():
            return
        raw = self.current_raw()
        if raw is None:
            return
        findings = save_validated(raw, path, self.defaults_path, self.profile_ref)
        if findings:
            self._say("NOT saved -- fix these:\n" + "\n".join(findings), BAD)
            return
        if self.app.use_protocol(path):
            self.path, self.raw, self.dirty = path, raw, False
            self.file_lbl.configure(text=f"file: {path.name}")
            self._say(f"Saved {path.name} and applied to the running session "
                      "(resolved rules printed in the console).", OK)
        else:
            self._say(f"Saved {path.name}, but the session REJECTED it -- still running the old "
                      "protocol. See the warning in the main window.", BAD)

    def save_apply(self) -> None:
        # No "overwrite anyway?" dialog: during a live demo someone clicks Yes,
        # the harness fixtures stop matching, and the headline metric breaks.
        if self.path.name in REFERENCE_PROTOCOLS:
            self._say(f"{self.path.name} is the reference experiment the harness is built on and "
                      "cannot be overwritten here. Use 'Save as new experiment...'.", WARN)
            return
        self._write_and_apply(self.path)

    def save_as_new(self) -> None:
        name = simpledialog.askstring("New experiment", "File name (saved in configs/protocols/):",
                                      initialvalue=(self.pid_var.get() or "my_experiment"), parent=self.win)
        if not name:
            return
        name = re.sub(r"[^A-Za-z0-9_\-]", "_", name.strip()).removesuffix(".json")
        path = self.path.parent / f"{name}.json"
        if path.name in REFERENCE_PROTOCOLS:
            self._say(f"{path.name} is the reference experiment; pick another name.", BAD)
            return
        if path.exists() and not messagebox.askyesno("Replace?", f"{path.name} exists. Replace it?",
                                                     parent=self.win):
            return
        if self.pid_var.get() in ("", self.raw.get("protocol_id")) and path.stem != self.raw.get("protocol_id"):
            self.pid_var.set(name)
        self._write_and_apply(path)

    def close(self) -> None:
        if self.dirty and not messagebox.askyesno("Discard changes?", "Close without saving?", parent=self.win):
            return
        self.win.destroy()
