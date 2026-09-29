# Resume brief — for whoever's picking this up next

Bridge document, not a replacement for `CLAUDE.md` (loaded automatically
by Claude Code — it is the authoritative brief and rules). This file is
**where things stand right now** and **how to rebuild what git doesn't
carry**. Last updated 2026-09-25.

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
- **Labels** — 1032 unique frames: `labels/batch-1..batch9`, `batch13`, plus
  `labels/dedup/batch10_dedup_v2.json`, `batch11_dedup.json`,
  `batch12_dedup.json`. batch12 re-labelled 27 batch10 frames: batch12 kept
  for 23 (fixes: hand_gloved on the case, yellow_lid on a slab, missing
  cases), batch10 kept for 4 where batch12 was wrong (Dataset59_000077,
  63_000041, 68_000073, 55_000034 -- judged side by side). The raw
  `batch10`/`batch11` exports overlap batch9 (100 identical frames +
  Dataset69_000036) and the converter hard-fails on duplicates, so build
  from the dedup copies, never the raw ones. 0 cross-session
  near-duplicates (dHash <= 3). S04 (Dataset72-82, new overhead tub rig,
  jars, bare) = 0 labelled; v4 pre-labels in
  `runs/autolabel_predictions_v4_s04/label_studio_predictions_S04.json`.
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
      LAN-tested 2026-09-24 (`run_gui.py --stream-to <ip>` -> phone VLC,
      `udp://@:5000`, home Wi-Fi): video in 1-2 s, ~2 s glass-to-glass
      (mostly VLC's default ~1 s network cache), smooth, reconnect <= 2 s
      (keyframe every 2 s). Not yet tested: a PC receiver, RTSP server.
      Network CAMERA tested the other way round (phone = rack camera):
      DroidCam app -> `run_gui.py --source http://<phone-ip>:4747/video`
      (close the DroidCam PC client first: the phone allows one viewer).
      ~0.05 s delay, 1280x720 at ~26 fps, app kill/reopen recovered by
      itself in seconds. GOTCHA: the DroidCam PC client installs a
      virtual "DroidCam Audio" mic and makes it the Windows default --
      "Hey BAS" then hears only dither (samples -1/0/+1). The co-pilot now
      prints/shows which mic it uses and flags it SILENT after 8 s; fix
      by resetting the Windows default input or `voice_control.
      input_device: "Microphone Array"` (name match, any host API).
   c. **GUI -- DONE** (`src/runtime/gui.py`, Tkinter: no extra deps).
      Live video, checklist naming each step's object, NOW banner,
      events feed, buttons = voice commands (Space/N/R/Q/F5).
   d. **App wiring -- DONE** (`src/runtime/app.py`): validates + prints
      the resolved constraints at start, hash-chained log in `logs/`,
      hot reload on file save (invalid edits rejected, old protocol
      kept), scripted `--events` start at the first camera frame.
      `scripts/run_gui.py` / `scripts/run_copilot.py` (headless).
   e. **Perception -> events -- BUILT (v1, 2026-09-24).**
      `src/perception/detector.py` (weights from config, classes checked
      BY NAME against the profile at load: v5 = one-line swap, fails
      loudly if it drops a class), `src/perception/fusion.py` (per-object
      k-of-n; container open/close + module remove/return; image-space
      containment), `src/runtime/perception_stage.py` (newest frame only,
      capture timestamps). On by default with a camera; `--no-perception`.
      GUI draws boxes ([D]) + DET badge. Same protocol on any props:
      `--profile configs/objects/profile_rect.yaml` (slabs, 6 steps) or
      `profile_mixed.yaml` (red jar + yellow slab, 9 steps).
      Scored on real clips (`scripts/replay_clip.py`, fixtures in
      `harness/clip_fixtures/`, clips in gitignored `test_clips/`):
      tune (Aryan's train1-3) 10/12 events, held-out (Parth's test1-2)
      5/13 -- v4 barely detects an OPEN container in Parth's oblique
      view (13% of frames vs 80% in Aryan's). test2's two-objects-out
      breach IS detected. Live on test2: 9.8 det-fps / 115 ms with 1080p
      recording, 16.7 / 74 ms without. Known limits: top-down returns up
      to ~3 s early (module hovering above box; a hand-off rule was
      tried and reverted: no gain); lid open/close/stow not perceived
      (operator "next step"). NEEDS: v5 trained with frames from Parth's
      setup (not test1/test2); Parth to confirm the test fixture times.
      train1-3 were NOT in v4's training data (S00 only, per Aryan):
      the high scores on Aryan's setup are real generalization to new
      recordings of the same setup; the gap on Parth's is the viewpoint.
   Harness (2026-09-24): alerts are planned by the live Announcer, so
   `expected_alerts` = SPOKEN utterances (cascade 4 -> 1, skipped_step
   3 -> 2), plus `expected_missed_steps` == union of the alerts'
   `step_ids`. Both are needed: with one alert per missed step, the
   4/min rate cap silently dropped the 5th missed step from the voice.
   No time-based debounce: all end-of-run skips arrive in one engine
   batch already, so a window would only add alert latency.
   Fixes 2026-09-25 (found running the GUI on the phone camera):
   (1) ENGINE: a condition-skipped step counted as "done" for ordering,
   so with slab props (lid steps skipped) return_a/return_b were due as
   soon as the container opened -- a never-removed module could be
   "returned" with no out_of_order. Ordering now passes THROUGH skipped
   steps (`ProtocolEngine.prerequisites`). (2) CPU: torch and the speech
   engine (onnxruntime) each claimed every core; the first detection
   took 5.4 s and a short session saw none. Detector warms up at load,
   torch = physical cores - 2 (`detector.threads`), speech = 2 threads
   (`audio.tts.threads`): first detection now 0.9 s after start.
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
3. **ArUco / rack geometry -- BUILT (2026-09-25), fusion not switched yet.**
   `src/perception/rack.py`: markers (DICT_4X4_50, IDs 1-4, 49 mm, flat on
   the tub floor) -> image-to-floor homography in mm from ANY visible
   marker (RANSAC when >=2; unknown IDs ignored -- wall reflections gave
   ID17), 1 s hold, else image space. Layout calibrated from video
   (`scripts/calibrate_rack.py --clips clips_Aruco` -> `configs/rack.yaml`):
   on clips NOT used for fitting, rack known 100% of frames, 1.0 px
   median reprojection, half-vs-all layout <= 0.9 mm. Runs in the
   perception thread (~12 ms/1080p frame); live on an ArUco clip: det
   15-17 fps, 51-58 ms, rack known 98.5% of samples (rest = startup).
   Log `geometry_status` = rack/image per line. GUI: RACK badge, marker
   overlay, "Rack setup [K]" (ArUco type / IDs / size, Auto-detect,
   Calibrate from live camera 4 s, Save & apply live). Tilt: geometry
   tests pass to 50 deg; simulated tilt on real frames: markers found
   fine to 50 deg, 71% of frames at 60, none at 70. Rack-space
   CONTAINMENT built in fusion behind `perception.geometry` (image | auto),
   DEFAULT image: without a rack pose it is event-identical to before
   (300 random streams, 6689 events, 0 diffs). auto = module centre vs the
   container's ROTATED floor footprint in mm, closed footprint kept as the
   interior while open (open box measured 1.15-1.8x the closed area = lid
   flap). On the 20 S05 clips (`scripts/cache_rack_detections.py` +
   `scripts/compare_geometry.py --sheet`): 231 vs 227 events, 55
   disagreements, nearly all jars HELD at the rim, where both geometries
   flicker -- no clear winner; needs 2-3 hand-traced S05 fixtures to decide.
   Rack space does NOT fix hover (no height); that needs the grasp signal.
   `zones.yaml`: container_interior measured (reference only, the case
   moves ~100 mm between clips); stow_zone unset = team decision. Live testing needs the 4 markers taped in
   the same place (or re-Calibrate in the GUI after re-taping).

## Added 2026-09-26

- **v5 detector** (runtime default; `models/README.md`). Leakage check:
  nearest-train-frame similarity (32x32 grey correlation, 1 = identical):
  S01 test .39 (nothing like train), S03 .70 (closest = S02: same slab
  setup, other recordings), S00 test clips .92 (~same-clip level .94 ->
  optimistic, as labelled). No markers in any S00 clip; S05 vs S00 .47.
  Per session v4 -> v5 mAP50: S01 .859 -> .917 (clean gain), S03 .524 ->
  .775 (partly learned from the similar S02 setup).
- **Pseudo-label experiment v6p** (`runs/yolo_dataset_v6p`: v5 train + 1197
  train-side frames labelled by v5 itself, conf >= 0.5; test frames
  excluded). Crashed at epoch 70/120 on SYSTEM RAM (0.3 GB free: the IDE's
  language server held 7 GB), weights kept. At epoch 70, S01+S03 mAP50
  .896 vs v5 .892 (S01 .918 vs .917, S03 .779 vs .775) = no real gain.
  Conclusion: training on v5's own labels does not help; label the frames
  v5 is unsure about instead (`runs/autolabel_predictions_v5/`, 2650 frames).
- **Verified S05 fixtures** (`harness/clip_fixtures/Dataset{12,15,19}_
  glovebox_ARUCO.json`, drafted by Claude from 1 fps strips, checked by
  Aryan): v5 finds 17/18, image and rack geometry alike; the miss is the
  hover case (jar uncapped right above the open case). `scripts/
  replay_clip.py clips_norm/<clip>.mp4 --geometry image|auto`.
- **attended_while_open** (defaults.yaml): a module with its lid off and
  no hands in view for grace_s (5) -> one warning `unattended_open_module`.
  Whole camera view = stow area. Hands = profile's non-role classes, k-of-n
  (`perception.hands_k/n`). GUI badge shows the running timer. Harness has
  `unattended_open_module` + `attendance_lids_on` (14/14); the harness now
  ticks timeouts at 4 Hz between events, as live.
- **Protocol editor** (GUI button / key E; `src/runtime/protocol_editor_gui.py`,
  logic in `src/protocol/editing.py`): Steps tab (add/edit/delete/move
  steps and groups from the fixed action set, renames follow `after`
  refs) and Rules tab (every default rule: on/off, severity, timer, spoken
  alert; non-overridable ones LOCKED). Saves only through the validator;
  "Save as new experiment" writes `configs/protocols/<name>.json` and
  switches the running session to it (`CopilotApp.use_protocol`).
  Overwriting `bas_specimen_v1.json` asks first (harness depends on it).
  Note: the validator bans colour/shape words in ids/targets/roles, NOT in
  spoken prompts.



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
   Check `python -c "import cv2; cv2.aruco"`. Then `pytest -q` → **418
   passed**. Phase-2 work needs nothing beyond this step.
2. **Video / frames** (only for labelling or training): get `clips/`
   (71 mp4, ~6.6 GB) from the team, then `python scripts/normalize_clips.py`
   and `python scripts/extract_frames.py`. Frame filenames must match the
   label JSONs — step 4 fails loudly on any missing frame, which is your
   check. If they don't match, ask the team for the `frames/` folder
   (~108 MB) instead. `extract_frames.py` reads per-clip dHash thresholds
   from `manifest/extract_overrides.csv` (S04 = 3: the default 6 kept only
   6-25 frames on the far tub view) -- keep that file, or S04 frame
   indices change under existing labels.
3. **GPU training venv** (optional, ~11x faster than CPU; training only,
   never the runtime): `python -m venv .venv-train`, then
   `pip install torch==2.14.0 torchvision==0.29.0 --index-url
   https://download.pytorch.org/whl/cu130` (~2 GB; cu128/cu129 have no
   2.14 build), then `pip install ultralytics==8.3.28 pyyaml`.
4. **Dataset** (list every `labels/batch*` file, add new batches):
   `python scripts/convert_labels_to_yolo_obb.py --json labels/batch-1_full.json
   labels/batch-2_full.json labels/batch-3_full.json labels/batch-4_sih.json
   labels/batch5_retrain.json labels/batch6_retrain3.json labels/batch7
   labels/dedup/batch8_retrain_dedup.json labels/batch9 labels/dedup/batch10_dedup_v2.json
   labels/dedup/batch11_dedup.json labels/dedup/batch12_dedup.json labels/batch13
   labels/dedup/batch14_dedup.json
   (batch14 raw export = the whole Label Studio project: use the dedup copy -- its 99 new
   frames + the Dataset47_glovebox_000000 case_closed fix, which is why batch8 is the
   dedup copy without that frame. v6 was built this way into runs/yolo_dataset_v6.)
   --out-images runs/yolo_dataset_v5/images/train
   --out-labels runs/yolo_dataset_v5/labels/train`, then
   `python scripts/split_yolo_dataset.py --dataset-dir runs/yolo_dataset_v5
   --val-sessions S01,S03,S05 --probe-config configs/training/split_v5_s00_test.yaml`
   (v5 split, chosen 2026-09-25: test = S01 + S03 + S05 + 9 whole S00 clips;
   train = rest of S00 + S02 + S04; built in `runs/yolo_dataset_v5`). S05 =
   the 20 ArUco clips (raw in `clips_Aruco/`, normalize with
   `--clips-dir clips_Aruco`), the only held-out session on the demo-like
   tub rig; label `runs/label_batch12/batch12_S05_test_import.json` (60). Next labels:
   `runs/label_batch12/batch12_S04_import.json` (100 S04) +
   `batch12_priority_import.json` (100 train-side, 80 jar) -- export as
   batch12, add to the --json list, rebuild the dataset dir fresh. `data.yaml` val =
   both test parts (model selection); score `data_test_sessions.yaml` (honest,
   unseen sessions) and `data_test_s00.yaml` (same session, overestimates)
   separately. (v4 used `--val-sessions S01,S02,S03 --probe-config
   configs/training/probe_gloved.yaml`.)
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

## Robustness pass (Parth side, 2026-09-28)

Found in the live DroidCam run of 2026-09-26 (handheld phone, busy room):
a 0.8 s open->closed flicker ended the protocol at 54 s; red chairs and
clothing were detected as the red module (conf 0.81).
- `perception.container_min_hold_s` / `module_min_hold_s` (both 1.0):
  a new state must hold its votes that long. Swept with v5 on the tune
  clips (0-1.5 s no loss, 2.0 s drops 10/12 -> 6/12) and the live
  recording as a stress clip (flips 62 -> 30, anomalies 22 -> 11). Does
  NOT fix a moving camera (that session's "closed" lasted 2.9 s): the
  camera must be fixed.
- `perception.workspace` (OFF by default): drop container/module
  detections outside the rig -- rack space (layout + margin_mm) when the
  ArUco pose is known, else an optional image `roi`. Hands never dropped.
  Unit-tested; NOT validated on marker video -- Aryan: run
  `scripts/replay_clip.py --geometry auto` on clips_Aruco with margin_mm.
- v5 on the 5 clips (stride 3): tune 10/12, held-out (Parth test1/test2,
  verified NOT in v5 training labels) 11/13 -- was 5/13 with v4.
- Note: `runs/label_batch_v5` proposed ids Dataset75_desk/76_desk, which
  clash with Aryan's Dataset75/76_glovebox -- renumber if ever used.

## Module lids from perception (Parth side, 2026-09-28)

`SceneFusion` now emits the jar lid steps (profiles with `lid_class_id`:
jar, mixed; slab profile unaffected). Per module, a lid vote
(`perception.lid` in runtime.yaml: k 3 of n 5, hold 0.3 s):

- **detached** = some `red_lid` box lies off the `red_module` box
  (< 0.3 of the lid box on the body) -> `open(module_a)`. It is "some lid
  off", not "no lid on": with the cap off, v5 also fires `red_lid` on the
  open jar mouth (overlap 0.9-1.0 for the whole detach in train1/train2).
- detached lid **in view** -> `move_to_zone(module_a.lid, stow_zone)` --
  team rule, the whole camera view is the stow area. A lid carried out of
  view is not stowed until it is seen again (lid_unstowed still fires).
- every lid box back on the body -> `close(module_a)`.
- no body or no lid box in a frame = no evidence (state held).

Tune clips only (held-out has no lids): lid ground truth from 2 fps
strips -- train1 off ~4.8 s / on ~6.4 s, train2 off ~8.4 s / on ~9.8 s,
train3 handles the jar but never opens it. Replay: 6/6 lid steps, 0 false
(train3 clean; train2's two lone "separate lid" frames at 20.4/20.8 s are
voted out). Tune 10/12 -> 16/18, held-out unchanged 11/13. Latency +0.3 to
+0.7 s. Sweep: overlap 0.1-0.5 and k/n 2/4-3/5 all 6/6; hold <= 0.6 s
fine, 1.0 s loses train2 (detach lasts only ~1.3 s), so lids must NOT
share the 1.0 s container/module hold.

Known limits: in train1 the cap comes off above the box before fusion
sees remove_a, so open_a_lid is flagged out_of_order (steps still
complete). The lid never leaves a hand in these clips, so "set down" is
unmeasured -- a stricter stow (lid not overlapping a hand) would need new
clips. Untested live; tests: tests/test_fusion_lid.py.

## Deployment: packaged app, torch-free detector (Parth side, 2026-09-29)

- `python scripts/build_app.py [--zip]` from `.venv` (the `build` extra) ->
  `dist/BAS-Copilot/`: `BAS-Copilot.exe` (the GUI: dashboard by default,
  same options as run_gui.py) + editable `configs/` + `models/` (detector
  .onnx, hand_landmarker.task, asr, tts). No Python/torch on the demo
  machine. Windows: 674 MB folder, 326 MB zip. PyInstaller does not
  cross-compile: build Mac/Linux on Mac/Linux.
- `.onnx` weights run on onnxruntime + numpy (`_OnnxObb` in detector.py),
  replacing the ultralytics-session swap: identical output to ultralytics
  on the same .onnx (351 frames, diff 0). `.pt` still uses torch.
- Frozen app: `REPO_ROOT` = the executable's folder (src/protocol/loader.py;
  runtime/config.py and validate_protocol.py import it).
- Bundle keeps mediapipe + matplotlib (mediapipe's tasks API imports it);
  drops torch, ultralytics, scipy, pandas, piper.train.
- Verified frozen (no camera/mic): dashboard opens; train2.mp4 + mixed
  profile -> 9/9 steps, 0 violations, hand skeletons on, log chain OK,
  recording OK. Same run from source: identical steps, 10.8 vs 11.7 det-fps
  -> packaging costs nothing. NOTE this laptop: ~11 det-fps with skeletons
  on (15.7 before them); Aryan measured 19.3 on his machine.

## Handoff to Aryan: live tests (Parth, 2026-09-29)

Parth built and verified everything above on clips only (no camera/mic);
the props are with Aryan, so the live checks are his. In order:

1. **Build the app**: `git pull`, then in `.venv`:
   `pip install -e ".[build]"` and `python scripts/build_app.py --zip`.
   Double-click `dist/BAS-Copilot/BAS-Copilot.exe`: the dashboard must open.
2. **Speed on the demo laptop**: start a session on the real camera and
   read `DET .. fps` in the top bar. Parth's laptop: ~11 det-fps with hand
   skeletons on (15.7 without); Aryan's: 19.3. If the demo laptop is slow,
   run skeletons less often before cutting anything else.
3. **PS sample experiment first**: white container + red and yellow boxes
   (slabs), profile `configs/objects/profile_rect.yaml`, camera FIXED on a
   stand. This is what PS 26174 describes -- the headline demo.
4. **Jar run** (profile_mixed / profile_jar): unscrew the cap, keep it in
   view, screw it back -> unseal / stow / reseal must tick off.
5. **Mistakes on purpose**: skip a step, do one out of order, bring in a
   foreign object -> one spoken alert each, naming the step.
6. **Voice**: "Hey BAS, pause / resume / next step / repeat", once in a
   quiet room, once with people talking nearby (never tested in noise).
7. **Markers taped on the rig** + DroidCam (never tested live).
8. **Stream to another laptop**: `--stream-to <ip>:5000`, open it in VLC.

Send back per run: the summary table printed on close and the
`logs/session_*.jsonl`. Anything wrong -> note the time into the session.

## Added 2026-09-29 (Aryan + Claude): PS gaps closed

**Earth laptop (Mission Control on another PC, over Tailscale): see `EARTH_SETUP.md`.**

- **extra_step** (defaults.yaml `no_extra_steps`, PS "an out of sequence step
  is added"): an action no remaining step asks for (e.g. a returned module
  taken out again). The world state follows it, so a later close flags
  module_not_returned. Undone within `settle_s` (3 s) = logged, not spoken:
  real clips show exactly that jitter (cap resting on the jar, jar hovering).
  `scripts/replay_clip.py --log-dir DIR` prints violations by type. Allowed
  extras are declared as `optional` steps (never spoken, never missed, never
  gate later steps; editor has an Optional box).
- **step_time_limit**: per-step `timeout_s` (editor "Time limit"), clock held
  while another module group is in progress (else free order false-alarms).
- Validator refuses what the engine would never enforce: new rule ids,
  `requires`, `min_duration_s`, `on_timeout` other than "alert",
  `concurrency: required`.
- **report.txt** next to each log (`src/logging/report.py`, built from the log only).
- **Earth downlink** (`src/link/`): log lines byte for byte + 1 JPEG per step /
  violation, ack + resend (store-and-forward), JPEG sha256 logged INTO the
  chain. Ground: `scripts/ground_station.py` (Mission Control; `--headless`).
  Co-pilot: start screen "Send to Earth" or `--downlink IP[:5055]`,
  `--link-delay 1.3` (Moon). Measured: 486 KB per 33 s session vs 3.6 MB video;
  ground killed + restarted mid-session -> archive byte-identical.
  Two PCs: allow python through Windows Firewall on the ground PC.
- **Activity line** (`src/runtime/activity.py`): derived from fingertip holding
  + fusion states, logged on change (event_type activity). Not a trained HAR model.
- GUI: EARTH badge, "Now doing" line, Help [H], report/logs buttons on the start screen.
- Start screen roles: "This PC is: SPACE STATION (sender) | EARTH (receiver)".
  EARTH shows this PC's IP to type on the station + Start receiving (Mission
  Control in the same window; `run_gui.py --role earth [--receive]`). Both
  roles list past sessions (chain re-verified, open report / folder).
- IP camera dialog (DroidCam / IP Webcam / RTSP / custom), Test with preview;
  camera URLs must be local-network numeric IPs (FFmpeg bypasses Python).
- Offline guard (`src/runtime/offline.py`, on in run_gui / run_copilot /
  ground_station; `--allow-internet` to disable): audit hook refuses any
  connection / DNS lookup outside the LAN except the Earth IP; OFFLINE badge;
  summary `offline_blocked`. Measured: full live run, 0 blocked.
- Fully offline mode: every session keeps logs/<session>/snapshots/*.jpg +
  info.json + steps.json next to its log (Downlink send=False); "Send to
  Earth" in the station's Sessions tab / `scripts/send_to_earth.py <ip>`
  uploads later over the same wire (fixed link id per session: resumes, no
  duplicates; marker logs/<session>/sent_to_earth.json).
- GOTCHA: never let CopilotApp raise after the hand stage is built -- a
  garbage-collected MediaPipe landmarker deadlocks the process in close().

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
