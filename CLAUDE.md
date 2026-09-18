# CLAUDE.md — BAS Glovebox HAR Co-Pilot

## Session status — read this first, every session

Living section. Update it before ending any session that changed the
repo, so the next session (yours or a fresh one) doesn't need to be
re-briefed from scratch. Keep it accurate rather than complete — delete
stale entries instead of letting them accumulate.

**Where things stand (last updated: phase-0 build + first review round):**

Phase 0 is built: repo scaffolded, config loader/validator, protocol
engine, debouncer, alert policy, hash-chained session log, kinematics
pure functions, threaded runtime skeleton, replay harness, phase-1
scripts written-not-run. Environment: `.venv/` at repo root, built from
the python.org 3.13 interpreter — **not** the MSYS2 `ucrt64` Python on
PATH, which can't fetch prebuilt wheels here (no working CA bundle) and
fails building `jsonschema`/`rpds-py` from source. Always use
`.venv/Scripts/python.exe` (or activate it) for anything in this repo.
`numpy` was dropped from `pyproject.toml` — it was never actually
imported anywhere; kinematics is pure-Python math.

The phase-0 exit report was delivered and the user ruled on it. Rulings
applied so far (all done, verified with `pytest` + `harness/run_all.py`
green; all six re-confirmed against live code/config in this session —
group-level `after` edges, the `hard_ordering_always_enforced` /
`container_empty_before_close` split, the three `default_constraints`
entries' `type`/`basis`/`severity` fields, the cooldown fixture's four
files, `extract_frames.py`'s naming helpers, and `validate_protocol.py`'s
"approx line N" — nothing has drifted):

1. Added explicit intra-group `after` chains to `bas_specimen_v1.json`
   (`remove_X -> open_X_lid -> stow_X_lid -> close_X_lid -> return_X`
   per module). This changed which violations several synthetic
   fixtures produce — re-verify any NEW fixture against measured engine
   output, don't hand-derive expected timestamps/counts.
2. Removed "a container cannot be closed while a module is outside it"
   from `defaults.yaml`'s `hard_ordering_always_enforced` — it's not a
   physical impossibility, so it stays enforced only as the
   non-overridable `container_empty_before_close` POLICY constraint.
3. Promoted `out_of_order`, `skip`, `wrong_object` to real
   `default_constraints` entries in `defaults.yaml` (type: `sequence`,
   basis: `procedural_integrity`, a new schema enum value). The engine
   now reads their severity/enabled from `constraints_by_id` instead of
   a hardcoded table (`_ENGINE_JUDGMENT_SEVERITY` in `engine.py` is now
   only a defensive fallback).
4. Added `configs/protocols/repeatable_action_test.json` (4 lidless
   modules) + `configs/objects/profile_repeatable_test.yaml` +
   `harness/{synthetic,fixtures}/root_cause_cooldown.json` — the first
   fixture that actually exercises `alert_policy.root_cause_cooldown_s`
   suppression. `bas_specimen_v1` structurally can't: its `remove_from`
   steps each fire once, so `mutual_exclusion_breach`'s constant
   `root_cause_id` never repeats within cooldown. Measured (not
   assumed): 3 violations logged, 2 alerts spoken.
5. `scripts/extract_frames.py` frame naming changed to
   `{clip}_{frame:06d}.jpg` (dropped the placeholder session token).
   Added `resolve_session_id()` / `clip_id_from_frame_filename()`
   helpers there; `scripts/test_mediapipe_gloves.py` now imports the
   latter instead of re-deriving it.
6. `scripts/validate_protocol.py` Finding output now says "approx line
   N" — `src/protocol/lineindex.py` is a regex heuristic, not a real
   JSON-position parser.

Also fixed opportunistically: two real bugs an advisor pass caught
before the exit report (hot reload was entirely unimplemented despite
being a named deliverable — now in `ProtocolEngine.reload_protocol()`;
the lid stow-zone name was hardcoded as `"stow_zone"` instead of read
from the protocol — now `ProtocolEngine._lid_stow_zones`, keyed off
whatever zone id the protocol's own `move_to_zone` step names). Also
swept em-dash characters out of every string literal that actually
reaches `print()` (not docstrings/comments) after noticing they render
as mojibake in this shell and could in principle crash a native
`cp1252` PowerShell console — cosmetic but cheap to fix.

**Three follow-up questions + two owed items — all answered and closed
out; user has since confirmed receipt. Compact record:**

- **(a) Module order for `bas_specimen_v1`: free.**
  `format_resolved_report()` prints an `Ordering:` line
  (`resolve_module_order()` in `loader.py`, sourced from
  `defaults.yaml`'s `default_ordering.module_order` /
  `strict_mode.force_module_order`). Live output:
  `Ordering: free - top-level groups may interleave; group membership
  alone implies no ordering, only explicit `after` edges do`.
- **(b) Violations logged vs. alerts spoken, tracked separately.**
  `ReplayResult.violations_logged` vs `.actual_alerts`; `format_result()`
  / `run_all.py` print both plus a suppressed count. Cascade fixture,
  run in isolation: 6 logged / 4 spoken / 2 suppressed.
- **(c) Debouncer end-to-end through the harness — done, both
  directions.** `harness/replay.py`'s `"raw_observations"` stream shape
  + `debounce_raw_observations()` runs noisy per-frame observations
  through the real `Debouncer`. `harness/{synthetic,fixtures}/
  debounce_raw_observations.json` (`bas_specimen_v1`, k=5/n=8, all
  values measured not hand-derived) has three cases on independent
  keys: (1) a flickering signal that still confirms true at t=1.30 (7th
  observation, 5-of-8); (2) that SAME key then genuinely releasing back
  to false at t=1.60 after 5 consecutive false observations evict the
  true run from the window — proves the debounced state is not
  sticky-true (a stuck-true bug would silently block every future
  re-confirmation of that action, worse than one missed detection); this
  case produces no synthetic ActionEvent by design (the stream shape
  only synthesizes on transitions TO present), so it's checked directly
  against `Debouncer.state()` in
  `tests/test_harness.py::test_debounce_raw_observations_down_transition_is_not_sticky`,
  not via the confirmed-events list. (3) A second, independent key that
  alternates true/false in lockstep and never reaches 5-of-8 either way
  — proves a balanced-noise key produces no spurious confirmation
  (narrower than "distinguishes noise from signal" — see the fixture's
  own `_note`). `pytest` 110/110, `harness/run_all.py` 9/9, both green.
  This fixture's raw-observation count (23, mostly discarded pre-engine)
  skews `run_all.py`'s "mean events/sec" headline upward — expected, not
  a bug, but not a detector-independent throughput figure either.
- **engine.py step tracking: a SET, not a list index.**
  `ProtocolEngine.complete: set[str]` / `.skipped: set[str]` are the
  stored state; `satisfiable_steps()` recomputes a fresh `set[str]` from
  them every call (`src/protocol/engine.py`). No list index anywhere in
  step-tracking.
- **"Syntax errors in most files" — investigated, false as stated; one
  real (cosmetic) issue found instead.** `compileall` clean, `pytest`
  green throughout. What was probably prompting the claim: the earlier
  em-dash sweep's "every string literal that reaches `print()`" missed
  12 sites (multi-line f-strings and `raise SomeError(...)` messages).
  Only `harness/run_all.py:81` was actually seen mojibaking live; the
  other 11 were found by a static scan and fixed on the same basis, all
  12 confirmed clean by re-scan afterward. 12 cosmetic spots out of
  ~15k lines — not "most files." Full detail (exact line list, scan
  methodology) has scrolled out of this log; `git blame` / diff history
  once this repo has version control, or re-derive by scanning for
  `print(`/`raise` calls with non-ASCII args if it ever matters again.
  A permanent guard now exists — see below.

**Non-ASCII-in-output CI gate — added this session, per explicit user
request** (a periodic manual sweep "won't hold"):
`tests/test_no_nonascii_output.py`. AST-based, not a grep: walks
`src/`, `scripts/`, `harness/`, `tests/`, and flags a string literal
only when it is structurally an argument to `print()`/`raise
<Exc>(...)`/`logger.*()` — docstrings and comments are excluded by
construction (never sink-call arguments), matching this project's
existing policy, not the literal `grep -rPn '[^\x00-\x7F]'` the user
first proposed (that flags ~34 files, mostly legitimate docstring
em-dashes; user chose the narrower scope when asked). Verified to
actually catch a regression (reintroduced an em-dash into
`scripts/split.py`, watched the test fail, reverted). No `.git` exists
in this repo yet, so this is a `pytest`-gated check, not a real
pre-commit hook — trivial to wire as one once `git init` happens; user
declined to do that now.

## Your role

You are the senior perception and systems engineer on a four-person team