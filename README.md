# BAS Co-Pilot

**An offline AI assistant for experiments on the space station: it watches the
experiment through a camera, tells the astronaut the next step, warns by voice
when a step is skipped or done out of order, and writes a tamper-proof record.**

Smart India Hackathon 2026 · Problem Statement **26174** — *AI Human Activity
Recognition for On-board BAS Experiments* (ISRO / Department of Space) ·
Team **Cheeselayers**

![The co-pilot during an experiment](docs/img/copilot_session.jpg)

---

## ⬇️ Download and run (Windows)

1. Go to this repository's **[Releases](../../releases)** page and download
   **`BAS-Copilot-windows.zip`** (≈ 325 MB).
2. Unzip it anywhere and double-click **`BAS-Copilot.exe`**. No Python, no
   installation, no internet needed.
3. Choose what this computer is (top right): **SPACE STATION** (runs the
   experiment) or **EARTH** (Mission Control). `README.txt` inside the zip has
   the one-page guide.

**Needs:** Windows 10/11 · 8 GB RAM (about 3 GB free while running) · a webcam,
or a phone used as a camera over Wi-Fi · speakers; a microphone for voice commands.
*macOS/Linux: run from the source code (see [For developers](#for-developers)).*

---

## The problem

On the Bharatiya Antariksh Station there is no real-time help from the ground:
signals are delayed and the link to Earth is too limited for video. Astronauts
still have to carry out every experiment exactly, step by step. The PS asks for
an on-board, offline system that recognises what the astronaut is doing,
checks it against the experiment's procedure, and helps in real time.

**Our sample experiment** (from the PS: *a box that contains two smaller boxes,
red and yellow*): open the container → take out a module → unscrew its cap →
put the cap down → screw it back → return the module → the same for the second
module → close the container. 12 steps.

## How we answer the PS

| The PS asks for | What we built |
|---|---|
| Continuously track the experiment from local video | A trained detector + a procedure checker follow every step, live |
| Suggest the next step, at the start and after each step | Spoken by voice and shown on screen |
| Voice alert when a step is skipped or an out-of-sequence step is added | One clear spoken alert per mistake: skipped, out of order, wrong object, extra step |
| A timestamped, structured, lightweight text log of steps and outcomes | A hash-chained log file (every edit detectable) + a readable report per session |
| Stream the video to an IP and store it locally | Video recorded on the laptop and streamed on the local network |
| A GUI for monitoring | The crew screen, plus **Mission Control** for Earth |
| Dataset generation for object detection, pose and hand-object interaction | Our own videos, frames extracted and hand-labelled; hand pose + hand-object cues |
| A trained AI model that runs on an offline standalone system | Our detector, trained on our dataset, running on a laptop CPU, packaged as an .exe |

---

## Features

**Sees**
- A **detector we trained ourselves** finds the container (open or closed),
  the red and yellow modules, their caps, and bare or gloved hands.
- **Hand skeletons** (21 points per hand) tell when a hand is *holding* an object.
- Four **ArUco markers** on the rig give positions relative to the rack, not
  the camera image.
- A **"Now doing"** line: *Handling the red module cap*, *Yellow module out of the box*.

**Understands and guides**
- A **procedure checker** follows the experiment step by step. Steps may be in
  any allowed order, and it always gives the same answer for the same situation.
- Speaks the **next step** and a **clear alert for each mistake**:
  skipped · out of order · wrong object · a step not in the procedure ·
  two modules out at once · module returned unsealed · container closed with a
  module outside · open module left unattended · step taking too long.
- **One alert per mistake**, never a stream of beeps. Everything goes in the log.
- **The astronaut is always in charge.** It never blocks; "next step" by voice
  marks a step the camera missed (logged as confirmed by the operator).

**Voice, hands-free and offline**
- Natural offline speech for prompts and alerts.
- Voice commands: *"Hey BAS, next step / repeat / pause / resume / quiet mode /
  restart experiment"*, all recognised without internet.

**Records**
- **Session log**: every step, alert and command, with time and confidence.
  Each line is locked to the previous one by a cryptographic hash, so changing
  one character is detected.
- **Report** (`report.txt`) at the end: every step, when and how it was seen, every alert.
- **Video** recorded locally and optionally streamed on the local network.
- **Sessions list** of past runs, each with its report and a verified log.

**Reports to Earth**
- **Mission Control** receives the log line by line and **one photo per step and
  per alert**, never raw video. About 0.5 MB per experiment instead of several MB.
- **Live**, or **fully offline**: everything is stored on board, and one click
  on **Send to Earth** delivers it when a link is available.
- Earth checks every line and every photo as it arrives: **LOG VERIFIED** or
  **TAMPERED**. Nothing is lost if the link drops.

![Mission Control on Earth](docs/img/mission_control.jpg)

**Works offline, by design**
- Runs on a normal laptop CPU. No GPU, no cloud.
- The app **blocks any connection outside the local network**, except the
  Earth address you type in (shown by the OFFLINE badge).

**New experiments without code**
- Experiments are simple files. The built-in **editor** adds or reorders steps,
  sets time limits, marks optional steps and switches rules on or off. A
  validator checks the file, and it applies while running.

---

## The AI model — trained by us

**What it is:** a YOLOv8n-OBB object detector (fast, small, *oriented* boxes
that follow tilted objects), **trained on our own dataset**, exported to ONNX
to run on a laptop CPU.

**How we built the dataset**
1. **Recorded about 100 videos** of the experiment on our own rigs: 6 recording
   sessions, different setups and lighting, bare and white-gloved hands,
   unscripted (people did the steps naturally, including mistakes).
2. **Normalised** the videos (fixed frame rate, rotation) and **extracted
   frames**, dropping near-duplicates automatically.
3. **Hand-labelled 1,032 whole images.** Each training image is a **full camera
   frame** from our videos (not cropped objects), with every object in it
   boxed: container open / closed, red module, yellow module, red cap, yellow
   cap, bare hand, gloved hand (8 classes).
4. **Split by recording session, never by frame.** The test videos come from
   sessions the model never saw, so the score is honest (no near-identical
   frames in both training and test).

**How we trained it:** from the public YOLOv8n-OBB starting weights, 120 epochs
on a GPU, with heavy augmentation (rotation up to 180° because there is no
"up" in space, flips, blur, contrast, noise, compression). We improved it over
several versions, each measured on unseen sessions (v4 → v5 raised mAP50 from
0.77 to 0.89). A v6 and a self-labelling experiment were measured too, and
rejected because they did not beat v5.

**Results (v5, on recording sessions it never saw):**

| | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| All classes | 0.887 | 0.833 | **0.892** | 0.703 |

Per class (mAP50): container open 0.98 · container closed 0.86 · red module
0.92 · yellow module 0.90 · red cap 0.84 · yellow cap 0.76 · bare hand 0.97.
On a CPU: **23 ms per image**.

**What is not ours:** the hand skeleton comes from Google's MediaPipe hand
model, used offline as it is. The "holding" cue and the activity line are our
own logic on top of it. The procedure checker is not a neural network, on
purpose, so that it can never invent a step.

---

## How it works

```
 camera ──► our detector (objects, hands) ─┐
        └─► hand skeletons (holding?) ─────┼─► what happened ──► PROCEDURE CHECKER
            ArUco markers (rack position) ─┘   "red module out"      (fixed rules)
                                               "cap off"                 │
                     ┌──────────────┬───────────────┬──────────────────┼──────────────┐
                     ▼              ▼               ▼                  ▼              ▼
                voice + screen   log (hash-chained)  report.txt   video + stream   Earth link
```

---

## Measured results

| What | Result |
|---|---|
| Detector on unseen recording sessions | mAP50 **0.892** (precision 0.887, recall 0.833) |
| Steps recognised on 3 hand-checked test videos (full pipeline) | **17 of 18** |
| Procedure checker, 16 scripted scenarios | **16/16**, **0 false alarms** |
| Speed on a laptop CPU (live) | 15–29 frames per second |
| Data to Earth for a 33 s experiment | **~0.5 MB** (log 30 KB + 12 photos) vs 3.6 MB of video |
| Log after a link drop / ground restart | **byte-identical** on Earth |
| Automated tests | **600** passing |

All numbers, with sample sizes and how they were measured: [ppt_context.md](ppt_context.md).

## Limits (honest)

- No full-body 3D pose (HMR, optional in the PS). We track hands and objects relative to the rig.
- Hand skeletons work on bare hands. Gloved hands are detected, but without finger tracking.
- The gloved-hand class has no score on an unseen session yet (no gloved recording outside the training session).
- Voice commands are not yet tested in a noisy room.
- Windows is the tested platform. macOS/Linux run from source; untested.

---

## Screenshots

| Space station start screen | Earth start screen |
|---|---|
| ![](docs/img/start_space_station.jpg) | ![](docs/img/start_earth.jpg) |

---

## For developers

```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[vision,audio,dev]"
.venv\Scripts\python.exe scripts\run_gui.py
```
Plus one OpenCV fix after installing; see **[docs/DEVELOPER.md](docs/DEVELOPER.md)**,
which also covers the code map, the data pipeline, training, tests and building the app.

| Folder | What |
|---|---|
| `src/perception/` | detector, turning detections into events, hand pose, ArUco rack |
| `src/protocol/` | the procedure checker, alert policy, experiment loader + validator |
| `src/runtime/` | the app: screens, voice, recording, activity, offline guard |
| `src/link/` | Earth link: sender, receiver, send-later, Mission Control |
| `src/logging/` | hash-chained log, report |
| `configs/` | safety rules, experiments, object profiles, settings |
| `scripts/` | run the app, data pipeline, labelling helpers, training, evaluation, build |
| `harness/`, `tests/` | scenario harness and 600 automated tests |
| `models/` | our detector (ONNX), hand model, offline voice and speech models |

## Documents

| For | Read |
|---|---|
| The presentation: every number, limit and talking point | [ppt_context.md](ppt_context.md) |
| The demo video script | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Setting up an Earth laptop | [EARTH_SETUP.md](EARTH_SETUP.md) |
| Developers | [docs/DEVELOPER.md](docs/DEVELOPER.md) |
| The detector versions and how each was measured | [models/README.md](models/README.md) |
