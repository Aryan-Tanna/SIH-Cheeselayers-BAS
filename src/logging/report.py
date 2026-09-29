"""Human-readable session report: the PS's "timestamped and structured
lightweight text file of the conducted steps with outcomes / status".

Built ONLY from the hash-chained JSONL lines plus the protocol's step
list, so the co-pilot and the ground station (src/ground/receiver.py)
produce the identical report from the same log. The JSONL stays the
record of truth; this is its readable view, never an input.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# How a step ended, from the log's own event lines.
_DONE = {"complete": "DONE", "operator_confirmed": "DONE (operator)"}


def _clock(t: float | None) -> str:
    if t is None:
        return "      -  "
    m, s = divmod(max(0.0, t), 60.0)
    return f"+{int(m):02d}:{s:04.1f}"


def _utc(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return ts


def step_outcomes(events: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per protocol step: status, time since start, how it was seen.
    `steps` = the session snapshot's list (id, prompt, object, optional,
    status); only its not_applicable status is trusted, the rest comes
    from the log so the report can never disagree with it."""
    t0 = next((e["ts_monotonic"] for e in events if e.get("event_type") == "session_start"), None)
    rows = []
    for s in steps:
        sid = s["id"]
        done = next((e for e in events if e.get("event_type") == "step_complete" and e.get("step_id") == sid), None)
        missed = any(e.get("event_type") == "violation" and e.get("violation_type") == "skip"
                     and e.get("step_id") == sid for e in events)
        late = any(e.get("event_type") == "violation" and e.get("violation_type") == "out_of_order"
                   and e.get("step_id") == sid for e in events)
        if s.get("status") == "not_applicable":
            status, t, how = "n/a", None, "not applicable to these props"
        elif done is not None:
            status = _DONE.get(done.get("status") or "", "DONE")
            if late:
                status += ", OUT OF ORDER"
            t = done["ts_monotonic"] - t0 if t0 is not None else None
            conf = done.get("confidence")
            how = ("operator said it was done" if done.get("status") == "operator_confirmed"
                   else f"seen by camera (conf {conf:.2f})" if isinstance(conf, (int, float)) and conf < 1.0
                   else "seen")
        elif missed:
            status, t, how = "MISSED", None, "never done"
        elif s.get("optional"):
            status, t, how = "not done", None, "optional"
        else:
            status, t, how = "not reached", None, "session ended first"
        rows.append({"id": sid, "prompt": s.get("prompt") or sid, "object": s.get("object") or "",
                     "status": status, "t": t, "how": how})
    return rows


def build_report(events: list[dict[str, Any]], steps: list[dict[str, Any]], *,
                 title: str = "", chain_ok: bool | None = None, chain_lines: int | None = None,
                 log_name: str = "") -> str:
    if not events:
        return "Empty session log.\n"
    first, last = events[0], events[-1]
    t0 = next((e["ts_monotonic"] for e in events if e.get("event_type") == "session_start"),
              first["ts_monotonic"])
    rel = lambda e: e["ts_monotonic"] - t0  # noqa: E731
    rows = step_outcomes(events, steps)
    counted = [r for r in rows if r["status"] not in ("n/a",) and not (r["status"] == "not done")]
    done = sum(r["status"].startswith("DONE") for r in counted)
    missed = sum(r["status"] == "MISSED" for r in counted)
    violations = [e for e in events if e.get("event_type") == "violation"]
    anomalies = [e for e in events if e.get("event_type") == "anomaly"]
    commands = [e for e in events if e.get("event_type") in (
        "operator_command", "operator_override", "session_paused", "session_resumed", "protocol_reloaded")]

    out: list[str] = []
    w = out.append
    w("BAS CO-PILOT  -  SESSION REPORT")
    w("=" * 72)
    w(f"Session     : {first.get('session_id', '-')}")
    w(f"Experiment  : {title or first.get('message', '')}")
    w(f"Started     : {_utc(first.get('ts_utc'))}")
    w(f"Last entry  : {_utc(last.get('ts_utc'))}   (duration {_clock(rel(last)).lstrip('+')})")
    if chain_ok is not None:
        w(f"Log         : {log_name}  hash chain "
          + (f"VERIFIED ({chain_lines} lines)" if chain_ok else "BROKEN - the log was altered"))
    w("")
    w(f"RESULT      : {done} of {len(counted)} steps done, {missed} missed, "
      f"{len(violations)} violation(s)")
    w("")
    w("STEPS")
    w(f"  {'#':>2}  {'time':>9}  {'status':<22} step (object) -- how")
    for i, r in enumerate(rows, 1):
        obj = f" ({r['object']})" if r["object"] else ""
        w(f"  {i:>2}  {_clock(r['t']):>9}  {r['status']:<22} {r['prompt']}{obj} -- {r['how']}")
    w("")
    w(f"VIOLATIONS ({len(violations)})")
    if not violations:
        w("  none")
    for e in violations:
        sev = (e.get("severity") or "").upper()
        w(f"  {_clock(rel(e)):>9}  {sev:<8} {e.get('violation_type'):<24} {e.get('message') or ''}")
    if anomalies:
        w("")
        w(f"ANOMALIES ({len(anomalies)})")
        for e in anomalies:
            w(f"  {_clock(rel(e)):>9}  {e.get('message') or e.get('target') or ''}")
    if commands:
        w("")
        w("OPERATOR / SYSTEM")
        for e in commands:
            w(f"  {_clock(rel(e)):>9}  {e.get('event_type'):<18} {e.get('message') or e.get('step_id') or ''}")
    w("")
    w("Times are from session start, on the camera clock (frame capture time).")
    w("The JSONL log is the record of truth; this report is generated from it.")
    return "\n".join(out) + "\n"
