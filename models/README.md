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
