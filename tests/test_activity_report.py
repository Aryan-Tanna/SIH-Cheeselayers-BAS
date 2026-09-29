"""Derived activity line, the readable session report, and the GUI helpers
for the Earth link."""

import json
import time
from pathlib import Path

from src.link.receiver import GroundReceiver, ground_steps
from src.logging.report import build_report
from src.logging.session_log import SessionLogger, load_events, verify_chain
from src.protocol.engine import ProtocolEngine
from src.protocol.events import ActionEvent
from src.protocol.loader import resolve
from src.runtime.activity import ActivityTracker, describe
from src.runtime.clock import VirtualClock
from src.runtime.gui import activity_text, earth_badge, step_lines

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "configs" / "protocols" / "bas_specimen_v1.json"
DEFAULTS = REPO / "configs" / "defaults.yaml"
NAMES = {"module_a": "red module", "module_b": "yellow module", "container": "payload container"}
BASE = {"container": "closed", "module_a": "in", "module_b": "in", "module_a.lid": "on",
        "module_b.lid": "on", "hands": "absent"}


# --- activity -------------------------------------------------------------

def test_activity_priorities():
    s = dict(BASE)
    assert describe(s, [], NAMES, "container") == "Idle"
    s["hands"] = "present"
    assert describe(s, [], NAMES, "container") == "Hands in the work area"
    s["container"] = "open"
    assert describe(s, [], NAMES, "container") == "Working in the open container"
    s["module_a"] = "out"
    assert describe(s, ["module_a"], NAMES, "container") == "Handling the red module (out of the box)"
    assert describe(s, [], NAMES, "container") == "Red module out of the box"
    s["module_a.lid"] = "off"
    assert describe(s, ["module_a.lid"], NAMES, "container") == "Handling the red module cap"
    assert describe(s, ["module_a"], NAMES, "container") == "Working on the open red module"
    s["hands"] = "absent"
    assert describe(s, [], NAMES, "container") == "Red module open, NO HANDS in view"


def test_activity_logged_only_once_stable():
    tr = ActivityTracker(min_hold_s=1.0)
    assert tr.update(0.0, "Idle") is None
    assert tr.update(1.0, "Idle") == "Idle"
    assert tr.update(1.2, "Hands in the work area") is None  # flicker...
    assert tr.update(1.4, "Idle") is None  # ...back: nothing logged
    assert tr.update(2.0, "Holding the red module") is None
    assert tr.shown == "Holding the red module"  # the GUI shows it at once
    assert tr.update(3.1, "Holding the red module") == "Holding the red module"


def test_activity_line_marks_reach_as_a_guess():
    txt = activity_text("Idle", [{"obj": "module_b", "state": "reaching", "eta_s": 0.6}], NAMES, gloved=1)
    assert txt.startswith("Now doing:  Idle") and "maybe reaching for the yellow module (0.6 s)" in txt
    assert "1 gloved hand" in txt


# --- report -----------------------------------------------------------------

def _session(tmp_path, events, steps_optional=False):
    clock = VirtualClock()
    eng = ProtocolEngine(resolve(PROTOCOL, DEFAULTS), clock=clock)
    log = tmp_path / "s.jsonl"
    with SessionLogger(log, "s") as lg:
        for e in eng.out:
            lg.log_event(e)
        seen = len(eng.out)
        for t, kw in events:
            clock.advance_to(t)
            eng.process(ActionEvent(ts=t, **kw))
            for e in eng.out[seen:]:
                lg.log_event(e)
            seen = len(eng.out)
    steps = [{"id": s, "prompt": eng.parsed.nodes[s].prompt, "object": "", "optional": False,
              "status": "not_applicable" if s in eng.skipped else "pending"} for s in eng.parsed.order]
    return log, steps


def test_report_lists_every_step_with_outcome_and_violations(tmp_path):
    log, steps = _session(tmp_path, [
        (1.0, dict(action="open", target="container")),
        (2.0, dict(action="remove_from", target="module_a", source="container")),
        (6.0, dict(action="place_into", target="module_a", dest="container")),  # lid steps skipped
        (9.0, dict(action="close", target="container")),
    ])
    chain = verify_chain(log)
    text = build_report(load_events(log), steps, title="Dual specimen module inspection",
                        chain_ok=chain.ok, chain_lines=chain.lines_checked, log_name=log.name)
    assert "hash chain VERIFIED" in text
    assert "RESULT      : 4 of 12 steps done, 8 missed" in text
    assert "DONE, OUT OF ORDER" in text  # return_a before its lid steps
    assert text.count("MISSED") == 8
    assert "+00:01.0" in text and "skip" in text and "module_not_returned" not in text


def test_report_marks_not_applicable_and_unreached(tmp_path):
    log, steps = _session(tmp_path, [(1.0, dict(action="open", target="container"))])
    steps[2]["status"] = "not_applicable"
    text = build_report(load_events(log), steps)
    assert "n/a" in text and "not reached" in text and "1 of 11 steps done" in text


# --- earth badge --------------------------------------------------------------

class _St:
    def __init__(self, d):
        self.downlink = d


def test_earth_badge_states():
    assert earth_badge(_St(None)) is None
    up = {"connected": True, "bytes_sent": 500_000, "queued": 0, "unacked": 0}
    text, _ = earth_badge(_St(up))
    assert text.startswith("EARTH ● 488 KB sent")
    down = {"connected": False, "bytes_sent": 0, "queued": 5, "unacked": 5}
    assert earth_badge(_St(down))[0] == "EARTH: no link, 5 buffered"


def test_optional_step_is_labelled_in_the_checklist():
    lines = step_lines({"current_step": None, "steps": [
        {"id": "x", "prompt": "Look again.", "status": "open", "optional": True, "object": "red module"}]})
    assert lines[0].text.endswith("(optional)")


# --- the whole app over a real link -----------------------------------------------

def test_app_session_reaches_the_ground_with_its_report(tmp_path):
    from tests.test_app import CLEAN, _events_file, _headless

    g = GroundReceiver(tmp_path / "ground", host="127.0.0.1", port=0, printer=lambda _m: None)
    g.start()
    app = _headless(tmp_path, events=_events_file(tmp_path, CLEAN), downlink=f"127.0.0.1:{g.port}")
    app.start()
    assert app.events_done.wait(10.0)
    summary = app.stop()
    assert summary["log_chain_ok"] and summary["downlink_unacked"] == 0
    local = Path(summary["log"])
    sess = g.sessions[app.session_id]
    end = time.monotonic() + 5
    while sess.report is None and time.monotonic() < end:
        time.sleep(0.05)
    assert (sess.dir / "session.jsonl").read_text(encoding="utf-8") == local.read_text(encoding="utf-8")
    assert sess.chain_ok and sess.report == Path(summary["report"]).read_text(encoding="utf-8")
    assert "12 of 12 steps done" in sess.report
    assert [s["status"] for s in ground_steps(sess)] == ["done"] * 12
    assert sess.info["protocol_id"] == "bas_specimen_v1"
    g.stop()
