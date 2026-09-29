"""Derived activity: one short line saying what the crew member is doing
right now ("Handling the red module cap", "Red module out of the box").

This is DERIVED, not a trained activity classifier: it combines the hand
skeleton's fingertip "holding" cue (bare hands only; measured ~95% while
a jar is out of the box) with the debounced object states from fusion
(container open/closed, module in/out, cap on/off, hands present).
"Reaching" cues are NOT used: measured right only 24-35% of the time.
Gloved hands have no skeleton, so it falls back to object states alone.

A label is logged (event_type "activity") only once it has held for
min_hold_s, so the log records activity changes, not per-frame noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def describe(states: dict[str, str], holding: list[str], names: dict[str, str], container: str | None) -> str:
    """states: fusion.states() (role -> open/closed, in/out, on/off; "hands"
    -> present/absent). holding: roles (or "<role>.lid") a hand holds now.
    names: role -> spoken name. container: the container role."""
    def nm(role: str) -> str:
        return names.get(role, role.replace("_", " "))

    hands = states.get("hands")
    modules = [r for r, v in states.items() if v in ("in", "out") and "." not in r]
    lid_off = [r[:-4] for r, v in states.items() if r.endswith(".lid") and v == "off"]
    out = [r for r in modules if states[r] == "out"]
    for h in holding:
        if h.endswith(".lid"):
            return f"Handling the {nm(h[:-4])} cap"
        if h in lid_off:
            return f"Working on the open {nm(h)}"
        if h in out:
            return f"Handling the {nm(h)} (out of the box)"
        return f"Holding the {nm(h)}"
    if lid_off:
        who = "hands on it" if hands == "present" else "NO HANDS in view"
        return f"{nm(lid_off[0]).capitalize()} open, {who}"
    if out:
        away = "" if hands != "absent" else ", hands away"
        return f"{' and '.join(nm(r) for r in out).capitalize()} out of the box{away}"
    if container and states.get(container) == "open":
        return "Working in the open container" if hands == "present" else "Container open, no hands in view"
    if hands == "present":
        return "Hands in the work area"
    return "Idle"


@dataclass
class ActivityTracker:
    min_hold_s: float = 1.0
    shown: str = ""  # what the GUI shows now (updates at once)
    logged: str = ""  # last label written to the log
    _cand: str = ""
    _since: float = 0.0

    def update(self, ts: float, label: str) -> str | None:
        """Returns the label to LOG, once it has held min_hold_s and differs
        from the last one logged; else None."""
        self.shown = label
        if label != self._cand:
            self._cand, self._since = label, ts
        if label != self.logged and ts - self._since >= self.min_hold_s:
            self.logged = label
            return label
        return None


def holding_roles(cues: list[Any]) -> list[str]:
    return [c.obj for c in cues if getattr(c, "state", None) == "holding"]
