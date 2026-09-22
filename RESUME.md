# Resume brief — for whoever's picking this up next

This is a bridge document, not a replacement for `CLAUDE.md`. Claude Code
loads `CLAUDE.md` automatically at the start of any session in this repo —
read that first, it's the authoritative project brief (mission context,
architecture, the phase-0/1/2 plan, the non-negotiable rules). This file
explains **where things actually stand right now** in plainer terms, and
what your specific next steps are.

## What this project is

SIH PS 26174 — an offline, edge-native AI co-pilot that watches a fixed
camera over a glovebox rig, tracks a scientific protocol's steps, and
alerts by voice on skipped/out-of-order steps. Three-way split: a
lightweight object detector (this doc's subject), classical geometry for
microgravity-safe positioning, and a deterministic constraint engine for
sequence validation. Full detail in `CLAUDE.md`.

## What's done

- **Phase 0** (protocol engine, kinematics, debouncer, alert policy,
  hash-chained logging, replay harness) — built, tested, green.
- **Phase 1 data pipeline** — all 62 raw clips normalized, frames
  extracted, `manifest/clips.csv` fully filled in by hand (prop_family,
  lid_type, gloves as literal `true`/`false`, camera_angle, session_id,
  partial notes). Sessions: `S00`=48 clips, `S01`=6, `S02`=8.
- **Object detection labelling** — 8-class list finalized (see
  `configs/objects/LABELLING_GUIDANCE.md` for the reasoning,
  `configs/objects/LABELLING_RULINGS.md` for the quick-reference
  annotation rules). **183 frames manually labelled** across
  `labels/batch-{1,2,3,4}_full.json` (original 157) +
  `labels/batch5_retrain.json` (26 more, reviewed from an auto-label
  pass). Labelled in OBB (rotated box) format — Label Studio's
  `(x, y, width, height, rotation)`, top-left-corner pivot, clockwise
  degrees. `scripts/convert_labels_to_yolo_obb.py` converts this to
  Ultralytics' 4-corner YOLO-OBB training format.
- **Two bootstrap detectors trained** (CPU only, `yolov8n-obb`):
  `bootstrap_v1` (157 frames, 80 epochs) → fine-tuned into
  `bootstrap_v2` (183 frames, 50 more epochs). **`best.pt` you were
  given is `bootstrap_v2`'s checkpoint** — put it at
  `runs/train/bootstrap_v2/weights/best.pt` in your clone (that path is
  what every script defaults to; recreate the directories, they're
  gitignored).
- **`frames/` you were given** — same folder as `frames/` in `.gitignore`,
  2056 total extracted frames, of which 183 are the labelled ones above.
  Drop it at the repo root as `frames/`.
- 163 tests passing (`pytest -q` from repo root once your venv is set up).

## The one number you should NOT trust yet

Both models report mAP50 ≈ 0.98 on their own validation split — but that
"val" split is currently **the same images as train** (a placeholder,
because no genuinely held-out session existed when they were trained).
That number measures memorization, not real-world accuracy. **Your test
clips are what fixes this** — see below.

## Setup steps

1. `python -m venv .venv` (3.11+), then `pip install -e ".[vision]"`.
2. Two environment bugs are already documented as comments right next to
   the relevant lines in `pyproject.toml` — read them, they will bite you
   otherwise:
   - `ultralytics` transitively installs `opencv-python`, which corrupts
     the pinned `opencv-contrib-python` (specifically breaks `cv2.aruco`).
     Fix: `pip uninstall -y opencv-python && pip install --force-reinstall
     --no-deps opencv-contrib-python==5.0.0.93`.
   - `ultralytics==8.3.28` calls `numpy.trapz`, removed in numpy 2.x. Any
     script that trains/validates needs `numpy.trapz = numpy.trapezoid`
     monkey-patched before importing `ultralytics` — see the top of
     `scripts/autolabel_remaining_frames.py` for the pattern.
3. Place `frames/` and `best.pt` as described above.
4. `pytest -q` — should be 163 passed before you touch anything else.

## Your task: turn your test clips into the first real validation set

1. Put your raw clip(s) in `clips/` (gitignored, that's fine).
2. `python scripts/normalize_clips.py --only <clip_id(s)>` then
   `python scripts/extract_frames.py --only <clip_id(s)>` — `--only`
   does a scoped run, won't touch the other 62 clips' state.
3. Add a row per clip to `manifest/clips.csv` by hand: `session_id`
   should be a new value (`S03` — S00/S01/S02 are taken), fill
   `prop_family`/`lid_type`/`gloves`/`camera_angle` with `_conf: 1.0`
   each since you're filling them as a human, not guessing. See
   `manifest/clips.csv`'s existing rows for the exact value vocabulary
   (`gloves` MUST be literal `true`/`false`, nothing else —
   `scripts/test_mediapipe_gloves.py` exact-matches those strings).
4. **Do not merge these frames into the training set.** The entire point
   is that `bootstrap_v2` has never seen them. Run inference with
   `best.pt` against them and compare against what you know is actually
   in the frame — that gives a real precision/recall number for the
   first time in this project. There isn't a script for this comparison
   yet; `scripts/autolabel_remaining_frames.py` will run the inference
   part (point `--frames-dir` at just your new clip's extracted frames),
   but the "compare against ground truth and report accuracy" step needs
   writing. Good first thing to ask your Claude Code session to build.

## Other things worth knowing before you dig in

- `scripts/convert_labels_to_yolo_obb.py`'s `parse_task()` distinguishes
  "nobody has reviewed this frame yet" (skipped) from "reviewed and
  confirmed zero objects" (kept as a real negative example) — this
  matters if you ever export a partial Label Studio review batch.
- `scripts/autolabel_remaining_frames.py` purges its own output directory
  before writing, specifically so stale predictions from an older model
  version don't linger in the review queue after a frame gets merged
  into training. If you fork this script, keep that behavior.
- `scripts/build_review_priority.py` turns the auto-label predictions
  into a sorted CSV (zero-detection frames first, then ascending
  confidence, lid-class detections flagged separately — lids are the
  weakest class, fewest/smallest training examples).
- Label Studio: install separately (`pip install label-studio`, not in
  this project's venv). To review pre-labelled frames you'll need
  `LOCAL_FILES_SERVING_ENABLED=true` and `LOCAL_FILES_DOCUMENT_ROOT=<your
  clone's absolute path>` set **before** `label-studio start` — note
  there is no `LABEL_STUDIO_` prefix on these, despite what you'd guess.
- `manifest/clips2.csv` is a deliberate backup someone made of `clips.csv`
  before a bulk value fix — leave it alone, don't merge or delete it.
- `build_review_sheet.py` overwrites `clips.csv` wholesale if re-run —
  do not run it again, it would destroy all the hand-filled columns.

## Where to go for more detail

- `CLAUDE.md` — full project brief, architecture, phase plan, the
  non-negotiable rules (anti-overfitting, no clip IDs in `src/`, etc.),
  and a "Session status" scratchpad at the top with terser/denser notes
  than this document.
- `configs/objects/LABELLING_GUIDANCE.md` — why the class list is what it
  is, the method for deciding a class for a new prop family.
- `configs/objects/LABELLING_RULINGS.md` — one-page quick reference for
  annotation rules if you end up labelling more frames.
