# Resume brief — for whoever's picking this up next

Bridge document, not a replacement for `CLAUDE.md` (loaded automatically
by Claude Code — it is the authoritative brief and rules). This file is
**where things stand right now** and **how to rebuild what git doesn't
carry**. Last updated 2026-09-24.

## What this project is

SIH PS 26174 — offline, CPU-only AI co-pilot watching a fixed camera over
a glovebox rig: tracks a protocol's steps, alerts by voice on skipped /
out-of-order steps, writes a tamper-evident log. Detector + classical
rack-space geometry + deterministic constraint engine. Detail in
`CLAUDE.md`.

## Who does what

- **Parth: Phase 2 code only** — audio/TTS, recorder,
  streamer, GUI, wiring. Needs **only** setup step 1 below (`.venv` +
  `pytest`). No video, frames, labelling or training on Parth's side.
- **Aryan: data, labelling, detector training** (batch9 → v5). New
  weights arrive as a committed `models/*.pt` — so load the detector
  from a config path, never hard-code `bootstrap_v4_best.pt`, and v5 is a
  one-line swap.

## What's done

- **Phase 0** (protocol engine, kinematics, debouncer, alert policy,
  hash-chained log, replay harness) — built, tested, green.
- **Phase 1 data** — 71 clips normalized + frames extracted;
  `manifest/clips.csv` hand-filled. Sessions: S00=48 clips (16 gloved),
  S01=6, S02=8, S03=9 (Dataset63-71). All bare-handed outside S00.
- **Labels** — 450 frames in `labels/batch-1..batch8` (Label Studio
  exports, OBB). Checked: 0 duplicate frames across batches, 0
  near-duplicates across sessions.
- **Detector `bootstrap_v4`** — committed at `models/bootstrap_v4_best.pt`
  (see `models/README.md`). Real held-out split by session:

  | on val S01+S02+S03 (117 frames) | P | R | mAP50 |
  |---|---|---|---|
  | v3 (old) | 0.72 | 0.58 | 0.67 |
  | **v4** | 0.78 | 0.58 | 0.73 |

  Per class v4 mAP50: red_module .92, hand_bare .86, case_closed .71
  (only 13 val boxes — noisy), red_lid .70, yellow_module .68 (recall
  dropped .70→.43 vs v3, cause untested), case_open .66, yellow_lid .56.
  **hand_gloved: unmeasured** (no gloved clip outside S00).
- **Training upgrades** — on-the-fly augmentation
  (`configs/training/augment_v4.yaml`: rotation 180°, flips, blur,
  contrast, CLAHE, sharpen, noise, JPEG via `scripts/photometric_aug.py`);
  `--device 0` GPU training; gloved probe
  (`configs/training/probe_gloved.yaml`, 4 whole S00 clips held out of
  train, scored separately — same session, so it overestimates).

## What's next (in order)

1. **Phase 2 runtime code (Parth) — START HERE, no model or video needed.** The
   team decided (2026-09-24) to build this now and train v5 later; the
   detector is swapped by a single weights path. Order:
   a. **Audio — DONE.** Piper TTS (offline, Win/macOS/Linux; voice
      `models/tts/en_US-lessac-medium.onnx`) + code-synthesized earcons,
      settings in `configs/runtime.yaml`. Flow: engine batch →
      `Announcer.plan()` (the one `AlertManager.decide()` call; spoken
      text = constraint `alert` lines and protocol `prompt`/`success`,
      never engine debug messages) → `AudioWorker` thread → sink.
      Behaviour: warnings interrupt; newer prompts supersede queued
      ones; one prompt per step, first in protocol order, preferring the
      branch the operator is in; no prompts after the terminal step;
      identical alert lines in one batch spoken once; cooldown-suppressed
      violations fully silent. All phrases pre-rendered at load (Piper
      measured 0.4-0.9 s/phrase — too slow at alert time). Persistent
      WASAPI stream on Windows (22 ms vs 91 ms MME). Degrades to
      earcons + printed text if the voice/device is missing. Listen:
      `python scripts/audio_demo.py --all` (`--silent` for no device).
      Hot reload: `Session.reload_protocol()`, then pre-warm the new
      phrases (`speakable_phrases`).
      **Session + voice control (2026-09-24):** `src/runtime/session.py`
      is the single, locked entry point (engine is not thread-safe).
      "Hey BAS, <cmd>" via Vosk (`models/asr/`, grammar-restricted,
      whole-utterance match only): pause (engine frozen, timers stopped,
      voice flushed; events during pause are ignored, NOT credited),
      resume (re-states current step), quiet (tick per completed step,
      alerts still spoken, end-of-experiment still spoken), voice,
      repeat. Skip alerts name the step and object via the profile's
      `spoken_name` ("Missed on the yellow module: Reseal the module.");
      out_of_order names what was expected first, and is dropped when a
      skip in the same instant already names it. Objects not bound to a
      role -> `anomaly` ("Anomaly detected."), no state change, not a
      violation. Harness covers pause/timer/anomaly (12/12). Live-mic
      tested (`scripts/voice_test.py`): exact whole-utterance matching
      accepted only 4/12 real wake utterances (breath/noise before the
      wake phrase, stutters, repeats), so the parser now takes the LAST
      "hey bass" and the command starting right after it; after that
      change 13/17 utterances accepted, all five commands working in
      both one-breath and wake-then-command form. Laptop mic echo
      cancellation removes the co-pilot's own voice from the mic.
   b. **Capture + recorder + stream -- DONE** (`src/runtime/capture.py`,
      `recorder.py`). One libx264 encode (bundled imageio-ffmpeg) feeds
      local MPEG-TS segments + a UDP stream (`stream.url` in
      `configs/runtime.yaml`, default loopback). Measured: TS survives an
      encoder kill (96/105 frames) where MP4 did not (69/105, or 0 when
      teed); an RTSP output inside the encoder stalls it on an
      unreachable server (0-byte recording), so rtsp:// goes through an
      isolated relay process. Video is constant-rate on capture
      timestamps: video offset = log ts_monotonic - t0 (`video.json`).
      Webcam 640x480/720p: encoder 12-15% of one core, 0 frames lost.
   c. **GUI -- DONE** (`src/runtime/gui.py`, Tkinter: no extra deps).
      Live video, checklist naming each step's object, NOW banner,
      events feed, buttons = voice commands (Space/N/R/Q/F5).
   d. **App wiring -- DONE** (`src/runtime/app.py`): validates + prints
      the resolved constraints at start, hash-chained log in `logs/`,
      hot reload on file save (invalid edits rejected, old protocol
      kept), scripted `--events` start at the first camera frame.
      `scripts/run_gui.py` / `scripts/run_copilot.py` (headless).
   e. **NEXT (needs perception):** detections -> semantic events
      (tracker + kinematics + debouncer -> ActionEvent/AnomalyEvent),
      loading `detector.weights` from config. Blocked for real video on
      ArUco/rack geometry (item 3).
   Log schema (2026-09-24): each JSONL line now also carries `target`,
   `severity`, `message` and `extra` (e.g. out_of_order's unmet steps,
   pause length, anomaly kind) -- before, an operator_command line did
   not say which command. Older logs lack them and still verify.
   Loader fix (2026-09-24): protocol config paths now resolve from the
   repo root; launched from another folder, the object profile silently
   failed to load and all six lid steps vanished.
2. **(Aryan)** Label batch9 (80 train + 50 val frames aimed at the weak
   classes) → train v5 with the gloved probe → report val AND probe
   separately → commit to `models/`.
3. **ArUco / rack geometry** — still not started (no `clips_aruco/`, no
   `validate_rack.py`, `zones.yaml` null). Blocks kinematics on real
   video, not the phase-2 items above.

## Setup

Not in git: `clips/`, `clips_norm/`, `frames/`, `runs/`, `.venv/`,
`.venv-train/`, Label Studio's database. **For Phase 2 coding (Parth) you need
step 1 only.** Steps 2-7 are the data/training side (Aryan's machine) —
kept here so it can be rebuilt anywhere if needed.

1. **Runtime venv** (CPU; this is what the product runs on):
   `python -m venv .venv` (3.11+; team uses 3.13), then
   `pip install -e ".[vision,audio,dev]"`, then fix the opencv clash
   documented in `pyproject.toml`:
   `pip uninstall -y opencv-python` and
   `pip install --force-reinstall --no-deps opencv-contrib-python==5.0.0.93`.
   Check `python -c "import cv2; cv2.aruco"`. Then `pytest -q` → **374
   passed**. Phase-2 work needs nothing beyond this step.
2. **Video / frames** (only for labelling or training): get `clips/`
   (71 mp4, ~6.6 GB) from the team, then `python scripts/normalize_clips.py`
   and `python scripts/extract_frames.py`. Frame filenames must match the
   label JSONs — step 4 fails loudly on any missing frame, which is your
   check. If they don't match, ask the team for the `frames/` folder
   (~108 MB) instead.
3. **GPU training venv** (optional, ~11x faster than CPU; training only,
   never the runtime): `python -m venv .venv-train`, then
   `pip install torch==2.14.0 torchvision==0.29.0 --index-url
   https://download.pytorch.org/whl/cu130` (~2 GB; cu128/cu129 have no
   2.14 build), then `pip install ultralytics==8.3.28 pyyaml`.
4. **Dataset** (list every `labels/batch*` file, add new batches):
   `python scripts/convert_labels_to_yolo_obb.py --json labels/batch-1_full.json
   labels/batch-2_full.json labels/batch-3_full.json labels/batch-4_sih.json
   labels/batch5_retrain.json labels/batch6_retrain3.json labels/batch7
   labels/batch8_retrain.json --out-images runs/yolo_dataset_v5/images/train
   --out-labels runs/yolo_dataset_v5/labels/train`, then
   `python scripts/split_yolo_dataset.py --dataset-dir runs/yolo_dataset_v5
   --val-sessions S01,S02,S03 --probe-config configs/training/probe_gloved.yaml`.
   Write `data.yaml` (train: images/train, val: images/val, 8 names in
   `CLASS_ORDER` order) and `data_probe_gloved.yaml` (val:
   images/probe_gloved). Always build into a **fresh** directory: re-running
   the split on an already-split dir deletes the old val frames.
5. **Train**: `.venv-train/Scripts/python scripts/train_yolo_obb.py
   --weights yolov8n-obb.pt --data runs/yolo_dataset_v5/data.yaml
   --augment-config configs/training/augment_v4.yaml --epochs 120
   --patience 40 --name bootstrap_v5 --device 0 --workers 2`.
   Then score it with `workers=0` on Windows (see gotchas).
6. **Pre-labels + next batch**: `scripts/autolabel_remaining_frames.py
   --weights models/bootstrap_v4_best.pt --labelled-images-dirs
   <dataset>/images/train <dataset>/images/val <dataset>/images/probe_gloved
   --out-dir runs/autolabel_predictions_v4`, then
   `scripts/build_review_priority.py --labels-dir
   runs/autolabel_predictions_v4/labels --out
   runs/autolabel_predictions_v4/review_priority.csv --focus-classes
   yellow_module,yellow_lid,red_lid,case_closed`, then
   `scripts/select_label_batch.py --out-dir runs/label_batch9` →
   `import_train.json` / `import_val.json` for Label Studio.
7. **Label Studio** (separate install: `pip install label-studio`): set
   `LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true` and
   `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=<absolute repo path>` before
   `label-studio start`; add Local Files storage at `<repo>/frames`.
   Its database is per-machine — annotations only travel via exports
   into `labels/`. Export often.

## Gotchas that will cost you time

- `ultralytics==8.3.28` needs `numpy.trapz = numpy.trapezoid` before import
  (numpy 2). `train_yolo_obb.py` does it; do it in your own scripts too.
- Do **not** `pip install albumentations` — it drags in
  opencv-python-headless and breaks `cv2.aruco`. Pixel augmentations live
  in `scripts/photometric_aug.py` instead.
- Windows: any ad-hoc Ultralytics val/predict script needs `workers=0`
  (no `if __name__ == "__main__"` guard → dataloader workers hang).
- Resuming a killed training run: re-pass `--augment-config` with
  `--resume` (the augmentation hook is process state, not saved args).
- Hue augmentation must stay tiny (`hsv_h` ≤ 0.02) and never grayscale:
  red vs yellow classes are colour-only. A test enforces this.
- Never split by frame. Never put S00 frames in val "to measure gloves" —
  that's leakage; use the probe, or record gloved clips in a new session.
- `build_review_sheet.py` overwrites `clips.csv` wholesale — never re-run.
  `manifest/clips2.csv` is a deliberate backup — leave it alone.
- Dataset22 has gloved boxes while `clips.csv` says `gloves=false`; the
  team checked it and ruled it fine — leave both as they are.
- `scripts/convert_labels_to_yolo_obb.py` treats "reviewed, zero objects"
  as a real negative and "not reviewed" as skipped — matters for partial
  exports.

## Where to go for more detail

- `CLAUDE.md` — brief, architecture, phase plan, non-negotiable rules.
- `configs/objects/LABELLING_GUIDANCE.md` / `LABELLING_RULINGS.md` —
  class list reasoning and annotation rules.
- `models/README.md` — what each committed weight file is.
