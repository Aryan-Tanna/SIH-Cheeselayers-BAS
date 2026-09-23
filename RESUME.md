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

- **Phase 1 held-out set (S03) — added, this is new.** The 9 test clips
  are now `Dataset63-71_glovebox`: normalized, 588 frames extracted,
  `manifest/clips.csv` at 71/71 rows. They are slab props (red + yellow
  rectangular blocks, so `lid_type=none`), bare hands, overhead, fixed
  camera, on a white desk rather than the tub rig. Verified: **0 of the
  183 training frames belong to S03.**

## The one number you should NOT trust yet

Both models report mAP50 ≈ 0.98 on their own validation split — but that
"val" split is currently **the same images as train** (a placeholder,
because no genuinely held-out session existed when they were trained).
That number measures memorization, not real-world accuracy.

`scripts/eval_heldout.py` is what replaces it. It has three modes; two
have already been run against S03, and the third is the open task.

**Already measured on all 588 held-out frames, no annotation required**
(`--diagnose`). Three classes are ruled out by the manifest itself — a
`gloves=false` clip cannot contain `hand_gloved`, a `lid_type=none` clip
cannot contain `red_lid`/`yellow_lid` — so every such box is a certain
false positive:

| check | result |
|---|---|
| `hand_gloved` false positives | **0** in 588 frames |
| `red_lid` false positives | 18 boxes / 18 frames (3.1%), mean conf 0.45 |
| `yellow_lid` false positives | 6 boxes / 6 frames (1.0%), mean conf 0.36 |
| `case_open` **and** `case_closed` in one frame | 10 frames (1.7%) |
| duplicate same-class boxes (IoU≥0.55) | 8 boxes across 8 frames (1.4%) |
| frames with zero detections | **0** (0.0%) |

Every false positive above is low-confidence. Raising `--conf` from 0.25
to 0.50 cuts them 24 → 6 and case contradictions 10 → 1, for 8% fewer
boxes overall. **Do not adopt 0.5 on that basis yet** — those 8% could
be lost true positives, and nothing here can tell the difference.
Recall is not measurable without ground truth.

**Also measured:** the detector runs at **11.3 FPS on CPU** (88.7 ms
mean per frame, p95 111 ms) against `CLAUDE.md`'s 25+ FPS / sub-150 ms
target. That is the uncompiled PyTorch path — no ONNX or OpenVINO
export has been attempted, which is the obvious lever and is exactly
what the architecture thesis's "lightweight compiled vision" assumes.

## Setup steps

Already done in this clone (`.venv/` exists, 217 tests green). Kept
here because it is the part that wastes a fresh session's afternoon.

0. **`best.pt` may reach you unzipped.** A PyTorch checkpoint is a zip
   archive, and it arrived here as a *directory* (`best.pt/best/...`)
   rather than a file — torch and ultralytics both reject that. Re-zip
   its contents with `ZIP_STORED`, keeping the internal `best/` prefix,
   and write the result to
   `runs/train/bootstrap_v2/weights/best.pt`. Confirm you got the right
   checkpoint before trusting it: `train_args` should read 50 epochs,
   imgsz 640, `model: runs/train/bootstrap_v1/weights/best.pt`.
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
4. `pytest -q` — **217 passed** (163 original + 54 for
   `scripts/eval_heldout.py`).

## Your task: the one step left

Steps 1–3 below are **done**. Step 4 is the open one, and it needs a
human, because ground truth does not exist and cannot be generated.

1. ~~Clips staged in `clips/`.~~ Done — originals preserved in
   `test_clips/`, name mapping in `manifest/test_clip_source_map.csv`.
2. ~~`normalize_clips.py --only` then `extract_frames.py --only`.~~
   Done — all 9 clips were already CFR 30 and landscape with no
   rotation tags, so normalize was a straight transcode. 588 frames.
3. ~~Rows added to `manifest/clips.csv`.~~ Done — `session_id=S03`,
   all four guessed columns filled at `_conf 1.0` from visual
   confirmation across every clip at several timestamps.
   `manifest/clips.csv.bak_pre_S03` is the pre-append backup.
4. **Annotate the validation sample.** 63 frames (7 per clip, evenly
   spread through each clip) are waiting in
   `runs/eval_heldout/S03_annotation_tasks.json`:

   ```
   label-studio start          # see the LS env vars below
   # import that JSON, annotate, export as JSON, then:
   python scripts/eval_heldout.py --ground-truth <your_export>.json
   ```

   That prints per-class precision / recall / F1 / AP50 and the first
   honest mAP50 this project has ever had.

   **The tasks are deliberately blank, not pre-labelled.** `--prelabel`
   exists and would be much faster to review, but this model's
   characteristic error is a box that is loose by 10–25% rather than a
   box that is missing, and a reviewer correcting pre-filled boxes
   tends to accept one that looks about right. That would quietly
   rewrite the ground truth toward the model and inflate precisely the
   IoU-sensitive numbers being measured. Draw validation boxes cold.

   Two classes cannot be scored from this session at all: `red_lid` and
   `yellow_lid` have zero true instances in slab-prop clips, and they
   are already the weakest classes in training (86 and 63 boxes). The
   script reports their false positives and prints `-` for precision
   and recall rather than `0.0`, since "untestable here" and "failed"
   are different claims. **Scoring those two needs a held-out `jar`
   session, which does not exist yet** — worth shooting.

**Do not merge these frames into the training set.** The whole point is
that `bootstrap_v2` has never seen them. `eval_heldout.py` hard-fails if
any S03 frame turns up in `runs/yolo_dataset/images/train`.

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
- `scripts/eval_heldout.py --diagnose` is worth re-running after any
  retrain. It needs no annotation, so it is free, and the three checks
  it makes (manifest-ruled-out classes, `case_open`+`case_closed` in one
  frame, duplicate same-class boxes) cannot be gamed by a model that has
  memorized its training set — unlike the mAP number.
- `runs/yolo_dataset/` was rebuilt from `labels/*.json` in this session
  and reproduces exactly: 183 images, 973 boxes. Its val split is still
  the train==val placeholder; `eval_heldout.py` does not touch it and
  does not fix it. Pointing that val split at S03 would be the natural
  follow-up once S03 has ground truth.
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
