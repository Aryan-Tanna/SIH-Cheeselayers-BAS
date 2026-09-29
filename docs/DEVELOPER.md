# Developer guide

Everything a developer needs that the README keeps out of the way.
The authoritative spec and rules are in [`CLAUDE.md`](../CLAUDE.md);
current state and rebuild steps are in [`RESUME.md`](../RESUME.md).

## Code map

```
configs/          defaults.yaml (safety rules), protocol.schema.json, protocols/*.json,
                  objects/*.yaml (props -> detector classes), runtime.yaml (camera, audio, link)
src/protocol/     constraint engine, debouncer, alert policy, loader/validator, editor model
src/perception/   detector (ONNX), fusion (detections -> step events), hand pose, ArUco rack
src/kinematics/   pure-function motion/grasp/drift/intent/lid maths (unit-tested; fingers.py live)
src/logging/      hash-chained JSONL session log + readable report
src/link/         Earth downlink (sender, receiver, upload-later, Mission Control window)
src/runtime/      app, GUI, start screen, protocol editor, voice/audio, recorder, offline guard
harness/          replay harness + synthetic fixtures (the headline correctness metric)
scripts/          run_gui.py, ground_station.py, send_to_earth.py, build_app.py, data + training
tests/            pytest suite
```

## Runtime scripts

```
.venv\Scripts\python.exe scripts\run_gui.py                        # start screen (Space station / Earth)
.venv\Scripts\python.exe scripts\run_gui.py --role earth --receive  # Earth, receiving at once
.venv\Scripts\python.exe scripts\ground_station.py                 # Mission Control only (Python + Pillow)
.venv\Scripts\python.exe scripts\send_to_earth.py <earth-ip>       # send stored sessions later
.venv\Scripts\python.exe scripts\run_copilot.py --source <video>   # headless run, prints a summary
.venv\Scripts\python.exe scripts\build_app.py --zip                # Windows app -> dist/
```

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
