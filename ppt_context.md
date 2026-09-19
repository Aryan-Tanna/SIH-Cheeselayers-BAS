# BAS Glovebox HAR Co-Pilot — PPT Context Document

> **Team:** Cheeselayers
> **Competition:** Smart India Hackathon (SIH)
> **Problem Statement:** PS 26174 — *"AI Human Activity Recognition for On-board BAS Experiments"*
> **Issuing Body:** ISRO / Department of Space

---

## 1. What Is This Project?

### 1.1 Mission Context

The **Bharatiya Antariksh Station (BAS)** is India's upcoming crewed space station. Astronauts aboard BAS will conduct scientific experiments inside a **glovebox** — a sealed, controlled environment for handling sensitive specimens.

The fundamental operational challenge:
- **Communication delay** between the space station and Earth makes real-time ground-supervision impossible.
- **Restricted bandwidth** rules out streaming raw video feeds to Mission Control.
- Astronauts must execute complex multi-step scientific protocols **flawlessly and autonomously**, with no human supervisor available.

A single procedural error — a skipped step, a wrongly placed specimen, an unsecured lid floating free in microgravity — can compromise an experiment, damage equipment, or create a safety hazard.

### 1.2 What the System Does

The BAS Glovebox HAR Co-Pilot is an **offline, edge-native AI co-pilot** that watches a fixed payload camera and:

| Capability | Description |
|---|---|
| **Protocol Tracking** | Continuously tracks the astronaut's progress against a pre-defined experiment procedure |
| **Step Guidance** | Prompts the next step at the start of each session and after every completed step |
| **Voice Alerting** | Alerts by voice when a step is skipped, performed out of order, or a safety hazard occurs |
| **Tamper-Evident Logging** | Writes a hash-chained JSONL log of every step, outcome, and violation |
| **Video Recording** | Stores footage locally and streams to a configurable IP address |
| **GUI Monitoring** | Presents a real-time dashboard for monitoring (Phase 2) |
| **Fully Offline** | CPU-only, no internet required at runtime |

### 1.3 The Orientation Problem (Solved)

Standard 2D/3D pose models assume a **gravity-aligned human** — there is a fixed "up." In **microgravity, there is no fixed up**. An astronaut can be upside-down, sideways, or at any angle.

**Our solution — Rack-Centric Normalization:**
- **ArUco fiducial markers** are attached to the rig rim.
- `cv2.solvePnP` computes a **camera-to-rack coordinate transform**.
- All geometry (positions, zones, distances, containment checks) is expressed in **rack space**, not image space.
- Robust to any astronaut orientation, any camera tilt, any lighting condition.

> We deliberately **NOT** use SMPL-based Human Mesh Recovery (HMR): GPU-bound at 100–200 ms/frame, which violates the CPU-only edge constraint.

---

## 2. Architecture

### 2.1 Core Design Philosophy — Three-Way Split

Rather than one large end-to-end activity recognition model (opaque, GPU-hungry, hard to validate for safety-critical use), the system is split into **three independent layers**:

```
RUNTIME PIPELINE
Camera → [Detection] → [Kinematics] → [Protocol Engine] → [Alert]
           |                |                  |
      Lightweight      Classical Geometry   Deterministic
      Vision (YOLO     (rack-space maths)   Constraint Engine
      + MediaPipe)     No ML inference      No hallucination
```

| Layer | Responsibility | Technology |
|---|---|---|
| **Vision** | Detect objects (modules, lids, hands, container) | YOLOv8, MediaPipe Hands |
| **Kinematics** | Motion, grasp, drift, intent, lid state in rack space | Pure Python maths, One Euro filter |
| **Protocol Engine** | Validate procedure sequence, emit completions & violations | Deterministic constraint-graph state machine |

### 2.2 System Component Map

```
SIH-Cheeselayers-BAS/
|
+-- configs/                   <- All thresholds and rules live here; NONE hardcoded in src/
|   +-- defaults.yaml          <- Safety constraints inherited by every protocol (fail-safe)
|   +-- protocol.schema.json   <- JSON Schema for validating any protocol file
|   +-- zones.yaml             <- Rack-space zone geometry (stow_zone, container_interior)
|   +-- objects/               <- Object profiles binding protocol roles to YOLO classes
|   |   +-- profile_jar.yaml   <- Jar prop family (cylindrical, screw cap) -- demo prop
|   |   +-- profile_rect.yaml  <- Rectangular slab (no lid) prop family
|   |   +-- LABELLING_GUIDANCE.md  <- Annotation rules for labellers
|   +-- protocols/
|       +-- bas_specimen_v1.json   <- Reference experiment: Dual specimen module inspection
|
+-- src/
|   +-- protocol/              <- The "brain" -- safety logic
|   |   +-- engine.py          <- Constraint-graph state machine (685 lines)
|   |   +-- loader.py          <- Config loader + constraint resolver (17.8 KB)
|   |   +-- debounce.py        <- k-of-n frame agreement filter
|   |   +-- alerts.py          <- Alert suppression + severity routing
|   |   +-- events.py          <- Typed event dataclasses (ActionEvent, StateEvent...)
|   |   +-- lineindex.py       <- Source-line tracking for validator error messages
|   |
|   +-- kinematics/            <- Pure-function physics in rack space
|   |   +-- motion.py          <- Rolling window, One Euro filter, speed/direction/dwell
|   |   +-- grasp.py           <- Grasp detection from fingertip proximity + motion coherence
|   |   +-- drift.py           <- Free-floating object detection (microgravity hazard)
|   |   +-- intent.py          <- Forward-projected hand intent (angular cone + hysteresis)
|   |   +-- lid_state.py       <- Lid open/closed state (hinged vs screw-cap, hysteresis)
|   |   +-- tracker.py         <- Object state: VISIBLE / OCCLUDED / LEFT_FRAME / DRIFTING
|   |
|   +-- logging/
|   |   +-- session_log.py     <- Append-only JSONL + SHA-256 hash-chain tamper evidence
|   |
|   +-- runtime/
|       +-- pipeline.py        <- Threaded pipeline skeleton with bounded dropping queues
|       +-- clock.py           <- Monotonic clock abstraction (real vs injectable test clock)
|
+-- harness/                   <- Correctness testing without any video
|   +-- replay.py              <- Headless pipeline replay from stub detections (14 KB)
|   +-- run_all.py             <- Run all synthetic fixtures; print metrics table
|   +-- fixtures/              <- Clip-keyed expected-event fixtures (human-written)
|   +-- synthetic/             <- 9 hand-crafted detection stream scenarios
|       +-- clean_run.json
|       +-- skipped_step.json
|       +-- out_of_order.json
|       +-- wrong_object.json
|       +-- mutual_exclusion_breach.json
|       +-- cascade.json
|       +-- root_cause_cooldown.json
|       +-- lid_unstowed_idle_tail.json
|       +-- debounce_raw_observations.json
|
+-- scripts/                   <- Data pipeline (Phase 1)
|   +-- normalize_clips.py     <- VFR to CFR30, portrait rotation, strip audio
|   +-- extract_frames.py      <- 2.5 fps sampling + dHash deduplication
|   +-- build_review_sheet.py  <- Contact sheets + manifest/clips.csv
|   +-- build_timeline_strip.py <- Per-clip fixture skeleton generator
|   +-- separability_check.py  <- Class-list decision support (ambiguous frame review)
|   +-- split.py               <- Session-keyed train/val split
|   +-- validate_protocol.py   <- Protocol JSON validator (line-number errors)
|   +-- test_mediapipe_gloves.py <- Glove-vs-bare detection rate benchmark
|
+-- tests/                     <- 140 pytest unit tests, all passing
    +-- test_engine.py          <- Protocol engine correctness (12.6 KB)
    +-- test_loader.py          <- Config loading & constraint resolution
    +-- test_debounce.py        <- Debouncer isolation
    +-- test_alerts.py          <- Alert suppression logic
    +-- test_session_log.py     <- Hash-chain integrity
    +-- test_kinematics_*.py    <- Pure-function kinematics (5 files)
    +-- test_harness.py         <- Full replay harness end-to-end
    +-- test_normalize_clips.py <- Video normalization
```

### 2.3 Runtime Data Flow

```
Camera Frame (with monotonic timestamp)
        |
        v
  [YOLO v8 Object Det.]  [MediaPipe Hands Landmark Det.]
        |                           |
        v                           v
  +------------------------------------------+
  |           KINEMATICS LAYER               |
  |  solvePnP -> rack-space transform        |
  |  motion.py   -> velocity, speed, dwell   |
  |  grasp.py    -> grasp_start/grasp_end    |
  |  drift.py    -> floating object alert    |
  |  lid_state.py -> open/closed/half        |
  |  intent.py   -> where is hand going?     |
  +------------------+-----------------------+
                     | Semantic Events
                     v
  +------------------------------------------+
  |          DEBOUNCER (k-of-n)              |
  |  5-of-8 frame agreement required         |
  |  before any state transition fires       |
  +------------------+-----------------------+
                     | Stable Semantic Events
                     v
  +------------------------------------------+
  |      PROTOCOL ENGINE (engine.py)         |
  |  Constraint-graph state machine          |
  |  Tracks SET of satisfiable steps         |
  |  Emits: step_complete / violation        |
  +--------+---------------------------------+
           |               |
           v               v
  [ALERT POLICY]     [SESSION LOGGER]
  Suppresses cascades  JSONL hash-chain
  1 root cause/cooldown  tamper-evident
           |
           v
  [TTS / Audio]  <- Phase 2
  [GUI Display]  <- Phase 2
  [RTSP Stream]  <- Phase 2
```

---

## 3. Protocol Engine (Deep Dive)

### 3.1 How It Works

The engine tracks a **set** of currently-satisfiable steps (not a position index in a list). Critical because:
- Steps within groups can be **free-order** (module A or module B first — both valid).
- Steps become satisfiable when their `after` dependencies are satisfied.
- This is a **constraint-graph state machine**, not a linear script.

### 3.2 Three-Tier Safety Architecture

**Tier 1: HARD ORDERING** (Engine-enforced, cannot be disabled by any protocol)
- Cannot remove a module from a closed container
- Cannot stow a lid before it is detached
- (Physical impossibilities — perception error if triggered)

**Tier 2: NON-OVERRIDABLE DEFAULTS** (Always enforced; protocols cannot disable)
- `no_loose_objects`: floating objects are microgravity hazards
- `container_empty_before_close`: all modules must be returned before sealing

**Tier 3: OVERRIDABLE DEFAULTS** (Protocols can replace or disable)
- `one_module_at_a_time` (contamination control, default ON)
- `sealed_before_return` (module must be re-sealed before returning)
- `lid_stow_required` (12s timeout to reach stow_zone)
- `out_of_order`, `skip`, `wrong_object` (sequence violation reporting)

### 3.3 Violation Codes

| Code | Meaning | Severity |
|---|---|---|
| `skip` | Required step never completed | Warning |
| `out_of_order` | Step attempted before dependencies | Caution |
| `wrong_object` | Wrong module for this step | Caution |
| `mutual_exclusion_breach` | Two modules out simultaneously | Caution |
| `lid_unstowed` | Lid not secured within 12s | Caution |
| `module_not_sealed` | Module returned without sealing | Caution |
| `module_not_returned` | Module outside container at close | Warning |
| `premature_close` | Container sealed while module out | Warning |
| `loose_object` | Object floating free | Warning |
| `wrong_orientation` | Incorrect insert angle | Advisory |

### 3.4 Operator Authority Principle

> **The astronaut is always the authority.** On violation: alert once, log, continue. Never block, never lock, never repeat.

- `OPERATOR_OVERRIDE` is a logged event — astronaut can always override.
- Session resume: reload a session log and pick up mid-protocol.
- **Hot reload**: protocols reloadable at runtime without restart.

### 3.5 Alert Policy (Why Restraint Matters)

A single root error can cascade into 4+ alertable conditions in 12 seconds. An astronaut who hears 4 alerts in 12 seconds will **mute the system**, and a muted system has zero mission value.

Alert policy rules:
- **One alert per root cause** — suppress downstream consequences.
- `root_cause_cooldown_s: 8` — 8 seconds before same root fires again.
- `max_alerts_per_minute: 4`
- Severity: `advisory` (tone only) -> `caution` (tone + speech) -> `warning` (interrupts)
- **Log everything**, speak only the root cause.

---

## 4. Dataset

### 4.1 Video Corpus

| Property | Value |
|---|---|
| **Total clips** | ~60 unscripted + ~20 with ArUco fiducials (batch 2) |
| **Duration per clip** | 30–58 seconds |
| **Frame rate** | 30 FPS (at least one is variable frame rate — handled by normalization) |
| **Resolution** | ~848 x 478 |
| **Nature** | **Unscripted** — astronaut-like glovebox manipulation, no protocol was followed |

### 4.2 Prop Families in the Dataset

| Family | Shape | Lid Type | Protocol Role |
|---|---|---|---|
| `jar` | Cylindrical | Screw cap | **Primary demo prop** — drives `bas_specimen_v1` |
| `box` | Rectangular | Hinged | Trains detector; secondary demo |
| `slab` | Rectangular | No lid | Trains detector; no-lid protocol variant |

### 4.3 Dataset Characteristics

- **Mixed gloved and bare hands** — roughly half the clips use white latex gloves.
- **Thread-suspended drift simulation** — simulates free-floating objects in microgravity.
- **Objects leave frame** — tracking must handle `LEFT_FRAME` as distinct from `OCCLUDED`.
- **No ArUco tags in batch 1** — rack-space normalization awaits batch 2.
- **No annotation stow zone** in batch 1 clips.

### 4.4 YOLO Detector Class List (Final — After Batch 1 Separability Review)

After reviewing 40 candidate-ambiguous frames from the pilot corpus:

```
case_open, case_closed, red_module, yellow_module, red_lid, yellow_lid, hand
```

**Deliberately rejected classes (with reasoning):**

- `module_in_case` / `module_free` — rejected: containment is a **position** question
  (rack-space centroid inside bbox), not an appearance question. A module looks identical
  whether inside the case or sitting just outside it from directly overhead.

- `case_half_open` — rejected: lid angle is a **continuum**, not a class. Computed
  geometrically by `src/kinematics/lid_state.py` from the lid bbox, with hysteresis.
  Discretizing it into a classifier class throws away precision the geometry already has.

### 4.5 Phase 1 Data Pipeline

```
clips/ (raw video)
    |
    v  normalize_clips.py
clips_norm/ (CFR 30 fps, landscape orientation, no audio)
    |
    v  extract_frames.py
frames/ (2.5 fps sampling, dHash dedup, ~40-60 frames per 45s clip)
    |
    v  build_review_sheet.py    <- HARD HUMAN CHECKPOINT (must stop here)
manifest/clips.csv (session_id blank, metadata derived)
    |
    v  [Human fills session_id, corrects guessed columns]
    |
    v  split.py
labels/ train / val  (split BY session_id, never by frame -- prevents leakage)
```

**Anti-leakage rule:** Split always by `session_id`. Two frames from the same filming session
can never appear in both splits — a model that memorizes one clip cannot score on its sibling
frames without actually generalizing.

---

## 5. Technology Stack

### 5.1 Core Runtime

| Component | Technology | Version | Rationale |
|---|---|---|---|
| **Language** | Python (python.org build) | 3.13 | Type hints throughout; rich ecosystem; rapid iteration |
| **Object Detection** | YOLOv8 (ultralytics) | 8.3.28 | State-of-the-art real-time detector; CPU-runnable; pretrained backbone |
| **Hand Landmarks** | MediaPipe Hands | 0.10.18 | Real-time CPU landmark detection; finger-tip proximity for grasp |
| **Computer Vision** | OpenCV | 4.10.0.84 | Frame I/O, ArUco detection, solvePnP, bbox geometry |
| **Image Processing** | Pillow | 11.0.0 | Contact sheets, frame review thumbnails |
| **Config Validation** | PyYAML + jsonschema | 6.0.2 + 4.23.0 | Declarative protocol validation with schema enforcement |
| **Concurrency** | threading (not asyncio) | stdlib | CPU-bound inference; OpenCV/YOLO/MediaPipe release GIL — threads actually parallelize |

### 5.2 Velocity Smoothing — One Euro Filter (Casiez et al. 2012)

Rather than a moving average (fixed latency/jitter tradeoff), the system uses the **One Euro Filter**:
- Adapts its cutoff frequency to motion speed.
- **Still at rest** -> aggressive low-pass (smooth, low jitter).
- **Fast motion** -> high-pass (responsive, low latency).
- This is what allows sub-150 ms glass-to-alert while not jittering on a stationary hand.

### 5.3 Data Pipeline Tools

| Tool | Use |
|---|---|
| ffmpeg + ffprobe | VFR to CFR transcoding, portrait rotation detection, metadata extraction |
| dHash (difference hash) | Near-duplicate frame deduplication during extraction |

### 5.4 Testing Infrastructure

| Tool | Version | Use |
|---|---|---|
| pytest | 8.3.3 | 140 unit/regression tests — all passing |
| pytest-cov | 6.0.0 | Coverage reporting |
| Replay harness | — | Headless end-to-end pipeline tests with no camera/video — 9/9 synthetic fixtures passing |

### 5.5 Phase 2 (Planned — Not Yet Built)

| Capability | Planned Technology |
|---|---|
| Text-to-Speech | Platform TTS or pyttsx3 (offline) |
| Earcons / tones | simpleaudio or playsound |
| GUI monitoring | tkinter or PyQt (offline, no web dependency) |
| RTSP video streaming | OpenCV + ffmpeg |
| Voice command ASR | Whisper (offline, CPU) |
| Packaging | PyInstaller (single-file distributable) |

---

## 6. Feasibility of the Tech Stack

### 6.1 Why This Stack Is Viable

**CPU-Only Operation**
YOLOv8 Nano/Small variants achieve 25–30+ FPS on modern laptop CPUs (i5/i7 class).
Target of 25+ FPS is achievable. The constraint engine, kinematics, and logging add
negligible overhead (<2 ms/frame).

**Offline, No Internet**
Every component — YOLO, MediaPipe, PyYAML, jsonschema — operates completely offline.
No API calls, no cloud inference, no network dependency at runtime.

**Sub-150 ms Glass-to-Alert Latency**
The pipeline is structured to meet this:
- Detection: ~30–40 ms (YOLOv8n on CPU)
- Kinematics: <1 ms (pure Python maths)
- Debounce: adds ~5 frames = ~167 ms at 30 FPS (configurable down to 3 frames)
- Engine + alert: <1 ms

The debounce window is the primary latency driver. At 5-of-8 frames (step_debounce_frames: 5),
debounce adds approximately 167 ms worst-case but prevents false alerts. Tunable per protocol.

**Microgravity Robustness — Rack-Centric Normalization**
cv2.solvePnP with ArUco fiducials is a solved problem used in AR applications at 30+ FPS.
The rack-space approach eliminates the gravity assumption entirely, making the system
orientation-agnostic.

**Gloved Hand Handling**
MediaPipe Hands is primarily trained on bare skin. White latex gloves reduce texture contrast.
We benchmark this explicitly (scripts/test_mediapipe_gloves.py — 200 frames, detection rate
and landmark jitter split by gloved vs bare). If gloved detection rate falls below 85%, we
fall back to YOLO hand bboxes + motion coherence. Grasp is detected from bbox proximity +
correlated velocity rather than finger-tip landmarks.

**Safety-Critical Correctness — Deterministic Engine**
The constraint engine is deterministic and fully unit-tested. There is no probabilistic
inference in the safety path. The same input always produces the same output. Verifiable
and auditable — essential for a crewed space environment.

**Hot Protocol Reload — Live Demo Feature**
A judge can edit configs/protocols/bas_specimen_v1.json and the system reloads and enforces
the new protocol without restart. Demonstrates data-driven protocol definition live on stage.

### 6.2 Known Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| MediaPipe fails on gloved hands | Medium | YOLO hand bbox + motion coherence fallback; benchmarked before building |
| YOLOv8 too slow on target CPU | Low | Use YOLOv8n (Nano); profile on actual hardware; drop to YOLOv5n if needed |
| Debounce adds too much latency | Medium | Configurable; min 3-of-5 frames = ~100 ms; protocol-tunable |
| ArUco detection unstable (batch 2) | Medium | Fallback to image-space geometry for batch-1 clips; rack-space for batch-2 |
| Class list changes after labelling starts | Low | Separability check done on real frames before labelling; class list is FINAL |
| Train/val data leakage | Mitigated | Session-keyed split enforced in code; hard-fail if session appears in both |

### 6.3 What Requires Code Changes vs. Data Changes

| New Requirement | What It Needs |
|---|---|
| Different step order, same actions | Protocol JSON only — no code |
| Different constraints (concurrency allowed) | Protocol JSON only — no code |
| Different objects, same action types | Profile YAML + detector fine-tune — no code |
| A genuinely new action (pour, stir, weigh) | New primitive in code — honest boundary |

This is the **no-code-change claim** stated accurately on the limitations slide.

---

## 7. Current Build Status

| Phase | Status |
|---|---|
| **Phase 0** — Engine, harness, no video | Complete. 140/140 pytest passing, 9/9 synthetic harness fixtures passing |
| **Phase 1** — Data pipeline (5-clip pilot) | Pilot complete. Review sheet and separability check done. Class list finalized. |
| **Phase 1** — Full corpus (55 remaining clips) | Awaiting: human review of manifest/clips.csv, then hand-labelling per LABELLING_GUIDANCE.md |
| **Phase 2** — Detector training, GUI, audio, RTSP | Planned — depends on labelled corpus |

---

## 8. Key Differentiators (Slide Talking Points)

1. **No gravity assumption** — rack-centric normalization via ArUco makes the system
   orientation-agnostic. The only space-aware HAR system in this competition.

2. **Deterministic safety layer** — violations are computed by a constraint-graph state
   machine, not predicted by a neural network. The safety-critical path has zero
   probabilistic hallucination.

3. **Protocol as data** — swap a JSON file to define a completely new experiment.
   No retraining, no code changes (for same action primitives).

4. **Alert restraint** — one voice alert per root cause per cooldown window. The log
   is complete; the voice is surgical. An astronaut who trusts the alert system uses it;
   one who does not, mutes it — and a muted system has zero mission value.

5. **Tamper-evident logging** — SHA-256 hash-chained JSONL. Any post-hoc alteration of
   the mission log is detectable. Same principle as blockchain secure audit trails.

6. **Honest capability reporting** — the system reports "unimplemented" for capabilities
   it does not yet have, never a fabricated confident answer.

7. **Fully offline** — no network calls at runtime, anywhere. Verifiable by code review.
   Critical for a crewed space environment where connectivity is unreliable.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **BAS** | Bharatiya Antariksh Station — India's planned crewed space station |
| **HAR** | Human Activity Recognition |
| **Glovebox** | Sealed enclosure for handling sensitive/hazardous specimens in space |
| **ArUco** | Binary square fiducial markers used for camera pose estimation |
| **solvePnP** | OpenCV function that computes 3D pose from 2D-3D point correspondences |
| **Rack space** | Coordinate system defined by the experiment rack, not image pixels |
| **CFR** | Constant Frame Rate — normalized from VFR (Variable Frame Rate) |
| **VFR** | Variable Frame Rate — common in phone recordings; breaks frame-based sampling |
| **dHash** | Difference hash — perceptual hash for near-duplicate image detection |
| **One Euro Filter** | Adaptive low-pass filter with speed-dependent cutoff for velocity smoothing |
| **k-of-n debounce** | Require k positive detections in the last n frames before committing a state change |
| **Protocol** | JSON file declaring steps, roles, zones, and constraints for one experiment type |
| **Profile** | YAML file binding abstract protocol roles to physical YOLO detector classes |
| **Constraint engine** | Deterministic state machine that enforces protocol rules |
| **Hot reload** | Reloading a protocol JSON at runtime without restarting the system |
| **OPERATOR_OVERRIDE** | Logged event when the astronaut overrides a violation and proceeds |
| **Root cause** | The first violation in a causal chain; suppresses downstream cascade alerts |
