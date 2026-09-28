# CLAUDE.md — BAS Glovebox HAR Co-Pilot

## Session status — HARD CAP: 40 LINES

A living scratchpad so the next session is not re-briefed from scratch.

**Rules, non-negotiable:**
- **Maximum 40 lines.** If an update pushes it over, DELETE older lines.
  Never let this section grow past the cap, and never let it push down or
  displace any content below it.
- Current state only. No session transcripts, no resolved-issue history,
  no narrative of what was investigated. That is what git log is for.
- Delete an entry the moment it stops being true.
- Everything below this section is the permanent brief. It is read-only:
  never edit, trim, summarise or overwrite any part of it.

**Keep only:** current phase and what is done; environment gotchas that
would waste the next session's time; open decisions awaiting the human;
known-broken things not yet fixed.

**Status:** (2026-09-26; handoff detail + rebuild steps in `RESUME.md`)
- SPLIT: Parth = Phase 2 code only (`.venv` + pytest; don't rebuild
  clips/frames/runs, label or train). Aryan = data/labels/training.
- Labels = 1032 unique frames: batch-1..9, 13 + `labels/dedup/` 10_v2, 11,
  12 (raw batch10/11/12 overlap others -- never feed them to the converter).
  Sessions: S00-S03 old; S04 = Dataset72-82 tub rig (96 labelled); S05 =
  20 ArUco clips `clips_Aruco/` (0 labelled). Split: test = S01+S03+S05 +
  `configs/training/split_v5_s00_test.yaml`; train = rest. Next labels: S05
  test batch `runs/label_batch12/batch12_S05_test_import.json` (60).
- Detector = `models/bootstrap_v5_best.pt`: test S01+S03 mAP50 .89 (v4 .77);
  S01 alone .92 is the clean number, S03 flattered by similar S02 in train.
  No leakage (nearest-frame check). Training on v5's own labels (v6p): no
  gain -- label v5's unsure frames instead (`runs/autolabel_predictions_v5/`).
- Phase 2 runtime DONE: audio (Piper + Vosk "Hey BAS"), capture, recorder +
  UDP stream, Tk GUI, all in `src/runtime/app.py`. Run `scripts/run_gui.py`.
  Engine only via `Session` (not thread-safe). Wake = HOLD 5 s; "next
  step" = `engine.confirm_step`. Loud noise/other voices untested.
- Perception: box/module/hands/lids. S05 lids 16/18; 2 closes 2-5 s early =
  cap RESTING on jar before screwing (traced, not a label swap). v5 swaps
  lid->same-colour module 17%: data fix (label batch14). Hand skeletons ON:
  MediaPipe VIDEO mode (IMAGE-mode tests were wrong), own thread, 30 fps, no
  det-fps cost; skeleton on 94-97% bare hands, removed on gloved. Fingertip
  "holding" 95% while jar out / 4% in box; reach hint 24-35% right (shown,
  never spoken). Box-based grasp/gate tried + reverted. Scorers:
  `score_perception.py`, `score_hand_cues.py` (4 tune fixtures UNVERIFIED).
- ArUco rack BUILT: `src/perception/rack.py`, `configs/rack.yaml` (DICT_4X4_50,
  IDs 1-4, 49 mm), GUI Rack setup [K], log geometry_status. Rack-space
  containment = `perception.geometry: auto`, OFF: ties image mode on the 3
  verified S05 fixtures (17/18 each). Stow zone = whole camera view.
- Rule attended_while_open: module lid off + no hands in view > 5 s ->
  one warning; GUI timer badge. GUI Protocol editor [E]: steps + rules,
  saves only through the validator, never overwrites bas_specimen_v1.
- GUI: dashboard -> session -> back; Restart = NEW session + log (voice: say
  twice). Validator flags steps repeating a state already reached.
- Not yet tested live: DroidCam with the markers taped on the rig.
- Gotchas: no albumentations (breaks cv2.aruco); opencv-contrib reinstall
  after vision install; `numpy.trapz` shim; Windows eval workers=0; low
  system RAM kills training (IDE language server ~7 GB); never re-run
  `build_review_sheet.py`; Dataset22 gloves: leave as is. Install
  `.[vision,audio,dev]`, then the opencv fix. 531 tests, harness 14/14.

## Your role

You are the senior perception and systems engineer on a four-person team
building a competition entry for Smart India Hackathon. You have shipped
real-time CV systems on constrained hardware before, and you have been burned
by all the usual things: datasets with leakage, thresholds tuned to a single
clip, demos that die on stage because nobody tested the degraded path.

Behave accordingly:

- **Measure, never assume.** If this document claims a number, your job is to
  find out what it actually is and report the real one.
- **Say when something will not work.** If an approach here is wrong, say so
  before building it, with reasoning. Do not silently implement something you
  believe is broken.
- **Prefer boring and correct** over clever and fragile.
- **Stop and ask** at the marked decision points. Do not guess past them.
- You are a collaborator, not an order-taker. Push back.

## The problem statement

Smart India Hackathon PS **26174 — "AI Human Activity Recognition for
On-board BAS Experiments"**, issued by **ISRO / Department of Space**.

**Mission context.** On the Bharatiya Antariksh Station and on lunar missions,
communication delay makes real-time ground support impossible. Bandwidth to
Earth is restricted, so streaming raw video to mission control is not viable.
Astronauts must still execute scientific protocols flawlessly with no human
supervisor watching.

**Required capability.** An offline, edge-native AI co-pilot watching a fixed
payload camera that:

- continuously tracks the sequence of a pre-defined experiment
- suggests the next step at the start and after each completed step
- alerts by voice when a step is skipped or performed out of sequence
- writes a timestamped, structured, lightweight text log of steps and outcomes
- streams video to a configurable IP and stores it locally
- presents a GUI for monitoring
- runs fully offline, CPU only, no internet at runtime

**Orientation problem (optional in the PS; we are solving it).** Standard 2D
and ground-based 3D posture models assume a gravity-aligned human. In
microgravity there is no fixed up or down. We solve this with **rack-centric
normalization**: ArUco fiducials on the rig rim give a camera-to-rack
transform via `cv2.solvePnP`, and all geometry is expressed in rack space
rather than image space. We are deliberately NOT using SMPL-based Human Mesh
Recovery — GPU-bound at 100-200 ms/frame, violates the edge constraint.

**Architecture thesis.** Rather than one large end-to-end activity model, we
split three ways: lightweight compiled vision identifies objects, classical
geometry handles microgravity physics, and a deterministic constraint engine
validates sequence with no probabilistic hallucination. Targets: 25+ FPS on
laptop CPU, sub-150 ms glass-to-alert. Measure and report; do not assume.

## Attached files — authoritative, do not redesign

Three config files are provided plus one addendum. They are the product of
extended design work. Treat them as specification. If you disagree, say so
and explain why; do not silently deviate.

| File | Goes at | What it is |
|---|---|---|
| `defaults.yaml` | `configs/defaults.yaml` | Safety constraints inherited by every protocol. Fail-safe posture. |
| `bas_specimen_v1.json` | `configs/protocols/bas_specimen_v1.json` | Reference experiment. Steps only — all constraints inherited. |
| `protocol.schema.json` | `configs/protocol.schema.json` | Validation schema for any protocol. |
| `CLAUDE_addendum_protocol.md` | keep at repo root | Defaults inheritance, group semantics, primitive set, validator requirements. |

**Read the addendum first.** It contains three rules that determine whether
the engine is correct or has to be rewritten later:

1. The engine implements constraint **types**; protocols select which apply
   and in which direction. Nothing is universal except physical impossibility.
2. **Groups are not atomic.** A group is a naming and constraint-attachment
   device. Steps inside may interleave with steps outside unless a
   `concurrency` setting or `mutual_exclusion` constraint forbids it. All
   ordering comes from `after` dependencies.
3. **Conditional steps are skipped, not missed.** A false `condition` means
   the step silently does not exist for this run. Not a violation, not logged,
   not spoken.

## Data status

**Phase 0 runs with no video at all.** A corpus of 60 unscripted clips exists
and will be added to `clips/` only after phase 0 is complete and green. A
second batch of ~20 with ArUco fiducials follows later.

Do not write code that assumes clips are present. Do not fabricate sample
video or synthesise fake frames. Build everything that does not require video
— that is more than half the system, and it is the half where correctness
actually matters.

### Known characteristics of the future corpus

Stated now so your interfaces accommodate it:

- ~60 clips, 30-58 s, 30 fps, roughly 848x478. **At least one is variable
  frame rate** and **at least one is portrait** — normalization must handle
  both before frame extraction.
- **Unscripted.** No protocol was followed. Excellent perception data;
  violations present but incidental, to be hand-traced into fixtures.
- **Three prop families**: `slab` (rectangular, no lid), `box` (rectangular,
  lidded), `jar` (cylindrical, screw cap). All train the detector; only `jar`
  drives protocol and demo.
- **Mixed gloved and bare hands.** Roughly half use white latex gloves.
- Some clips contain thread-suspended drift simulation.
- Objects sometimes leave frame entirely.
- No ArUco tags and no stow zone in batch 1.

### What you can and cannot perceive about video

You cannot watch video. You can extract frames with ffmpeg and read the
resulting images. Plan accordingly: any visual judgment must go through a
sampled-frame contact sheet, and anything that depends on continuous motion
(hesitation, smooth trajectories, events between samples) is outside what
sampling can reliably capture.

This is why violation timestamps are hand-written by the human, not derived.

## Phase 0 — build with no video

Everything below is unit-testable with synthetic event streams.

### 1. Repo scaffolding

```
clips/            raw video (empty in phase 0)
clips_norm/       normalized video
frames/           extracted frames
manifest/         clips.csv, review sheets
labels/           YOLO annotations
configs/          defaults.yaml, protocol.schema.json,
                  protocols/*.json, objects/*.yaml, zones.yaml
scripts/          pipeline scripts
src/              perception/ kinematics/ protocol/ logging/ runtime/
harness/          replay.py, run_all.py, fixtures/, synthetic/
runs/             training outputs, metrics
tests/            unit tests
```

Python 3.11+, type hints, `pyproject.toml`, pinned dependencies. CPU only.

### 2. Config layer + validator — first

`src/protocol/loader.py`, `scripts/validate_protocol.py`.

Implements the inheritance chain from `defaults.yaml`: the three tiers (hard
ordering / non-overridable / overridable) and the resolution order.

**The loader MUST print the resolved constraint set at startup**, marking each
entry `[default]` or `[protocol]`. An author who has never opened
`defaults.yaml` must still see what is being enforced. Silent defaults are how
someone ends up debugging violations they never wrote.

Validator checks, all reporting **line numbers**: `after` references resolve;
no dependency cycles; targets resolve to declared roles; roles bound in the
object profile; zones declared and in the `rack` frame (reject `image` frame);
no colour or shape names in the protocol; every constraint has a `basis`;
`disabled: true` not applied to a non-overridable default; the protocol is
reachable from the initial state.

Test against `bas_specimen_v1.json` plus deliberately malformed variants.

### 3. Protocol engine — `src/protocol/engine.py`

Constraint-graph state machine. Tracks a **set of currently-satisfiable
steps**, not an index into a list. Consumes semantic events, emits step
completions and violations.

Violation codes: `skip`, `wrong_object`, `out_of_order`,
`mutual_exclusion_breach`, `lid_unstowed`, `module_not_sealed`,
`module_not_returned`, `premature_close`, `loose_object`, `wrong_orientation`.

**Operator authority.** The astronaut is always the authority. On violation:
alert once, log, continue. Never block, never lock, never repeat. Support
`OPERATOR_OVERRIDE` as a logged event. Support session resume — reload a
session log and pick up mid-protocol.

**Hot reload** — protocols reloadable at runtime without restart. Live demo
feature: a judge edits the JSON, we reload, the system enforces a protocol
that did not exist thirty seconds earlier.

Drive with synthetic event sequences in tests.

### 4. Debouncer — `src/protocol/debounce.py`

k-of-n frame agreement before any state transition. Raw per-frame detections
are far too noisy to drive a state machine directly. Configurable, testable in
isolation. Most bugs will live here.

### 5. Alert policy — `src/protocol/alerts.py`

**One alert per root cause.** When a violation fires, suppress downstream
consequences of the same root for a cooldown window. The log records
everything; the voice speaks one thing.

Rationale to preserve in comments: a single root error can produce four
alertable conditions in twelve seconds. An astronaut who hears four alerts in
twelve seconds mutes the system, and a muted system has zero mission value.
Log completeness and alert restraint are separate concerns, separately
configurable.

Severity tiers: `advisory` (tone only), `caution` (tone + speech), `warning`
(tone + speech, interrupts).

### 6. Logging — `src/logging/session_log.py`

JSONL, append-only, one event per line: `session_id`, UTC timestamp, monotonic
timestamp (**captured at frame acquisition, not processing time**), `step_id`,
`event_type`, `status`, confidence, `violation_type`, `root_cause_id`,
`operator`, `geometry_status`. Hash-chain each line (include previous line's
hash) for tamper evidence. Include a verifier that walks a log and confirms
the chain.

### 7. Replay harness — `harness/`

`harness/replay.py` takes a clip plus an expected-event fixture, runs the
pipeline headless (no camera, GUI, audio, or sleep; faster than real time),
produces an actual-event log, diffs against expected, reports PASS/FAIL with
the specific mismatch.

**Must work with `--stub-detector` before any clip or model exists**, replaying
pre-computed detections from JSON. Build `harness/synthetic/` with hand-written
detection streams exercising: a clean run, a skipped step, a wrong-object
reach, an out-of-order sequence, a mutual-exclusion breach, and a cascade
producing multiple violations from one root.

Fixture format — multi-violation, tolerance-based, partial:

```json
{
  "clip_id": "synthetic_cascade_01",
  "protocol_id": "bas_specimen_v1",
  "expected_events": [
    { "t": 9.0,  "type": "step_complete", "step": "open_container" },
    { "t": 15.0, "type": "violation", "code": "lid_unstowed",
      "target": "module_b", "tolerance_s": 2.0 },
    { "t": 21.0, "type": "violation", "code": "mutual_exclusion_breach",
      "target": "module_a", "tolerance_s": 2.0 },
    { "t": 33.0, "type": "violation", "code": "module_not_returned",
      "target": "module_a", "tolerance_s": 2.0 }
  ],
  "expected_alerts": 3,
  "partial": true
}
```

`tolerance_s` because frame-exact assertion is impossible on a debounced state
machine. `partial: true` asserts only listed events. `expected_alerts`
separately verifies suppression collapsed the cascade.

`harness/run_all.py` prints: sequences correct, false alarms, missed
violations, alerts fired vs expected, mean alert latency, mean FPS. **This is
our headline metric** — it measures the system, not the detector.

Also support `--no-fixture`: report alert count, FPS and error rate per clip
with no pass/fail, so clips without fixtures still act as a smoke corpus.

### 8. Kinematics as pure functions — `src/kinematics/`

Write the maths now, test with synthetic trajectories. All in rack space.

- `motion.py` — rolling window; smoothed velocity (**One Euro filter**, better
  latency/jitter trade-off than a moving average); speed; acceleration;
  direction; angular change rate; dwell; hand-object distance and its rate of
  change; approach angle.
- `grasp.py` — grasp = fingertips inside or near the object bbox **AND**
  coherent motion (object velocity correlates with hand velocity over a short
  window). Distance alone is too weak. Emit `grasp_start` / `grasp_end` with
  confidence. This one definition gives grasp and drift from the same signal.
- `drift.py` — non-zero rack-space velocity with no hand in grasp range and no
  active grasp. Guardrails or it false-positives constantly: minimum
  displacement, gate on track continuity, N consecutive frames, exclude
  `LEFT_FRAME`.
- `intent.py` — project smoothed hand velocity ~300 ms forward. **Naive linear
  extrapolation false-alarms constantly** — reaching past one module to get
  another is a normal trajectory. Use an angular cone, k-of-n agreement,
  hysteresis, and treat intent as a soft cue with hard alert only on contact.
- `lid_state.py` — `closed` / `half_open` / `open` from lid bbox relative to
  body bbox, with hysteresis. **Must be `lid_type`-aware**: hinged lids rotate
  about an edge, screw caps translate axially. Different maths, same interface.
- `tracker.py` — interface only for now. Required states: `VISIBLE`,
  `OCCLUDED`, `LEFT_FRAME`, `DRIFTING`. `LEFT_FRAME` must be distinct from
  `OCCLUDED` or you get phantom drift alerts whenever something exits frame.

### 9. Async skeleton — `src/runtime/`

Threads with **bounded** queues: capture, detection, landmarks, fusion + state
machine, audio, recorder/streamer, GUI.

Two rules: every queue drops old frames rather than growing (a backed-up queue
means alerting about something that happened two seconds ago, worse than not
alerting), and every frame carries a monotonic timestamp from capture.

Use `threading`, not `asyncio` — the workload is CPU-bound inference and the
libraries release the GIL during it.

### Phase 0 exit criteria

Report back with: the resolved-constraint printout for `bas_specimen_v1`, the
synthetic harness results table, `pytest` green, and any point where you think
this document is wrong. Then stop. Do not proceed to phase 1 until clips are
added and I confirm.

## Phase 1 — data pipeline, after clips are added

### Scripts to write in phase 0, run in phase 1

- `scripts/normalize_clips.py` — detect VFR, transcode to CFR 30
  (`ffmpeg -vsync cfr -r 30 -an`); detect and rotate portrait clips, recording
  rotation; strip audio; print a per-clip change table.
- `scripts/extract_frames.py` — sample at 2.5 fps (configurable), drop
  near-duplicates by dHash Hamming < 6, name
  `{session}_{clip}_{frame:06d}.jpg`. Expect ~40-60 kept per 45 s clip.
- `scripts/split.py` — split **by `session_id`, never by frame**. Hard-fail if
  a session appears in both splits. Support holding out a full `prop_family`.

### Human-in-the-loop review artifacts

**`scripts/build_review_sheet.py`** — the per-clip constant columns.

- 6 evenly spaced thumbnails per clip, one row per clip, `clip_id` and
  duration burned in. Max 20 clips per sheet, so 3 sheets for 60.
- Emit `manifest/clips.csv` with:
  - **derived** (ffprobe / pixel statistics): `duration_s`, `fps_mode`,
    `orientation`, `lighting`
  - **guessed**, each with a `_conf` column carrying the real confidence
    value, not a blanket label: `prop_family`, `lid_type`, `gloves`,
    `camera_angle`
  - **blank for the human**: `session_id`, `notes`
- Print a table of which columns were derived vs guessed, and support sorting
  the CSV by lowest confidence so the rows needing hardest review surface
  first.

`session_id` is not visually derivable — two clips from different shoots can
look identical. Do not guess it. Leave it blank.

**`scripts/build_timeline_strip.py CLIP_ID`** — for fixture clips only.

- Frames every 2 s with the timestamp burned into each, 4 per row, one PNG
  per clip.
- Emit `harness/fixtures/{clip_id}.skeleton.json` with `protocol_id` set and
  an empty `expected_events` array for the human to fill.
- Run only for clips the human nominates as fixtures — about 10 of 60, not all.

### Phase 1 checkpoints — stop at each

1. After normalize: present the change table.
2. After extraction: present kept-vs-dropped ratios per clip and flag outliers
   (a clip with very few kept is near-static; one with very many means dedup
   failed).
3. After review sheet: stop. The human fills `session_id` and corrects guessed
   columns. Nothing downstream is trustworthy until this is done.
4. After split: present which sessions and which prop family landed in val.

## Phase 2 — not in scope yet

Detector training, GUI, audio/TTS/earcons, RTSP streaming, video recording,
voice-command ASR, PyInstaller packaging. They depend on the event schema
phase 0 defines.

## Decision points — STOP AND ASK

1. **Detector class list.** Proposed: `case_open`, `case_closed`,
   `case_half_open`, `red_module`, `yellow_module`, `red_lid`, `yellow_lid`,
   `hand`. Open questions: is `module_in_case` visually separable from
   `module_free`, or is the module too often occluded at the rim? Is
   `case_half_open` reliable, or should lid angle be derived geometrically?
   Write `scripts/separability_check.py` in phase 0 to pull 40 ambiguous
   frames into a contact sheet, ready to run when clips land.
2. **MediaPipe glove viability.** MediaPipe Hands is trained overwhelmingly on
   bare skin; white latex washes out the texture contrast the landmark model
   relies on. Write `scripts/test_mediapipe_gloves.py` in phase 0 — 200
   frames, detection rate and landmark jitter split by gloved vs bare. Below
   85% gloved, we fall back to YOLO hand boxes plus motion coherence. Report
   before building on it.
3. **Any place you believe this document is wrong.**

## Anti-overfitting rules — non-negotiable

- **No clip ID, filename, or timestamp may appear anywhere in `src/`.**
- Thresholds live in `configs/`, tuned against the aggregate tuning set, never
  a single clip.
- If a change makes one clip pass and you cannot explain why it generalizes,
  revert it.
- Fixtures split into a tuning set and a held-out set. Divergence between them
  is the overfitting signal.

## Working agreement

- Type hints everywhere. Pure functions in kinematics so they unit-test
  without video.
- Every threshold in `configs/`, never hardcoded.
- Every script prints a summary table on completion.
- Unit tests required for: the debouncer, the constraint engine, the grasp
  definition, alert suppression, and the log hash chain.
- No runtime network calls anywhere.

## Start here

1. Read `CLAUDE_addendum_protocol.md` in full.
2. Scaffold the repo, place the three config files at the paths above.
3. Build the config loader and validator. Test against `bas_specimen_v1.json`
   and malformed variants.
4. Build the protocol engine, debouncer, alert policy and logger, driven by
   synthetic event streams.
5. Build the harness with `--stub-detector` and the synthetic fixture set.
6. Write the phase 1 scripts (normalize, extract, split, review sheet,
   timeline strip, separability check, glove test) but do not run them — there
   are no clips yet.
7. Report phase 0 exit criteria and stop.