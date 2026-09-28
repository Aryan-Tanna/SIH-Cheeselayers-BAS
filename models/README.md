# Vendored model weights

Weights are committed directly into this repo, never fetched at
runtime — the deployed system must run fully offline (no internet at
runtime, per `CLAUDE.md`).

## `hand_landmarker.task`

- **Source**: `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task`
  (Google's official MediaPipe Solutions model storage — this is the
  documented, intended distribution point for this model; the classic
  `mediapipe.solutions.hands` API bundled the equivalent model inside
  the pip wheel itself in `mediapipe<0.10.20`-ish, but that API and its
  bundled model were removed starting with the version this repo has
  installed. Vendoring the `.task` file locally, as done here, is
  MediaPipe's own documented pattern for offline/on-device deployment
  via the newer Tasks API.)
- **Fetched**: 2026-09-19
- **Size**: 7,819,105 bytes
- **MD5**: `15318430ea3851670fe9914116a9cfad` (matches the source's
  reported ETag/MD5 exactly — verified at fetch time; re-verify with
  `md5sum models/hand_landmarker.task` if this file is ever
  re-downloaded, since Google could update "latest" underneath the URL)
- **License**: Apache License 2.0 (same license as the MediaPipe
  project distributing it). Redistribution is permitted with
  attribution and retention of copyright/license notices — this file
  and note satisfy that.
- **Used by**: `scripts/test_mediapipe_gloves.py`, via
  `mediapipe.tasks.python.vision.HandLandmarker`.

## `bootstrap_v4_best.pt`

- **What**: YOLOv8n-OBB detector, 8 classes (`CLASS_ORDER` in
  `scripts/convert_labels_to_yolo_obb.py`). `best.pt` of run
  `bootstrap_v4` (best epoch 35 of 75, early-stopped), trained from
  `yolov8n-obb.pt` on labels batch-1..batch8, train = S00 (333 frames),
  augmentation `configs/training/augment_v4.yaml`.
- **Val (S01+S02+S03, 117 frames, never trained on)**: P 0.78, R 0.58,
  mAP50 0.73, mAP50-95 0.51. hand_gloved unmeasured (0 val instances).
- **Committed** because `runs/` is gitignored and a fresh clone would
  otherwise have no detector at all. Superseded when v5 is trained.
- **Created**: 2026-09-23. **Size**: 6445331 bytes. **MD5**: `04510d806a7e7885d94ebb1174b5694b`

## `tts/en_US-lessac-medium.onnx` (+ `.onnx.json`)

- **What**: Piper neural TTS voice (US English, "lessac", medium
  quality, 22050 Hz), used by `src/runtime/tts.py`. Path set in
  `configs/runtime.yaml` (`audio.tts.voice_model`); both files must sit
  side by side.
- **Source**: `https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/`
  (the Piper project's official voice repository).
- **Fetched**: 2026-09-24
- **Size**: 63,201,294 bytes (`.onnx`), 4,885 bytes (`.onnx.json`)
- **MD5**: `2fc642b535197b6305c7c8f92dc8b24f` (`.onnx`),
  `c1f2b7bddefe113f3255ff9ef234cfd3` (`.onnx.json`) -- both match the
  repo's published `voices.json` digests.
- **Why this one**: every English Piper voice is >=63 MB ("low" quality
  is no smaller), so medium costs nothing extra over low and sounds
  better. Measured on a laptop CPU: ~3.6 s load, 0.4-0.9 s per phrase,
  which is why every speakable phrase is pre-rendered at protocol load.
- **License**: see the voice's MODEL_CARD in the source repository
  (lessac dataset voice, distributed by the Piper project for
  redistribution with attribution).

## `asr/vosk-model-small-en-us-0.15/`

- **What**: Vosk (Kaldi) small US-English speech model, used by
  `src/runtime/voice_control.py` for offline "Hey BAS" commands.
  Recognition is restricted to a fixed grammar at runtime, so the
  small model is ample. Path set in `configs/runtime.yaml`
  (`voice_control.model`).
- **Source**: `https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip`
  (the Vosk project's official model list), unzipped in place.
- **Fetched**: 2026-09-24. **Zip MD5**: `09ab50ccd62b674cbaa231b825f9c1cb`
  (41,205,931 bytes). Unzipped ~68 MB; largest file 24 MB
  (`graph/Gr.fst`), all under GitHub's 100 MB per-file limit.
- **Measured**: recognizes all five commands + bare wake phrase at
  confidence 1.0 on Piper-synthesized speech, 22-48 ms per utterance;
  rejects ordinary sentences (they decode with `[unk]`). Not yet
  measured on live human speech or with fan noise.
- **License**: Apache License 2.0 (Alpha Cephei).

## `bootstrap_v5_best.onnx` (runtime default since 2026-09-28)

- **What**: `bootstrap_v5_best.pt` exported to ONNX, one self-contained file
  (md5 `cf1246c51e64d158a05d364f3b257ee1`). Exported with ultralytics 8.3.28,
  torch 2.14 + onnx 1.23 + onnxscript 0.7 (dev extra), `imgsz=640`,
  `simplify=False`, static shape, then merged with `onnx.save` (the
  exporter writes a `.onnx.data` side file).
- **Parity (test S01+S03, same frames/labels)**: mAP50 .894 vs .892 (.pt),
  mAP50-95 .702 vs .703. Live frames (S05 Dataset15, 60 frames): identical
  class lists 60/60, box centres within 0.35 px (median).
- **Speed (CPU)**: 23.0 vs 35.6 ms/inference (ultralytics val); in the live
  app with audio on, 19.9 vs 16.9 det-fps, capture->detections 63 vs 73 ms.
- **Threads**: ultralytics opens the session with default options (one
  spinning worker per core, the speech-contention problem); the Detector
  re-creates it capped at `detector.threads`, no spinning.
- **Re-export after a retrain**:
  `yolo export model=models/<new>.pt format=onnx imgsz=640 simplify=False`,
  then `python -c "import onnx; onnx.save(onnx.load('x.onnx'), 'models/<new>.onnx')"`,
  then check parity with `yolo val` on `data_test_sessions.yaml` before switching.

## `bootstrap_v5_best.pt` (training weights; runtime default 2026-09-26 to 09-28)

- **What**: YOLOv8n-OBB, same 8 classes, same recipe as v4 (from
  `yolov8n-obb.pt`, `configs/training/augment_v4.yaml`, 120 epochs,
  GPU, 26 min). `best.pt` of run `bootstrap_v5`.
- **Data**: 1032 labelled frames (batch-1..13, dedup copies in
  `labels/dedup/`). Train 715 = S00 minus 9 test clips + S02 + S04.
  Test = S01 + S03 (205) + S05 (0 labelled yet) + 9 whole S00 clips
  (112, `configs/training/split_v5_s00_test.yaml`). Split by whole
  session / whole clip, never by frame.
- **Test S01+S03 (never trained on, same frames and labels for both)**:
  v4 P .77 R .65 mAP50 .769 mAP50-95 .572 -> **v5 P .887 R .833 mAP50
  .892 mAP50-95 .703**. Per class mAP50 v5 (v4): case_open .98 (.77),
  case_closed .86 (.65), red_module .92 (.91), yellow_module .90 (.74),
  red_lid .84 (.80), yellow_lid .76 (.62), hand_bare .97 (.91).
  Caveat: v4 picked its best epoch ON S01-S03 (it was v4's val), so v4
  is if anything flattered here. S03 is slab, like S02 which v5 trains on.
- **Test 9 S00 clips (same session as train -> overestimates)**: mAP50
  .906; hand_gloved .99 -- still not a real glove number (needs gloved
  clips from a new session).
- **Live**: 34 ms/1080p frame CPU, 15.5 det-fps with rack tracking on.
- **Not yet measured**: S05 (label `runs/label_batch12/batch12_S05_test_import.json`).
