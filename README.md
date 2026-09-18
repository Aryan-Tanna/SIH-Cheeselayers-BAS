# BAS Glovebox HAR Co-Pilot

Offline, edge-native AI co-pilot for Smart India Hackathon PS **26174 —
"AI Human Activity Recognition for On-board BAS Experiments"** (ISRO /
Department of Space).

An astronaut on the Bharatiya Antariksh Station runs a scientific
protocol with no real-time ground support (comms delay, restricted
bandwidth). This system watches a fixed payload camera, tracks protocol
progress against a declarative spec, prompts the next step, alerts by
voice on skipped or out-of-order steps, and writes a tamper-evident log
— fully offline, CPU-only, no internet at runtime.

Full project brief, architecture rationale, and the phase-by-phase build
plan live in [`CLAUDE.md`](CLAUDE.md) — that document is the
specification this repo is built against. This README is an orientation
map on top of it, not a replacement.

## Architecture

Three-way split instead of one end-to-end model:

- **Lightweight vision** identifies objects (phase 2 — no detector
  trained yet).
- **Classical geometry** (`src/kinematics/`) handles microgravity
  physics in rack-relative coordinates — no fixed "up," so no
  gravity-aligned pose assumptions.
- **A deterministic constraint engine** (`src/protocol/`) validates
  procedure sequence against a declarative protocol spec, with no
  probabilistic hallucination in the safety-critical path.

```
configs/          defaults.yaml, protocol schema, protocol/object/zone definitions
src/
  protocol/       constraint engine, debouncer, alert policy, config loader/validator
  kinematics/     pure-function motion/grasp/drift/intent/lid-state math (rack space)
  logging/        hash-chained JSONL session log
  runtime/        threaded capture -> detection -> fusion -> alert pipeline skeleton
harness/          replay.py + run_all.py: headless fixture-driven pipeline tests
scripts/          phase-1 data pipeline (normalize, extract, review, split, ...)
tests/            pytest unit/regression suite
clips/, clips_norm/, frames/, manifest/, labels/, runs/   data pipeline stages (gitignored)
```

The constraint engine tracks a **set** of currently-satisfiable protocol
steps (not a list index), consumes semantic action events, and emits
step completions or violations. Everything a protocol enforces is data
(`configs/defaults.yaml` + a protocol JSON), not hardcoded logic — see
`CLAUDE_addendum_protocol.md` for the inheritance/override rules.

## Status

Phase 0 (engine, harness, no video) is built and green. Phase 1 (data
pipeline) is running against a 5-clip pilot corpus. See `CLAUDE.md`'s
**Session status** section for exactly what's done, what's broken, and
what's an open decision as of the last session — that section is kept
current and capped short on purpose; check it before assuming anything
below still holds.

## Setup

Requires the **python.org** Python 3.13 interpreter, not MSYS/MinGW
Python — on Windows with MSYS installed, `python` on `PATH` may resolve
to the wrong one and fail to fetch prebuilt wheels (no working CA
bundle), then fail building `jsonschema`/`rpds-py` from source.

```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The phase-1 data pipeline additionally needs the `vision` extra
(Pillow; OpenCV/YOLO/MediaPipe once phase 2 needs them) and `ffmpeg`
+ `ffprobe` on `PATH`:

```
.venv\Scripts\python.exe -m pip install -e ".[vision]"
```

Always invoke `.venv\Scripts\python.exe` explicitly (or activate the
venv) — do not rely on a bare `python`/`py` resolving to it.

## Running things

```
# Full test suite
.venv\Scripts\python.exe -m pytest

# Synthetic fixture corpus through the replay harness (engine + alerts + logging,
# no detector/video needed — this is the headline correctness metric)
.venv\Scripts\python.exe harness\run_all.py

# Validate a protocol JSON (ordering cycles, unresolved roles/zones, missing
# `basis` fields, etc. -- reports Finding lines with approximate source line numbers)
.venv\Scripts\python.exe scripts\validate_protocol.py configs\protocols\bas_specimen_v1.json
```

The resolved-constraint report (which defaults are enforced, which the
protocol overrode, ordering) is `src/protocol/loader.py`'s
`format_resolved_report()` / `print_resolved_constraints()` — not
currently wired to a CLI entrypoint, so it's called from Python
directly:

```python
from pathlib import Path
from src.protocol.loader import resolve, print_resolved_constraints
print_resolved_constraints(resolve(Path("configs/protocols/bas_specimen_v1.json"), Path("configs/defaults.yaml")))
```

Phase-1 data pipeline, in order, once real clips are in `clips/`:

```
.venv\Scripts\python.exe scripts\normalize_clips.py      # VFR->CFR30, rotate to landscape -> clips_norm/
.venv\Scripts\python.exe scripts\extract_frames.py        # sample + dedup -> frames/
.venv\Scripts\python.exe scripts\build_review_sheet.py     # manifest/clips.csv + contact sheet -- STOP for human review
.venv\Scripts\python.exe scripts\separability_check.py     # class-list decision support
.venv\Scripts\python.exe scripts\split.py                  # train/val split by session_id, after review
```

`build_review_sheet.py` is a hard checkpoint: `manifest/clips.csv`'s
`session_id` and the guessed columns must be human-reviewed before
anything downstream is trustworthy. A guessed column with no honest
phase-1 signal (no detector exists yet) reports `unimplemented`, not a
fabricated guess — see that script's docstring for exactly which
columns and why.

Rotation is decided automatically but is not blindly trusted: a
portrait clip with no rotation metadata gets a **default** guess
(flagged `defaulted, verify` in `normalize_clips.py`'s output and in
`manifest/rotation.csv`), which a human can override by editing that
file and marking the row `confirmed`.

## Testing philosophy

- **Measure, never hand-derive.** Fixture expected-values and thresholds
  come from running the real code and reading its actual output, not
  from calculating what "should" happen — see `tests/test_normalize_clips.py`
  and `tests/test_harness.py` for examples using real measured numbers
  from the pilot corpus.
- **Never tune against a single clip.** Thresholds live in `configs/`
  and are calibrated against the aggregate tuning set.
- **No clip ID, filename, or timestamp anywhere under `src/`** —
  anti-overfitting rule enforced by convention, checked in review.
- A capability with no honest signal reports itself as absent
  (`unimplemented`), never as a confident-looking placeholder.
