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
