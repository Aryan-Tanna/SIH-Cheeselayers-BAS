"""BAS Mission Control window (Earth side of the downlink), embeddable:
scripts/ground_station.py runs it on its own; the start screen
(src/runtime/dashboard.py, role EARTH) runs it inside the main window.
Reads GroundReceiver state only (src/link/receiver.py) -- polled from Tk's
own loop, like the co-pilot GUI."""

from __future__ import annotations

import os
import socket
import tkinter as tk
from typing import Any, Callable

from src.link.receiver import GroundReceiver, feed_record, ground_steps
from src.runtime.gui import (
    ACCENT, BAD, BG, FG, FONT, FONT_BIG, FONT_BOLD, FONT_MONO, MUTED, OK, PANEL, PANEL_2, STATUS_STYLE, WARN,
    event_line, fit_size, progress_text,
)


def local_ips() -> list[str]:
    """This PC's IPv4 addresses, for the crew to type in as the Earth IP.
    Offline: asks the OS, sends nothing."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(str(info[4][0]))
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127.")) or ["127.0.0.1"]


NO_SIGNAL_S = 5.0  # no message for this long = NO SIGNAL (the sender pings via acks/data)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def ground_feed_line(rec: dict[str, Any], t0: float | None, names: dict[str, str]) -> tuple[str, str] | None:
    et = rec.get("event_type")
    rel = "" if t0 is None else f"{(rec.get('ts_monotonic') or 0) - t0:7.1f}s  "
    if et == "snapshot":
        return (f"{rel}📷 image  {(rec.get('extra') or {}).get('label', '')}", MUTED)
    if et == "activity":
        return (f"{rel}activity: {rec.get('message')}", ACCENT)
    return event_line(feed_record(rec), t0, names)


class MissionControl:
    PANEL_MS = 300

    def __init__(self, root: tk.Tk, rx: GroundReceiver, on_back: Callable[[], None] | None = None) -> None:
        """on_back: shows a Back button (stop receiving, return to the start
        screen) when embedded; standalone it is None and closing quits."""
        self.root, self.rx, self.on_back = root, rx, on_back
        self._closed = False
        self._photo: Any = None
        self._thumbs: list[Any] = []
        self._shown_snap: str | None = None
        self._pinned: dict[str, Any] | None = None
        self._feed_key: tuple | None = None
        self._steps_key: tuple | None = None
        self._session: str | None = None
        root.title("BAS Mission Control - EARTH (receiving)")
        root.configure(bg=BG)
        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill="both", expand=True)
        self._build()
        self._tick()

    def _build(self) -> None:
        r = self.frame
        head = tk.Frame(r, bg=PANEL)
        head.pack(side="top", fill="x")
        tk.Label(head, text="🌍  EARTH  ·  MISSION CONTROL", bg=PANEL, fg=FG, font=FONT_BIG).pack(
            side="left", padx=14, pady=8)
        tk.Label(head, text="RECEIVER", bg=ACCENT, fg=BG, font=FONT_BOLD, padx=8, pady=2).pack(side="left", padx=4)
        self.session_lbl = tk.Label(head, text="waiting for the co-pilot...", bg=PANEL, fg=MUTED, font=FONT_BOLD)
        self.session_lbl.pack(side="left", padx=8)
        # status on its own row: long texts (data counts) must never push
        # the LINK badge off the window
        bar = tk.Frame(r, bg=PANEL)
        bar.pack(side="top", fill="x")
        self.badges: dict[str, tk.Label] = {}
        for key in ("link", "chain", "delay", "data"):
            lbl = tk.Label(bar, text="", bg=PANEL_2, fg=FG, font=FONT_BOLD, padx=10, pady=3)
            lbl.pack(side="left", padx=(10 if key == "link" else 4, 4), pady=(0, 8))
            self.badges[key] = lbl

        body = tk.Frame(r, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        left = tk.Frame(body, bg=PANEL, width=430)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        tk.Label(left, text="PROCEDURE (as executed on board)", bg=PANEL, fg=MUTED, font=FONT_BOLD,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        self.progress_lbl = tk.Label(left, text="", bg=PANEL, fg=FG, font=FONT_BOLD, anchor="w")
        self.progress_lbl.pack(fill="x", padx=12)
        self.steps_txt = tk.Text(left, bg=PANEL, fg=FG, font=FONT, relief="flat", wrap="word",
                                 cursor="arrow", highlightthickness=0, height=14)
        self.steps_txt.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        tk.Label(left, text="EVENTS FROM ORBIT", bg=PANEL, fg=MUTED, font=FONT_BOLD, anchor="w").pack(
            fill="x", padx=12, pady=(4, 2))
        self.feed_txt = tk.Text(left, bg=PANEL_2, fg=FG, font=FONT_MONO, relief="flat", wrap="word",
                                cursor="arrow", highlightthickness=0, height=14)
        self.feed_txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for t in (self.steps_txt, self.feed_txt):
            for colour in {OK, BAD, WARN, ACCENT, MUTED, FG, "#a78bfa"}:
                t.tag_configure(colour, foreground=colour)
        self.steps_txt.tag_configure("current", font=FONT_BOLD, background=PANEL_2)
        self.steps_txt.tag_configure("step", lmargin1=4, lmargin2=30, spacing1=2)
        self.feed_txt.tag_configure("event", lmargin1=2, lmargin2=80)

        self.image_box = tk.Frame(right, bg="#000000")
        self.image_box.pack(side="top", fill="both", expand=True)
        self.image_box.pack_propagate(False)
        self.image_lbl = tk.Label(self.image_box, bg="#000000", fg=MUTED, font=FONT,
                                  text="No images yet.\nOne arrives with every completed step and every alert\n"
                                       "- never a video stream: the link is kept for what matters.")
        self.image_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.caption_lbl = tk.Label(right, text="", bg=PANEL, fg=FG, font=FONT_BOLD, anchor="w", padx=10, pady=6)
        self.caption_lbl.pack(side="top", fill="x", pady=(6, 0))
        self.strip = tk.Frame(right, bg=BG, height=110)
        self.strip.pack(side="top", fill="x", pady=(6, 0))

        foot = tk.Frame(r, bg=BG)
        foot.pack(side="bottom", fill="x", padx=10, pady=(0, 10), before=body)
        if self.on_back is not None:
            tk.Button(foot, text="◀  Stop receiving", command=self.close, bg=BAD, fg=BG, relief="flat",
                      font=FONT_BOLD, padx=12, pady=5, cursor="hand2").pack(side="right")
        for text, cmd in (("Open archive folder", self._open_archive),
                          ("Open session report", self._open_report),
                          ("Latest image", self._unpin),
                          ("Simulate loss of signal", self.rx.drop_link)):
            tk.Button(foot, text=text, command=cmd, bg=PANEL_2, fg=FG, activebackground=ACCENT,
                      activeforeground=BG, relief="flat", font=FONT_BOLD, padx=12, pady=5,
                      cursor="hand2").pack(side="left", padx=(0, 8))
        ips = "  or  ".join(f"{ip}:{self.rx.port}" for ip in local_ips())
        self.hint_lbl = tk.Label(foot, text=f"Listening.  Give the space station this Earth IP:  {ips}",
                                 bg=BG, fg=MUTED, font=FONT_BOLD)
        self.hint_lbl.pack(side="left", padx=10)

    # --- actions ---------------------------------------------------------------

    def _open_archive(self) -> None:
        sess = self.rx.latest()
        path = sess.dir if sess else self.rx.archive
        if hasattr(os, "startfile"):
            os.startfile(path)  # noqa: S606 -- local folder, Windows

    def _open_report(self) -> None:
        sess = self.rx.latest()
        if sess and sess.report and hasattr(os, "startfile"):
            os.startfile(sess.dir / "report.txt")  # noqa: S606

    def _unpin(self) -> None:
        self._pinned, self._shown_snap = None, None

    # --- refresh -------------------------------------------------------------------

    def close(self) -> None:
        """Stop receiving and hand the window back (embedded mode)."""
        if self._closed:
            return
        self._closed = True
        self.frame.destroy()
        if self.on_back is not None:
            self.on_back()

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.refresh()
        finally:
            self.root.after(self.PANEL_MS, self._tick)

    def _badge(self, key: str, text: str, bg: str) -> None:
        self.badges[key].configure(text=text, bg=bg, fg=BG if bg in (OK, WARN, BAD, ACCENT) else FG)

    def refresh(self) -> None:
        rx = self.rx
        age = rx.signal_age_s()
        if rx.connected and age is not None and age < NO_SIGNAL_S:
            self._badge("link", f"● LIVE  ({age:.1f} s ago)", OK)
        elif rx.connected:
            self._badge("link", f"LINK UP, quiet {age:.0f} s" if age is not None else "LINK UP", WARN)
        else:
            latest = rx.latest()
            if latest is not None and latest.report is not None:
                self._badge("link", "SESSION COMPLETE - all data received", OK)
            else:
                self._badge("link", "NO SIGNAL - buffering on board" if age is not None else "NO SIGNAL", BAD)
        with rx.lock:
            sess = rx.latest()
            if sess is None:
                self._badge("chain", "LOG: -", PANEL_2)
                self._badge("data", "DATA: 0 B", PANEL_2)
                self._badge("delay", "DELAY: -", PANEL_2)
                return
            if sess.session_id != self._session:
                self._session, self._feed_key, self._steps_key = sess.session_id, None, None
                self._pinned, self._shown_snap = None, None
            events = list(sess.events)
            steps = ground_steps(sess)
            snaps = list(sess.snapshots)
            info, report = dict(sess.info), sess.report
            chain_ok, chain_err = sess.chain_ok, sess.chain_error
            b = dict(sess.bytes)
            delay = sess.last_delay_s
        title = info.get("title") or info.get("protocol_id") or ""
        self.session_lbl.configure(text=f"{title}   |   {self._session}" + ("   |   ENDED (report received)"
                                                                             if report else ""))
        self._badge("chain", f"LOG VERIFIED  {len(events)} lines" if chain_ok else "LOG TAMPERED",
                    OK if chain_ok else BAD)
        if not chain_ok:
            self.hint_lbl.configure(text=chain_err, fg=BAD)
        span = (events[-1]["ts_monotonic"] - events[0]["ts_monotonic"]) if len(events) > 1 else 0.0
        total = sum(b.values())
        rate = f", {total * 8 / span / 1000:.1f} kbit/s avg" if span > 1 else ""
        self._badge("data", f"DATA {human_bytes(total)}  (log {human_bytes(b['log'])}, images "
                    f"{human_bytes(b['snapshot'])}{rate})", PANEL_2)
        self._badge("delay", "DELAY -" if delay is None else f"DELAY {max(0.0, delay):.1f} s", PANEL_2)
        self._draw_steps(steps)
        self._draw_feed(events, steps)
        self._draw_images(snaps)

    def _draw_steps(self, steps: list[dict[str, Any]]) -> None:
        key = tuple((s["id"], s["status"], s["is_current"]) for s in steps)
        if key == self._steps_key:
            return
        self._steps_key = key
        self.progress_lbl.configure(text=progress_text({"steps": steps}))
        t = self.steps_txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        for s in steps:
            glyph, colour, label = STATUS_STYLE.get(s["status"], ("?", MUTED, s["status"]))
            obj = f"{s['object']}:  " if s.get("object") else ""
            opt = "  (optional)" if s.get("optional") else ""
            suffix = f"   ({label})" if label and s["status"] not in ("pending", "open", "done") else ""
            tags = (ACCENT if s["is_current"] else colour, "step") + (("current",) if s["is_current"] else ())
            t.insert("end", f" {glyph}  {obj}{s.get('prompt', s['id'])}{opt}{suffix}\n", tags)
        t.configure(state="disabled")

    def _draw_feed(self, events: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
        key = (len(events),)
        if key == self._feed_key:
            return
        self._feed_key = key
        t0 = events[0]["ts_monotonic"] if events else None
        names = {s["id"]: (f"{s['object']}: " if s.get("object") else "") + s.get("prompt", s["id"])
                 for s in steps}
        t = self.feed_txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        for rec in events[-200:]:
            line = ground_feed_line(rec, t0, names)
            if line is not None:
                t.insert("end", line[0] + "\n", (line[1], "event"))
        t.see("end")
        t.configure(state="disabled")

    def _draw_images(self, snaps: list[dict[str, Any]]) -> None:
        from PIL import Image, ImageTk

        show = self._pinned or (snaps[-1] if snaps else None)
        if show is not None and show.get("file") and (show["file"], show["attested"]) != self._shown_snap:
            self._shown_snap = (show["file"], show["attested"])
            img = Image.open(show["file"])
            tw, th = fit_size(img.width, img.height, self.image_box.winfo_width(), self.image_box.winfo_height())
            if tw > 2 and th > 2:
                self._photo = ImageTk.PhotoImage(img.resize((tw, th)))
                self.image_lbl.configure(image=self._photo, text="")
            ok = show["intact"] and show["attested"]
            verdict = ("VERIFIED - sha256 attested in the hash-chained log" if ok else
                       "NOT VERIFIED - " + ("damaged in transfer" if not show["intact"] else
                                            "no attestation received yet"))
            self.caption_lbl.configure(
                text=f"{'Pinned' if self._pinned else 'Latest'}:  {show['label']}   "
                     f"(log line {show['for_seq']}, {human_bytes(show['bytes'])})   {verdict}",
                fg=OK if ok else WARN)
        if len(self._thumbs) != len(snaps[-8:]) or (snaps and self._thumbs
                                                   and self._thumbs[-1][0] is not snaps[-1]):
            for w in self.strip.winfo_children():
                w.destroy()
            self._thumbs = []
            for s in snaps[-8:]:
                if not s.get("file"):
                    continue
                im = Image.open(s["file"])
                im.thumbnail((150, 90))
                ph = ImageTk.PhotoImage(im)
                b = tk.Button(self.strip, image=ph, bg=PANEL, relief="flat", cursor="hand2",
                              command=lambda s=s: self._pin(s))
                b.pack(side="left", padx=(0, 6))
                self._thumbs.append((s, ph))

    def _pin(self, snap: dict[str, Any]) -> None:
        self._pinned, self._shown_snap = snap, None


