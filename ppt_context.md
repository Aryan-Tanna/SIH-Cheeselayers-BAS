# BAS Glovebox HAR Co-Pilot — PPT Context Document

> **Team:** Cheeselayers · **Competition:** Smart India Hackathon
> **Problem Statement:** PS 26174 — *AI Human Activity Recognition for On-board BAS Experiments* (ISRO / Department of Space)
> **Rule for every slide:** only numbers from this file, with their sample size. Where it says "not measured", the slide says so too.
> Last updated 2026-09-29.

---

## 1. The problem, in the PS's own terms

Astronauts on the Bharatiya Antariksh Station run experiment protocols with no real-time ground support
(communication delay; bandwidth to Earth too restricted to stream raw video). The PS asks for an on-board,
offline system that watches a fixed payload camera and:

| PS requirement | What we built | Evidence |
|---|---|---|
| Continuously track the experiment sequence from local video | Detector + fusion turn frames into step events; a constraint engine tracks the protocol | 17/18 expected events on 3 verified held-out clips (S05) |
| Suggest the next step at the start and after each step | Spoken prompt + GUI "NOW" banner; optional steps never pushed | synthetic harness + live runs |
| Voice alert when a step is **skipped** or **out of sequence** | `skip`, `out_of_order`, `wrong_object` alerts | 16/16 synthetic fixtures, 0 false alarms |
| …or when an out-of-sequence step is **added** | `extra_step` rule (new): an action no remaining step asks for | fixture + unit tests; real-clip false-alarm rate below |
| Timestamped, structured, lightweight text file of steps and outcomes | Hash-chained JSONL log + readable `report.txt` per session | chain verified on every session end |
| Stream video to an IP and store it locally | One H.264 encode → local MPEG-TS segments + UDP stream | LAN-tested to a phone (VLC) |
| GUI for monitoring | Co-pilot GUI (crew) + **Mission Control** (ground) | screenshots in the deck |
| Trained model running offline, standalone | YOLOv8n-OBB v5 (ONNX, CPU), packaged app build | held-out mAP50 .89 |
| Dataset for object detection, pose, hand-object interaction | 1032 hand-labelled frames (detector). Hands: MediaPipe (off the shelf), grasp = fingertip rules | see §6 limits |
| Optional: orientation-agnostic body tracking (HMR) | Not HMR. ArUco markers on the rig → image-to-rack mapping (planar homography) | see §6 |

**Our sample experiment** (the PS: "a box that contains two smaller boxes of color red and yellow"):
open the container → take out each module → unseal, stow cap, reseal → return it → seal the container.
Modules in either order, one out at a time (configurable). 12 steps, `configs/protocols/bas_specimen_v1.json`.

---

## 2. Architecture — three layers, one deterministic core

```
camera ──► capture (timestamp at acquisition) ──► recorder: local .ts + UDP stream
              │
              ├─► detector (YOLOv8n-OBB v5, ONNX, CPU) ─► fusion: k-of-n votes + min hold
              │        + ArUco rack mapping                 → open / remove / return / cap off / cap on
              ├─► hand skeletons (MediaPipe, own thread) ─► "holding" cue, activity line
              ▼
        PROTOCOL ENGINE (deterministic constraint graph) ─► alert policy ─► voice (Piper, offline)
              │                                                           └► GUI
              ├─► hash-chained JSONL log ─► report.txt
              └─► EARTH DOWNLINK: log lines + 1 JPEG per step/alert ─► MISSION CONTROL (ground)
```

- **Vision identifies objects**; it never decides safety.
- **The engine decides**: a constraint graph over steps (a *set* of due steps, not a list index), fed by
  semantic events. Same input → same output, every time. No neural network in the alert path.
- **Protocols are data**: steps + inherited safety rules (`configs/defaults.yaml`). The resolved rule set is
  printed at start-up, each rule marked `[default]` or `[protocol]`.

---

## 3. The protocol engine

**Rules (defaults.yaml), three tiers:**
- *Physical impossibilities* (engine, cannot be disabled): a module can't leave a closed container; a lid can't be stowed before it is off.
- *Non-overridable safety*: `container_empty_before_close`, `no_loose_objects` (declared; see §6: not triggerable on this rig).
- *Overridable*: one module at a time, sealed before return, lid stow timeout, attended while open, out-of-order, skip, wrong object,
  **extra step** (new), **step time limit** (new, per step, opt-in).

**Violation codes:** skip · out_of_order · wrong_object · extra_step · mutual_exclusion_breach · lid_unstowed ·
unattended_open_module · module_not_sealed · module_not_returned · step_overdue · (loose_object, wrong_orientation: declared, not live).

**Operator authority:** alert once, log, continue — never block. "Hey BAS, next step" confirms a step the camera
missed (logged as operator-confirmed). Pause / resume / repeat / quiet by voice. Session resume from a log.

**Alert restraint:** one spoken alert per root cause (8 s cooldown, max 4/min); the log keeps everything.
A cascade of 6 violations from one root cause is spoken once (synthetic fixture `cascade`).

**Extra-step rule, measured honestly:** detector jitter looks exactly like an extra action (a screw cap resting on the
jar reads closed → open → closed within ~2 s). So an extra action that is undone within `settle_s` (3 s) is logged,
not spoken. On real clips: 2 of 3 verified correct runs give **0** extra-step alerts; 1 gives 2 (jar hovering at the rim —
the known early-return limit). Across 7 clips: 26 → 10 extra-step alerts after the settle window.
After "Experiment complete." extra actions (packing the props away) are logged, never spoken.
*Caveat: the window was chosen from the tune-clip hover measurement, but we had already seen the held-out clips — validate on fresh clips.*

**Protocol editor (GUI, key E):** add / reorder steps and groups, "after" ordering, per-step **time limit**,
**optional** steps (the in-protocol way to *allow* an extra action), per-group "modules out together",
every rule's on/off / severity / timer / spoken alert. Saves only through the validator; the validator refuses
anything the engine would not enforce (no silent, inert rules). Hot reload: the running session switches without restart.

---

## 4. Earth downlink + Mission Control (the bandwidth premise, measured)

The PS says raw video to Earth is not viable. So the co-pilot sends **the log line by line and one JPEG per step
completion and per alert** — never video — to a ground station (`scripts/ground_station.py`).

- **Store-and-forward:** everything is kept on board until the ground acknowledges it; after a loss of signal it resends from
  where the ground stopped. Tested: ground station killed mid-session and restarted → archive **byte-identical** to the on-board log.
- **Verified on the ground:** every line is checked against the hash chain as it arrives (one altered line → "LOG TAMPERED");
  every image's sha256 is **written into the chain** on board, so the ground marks it VERIFIED only if the system attested it.
- **Light-time simulation:** `--link-delay 1.3` (Moon) for the demo; a bandwidth cap too.

| One real session (clip Dataset12, 32.5 s, 12 steps) | Bytes |
|---|---|
| Log (39 hash-chained lines) | 30 KB |
| 12 JPEG snapshots (640 px, q70) | 452 KB |
| **Total downlink** | **486 KB ≈ 120 kbit/s average** |
| Same session as local H.264 video (15 fps, CRF 28) | 3.6 MB |
| Log only (if images are switched off) | ≈ 7 kbit/s |

Mission Control shows: LIVE / NO SIGNAL, LOG VERIFIED / TAMPERED, delay, data received (log vs images),
the checklist as executed on board, the event feed, the latest image with its verification, a thumbnail strip,
the session report when it arrives, and a "simulate loss of signal" button.

---

## 5. Measured numbers (with where they come from)

| What | Number | Sample |
|---|---|---|
| Detector v5, held-out sessions S01+S03 | mAP50 **0.89** (ONNX 0.894) | frames from sessions never trained on |
| …per session | S01 0.917, S03 0.775 | S03 partly resembles a training session (S02) |
| Clip-level events, verified held-out (S05, ArUco rig) | **17/18** | 3 clips, hand-verified timelines |
| Clip-level events, other held-out | 11/13 | 2 clips (Parth's setup) |
| Synthetic harness | **16/16** fixtures, 0 false alarms, 15/15 alerts as expected | engine + alerts, no video |
| Unit/regression tests | 598 (597 pass, 1 skip: clip not on this PC) | pytest, 2026-09-29 |
| Detector speed, this laptop, live on a clip | **15–29 fps**, 46–82 ms camera→detections | 6 runs today, 2 clips; varies run to run |
| Detector speed with the Earth link on (12 images sent) | 22.3 and 21.0 fps — inside the 19.2–29.4 fps spread of runs without it | 2 full runs with the link, 2 without; small sample |
| Detector speed, second laptop, skeletons on | ~11 fps | Parth's measurement |
| Step event latency | ~1 s **by design** (1.0 s hold + k-of-n vote) | config; prevents flicker false alarms |
| Voice | phrases pre-rendered (Piper 0.4–0.9 s/phrase at load); 22 ms audio output (WASAPI) | measured |
| Wake phrase "Hey BAS" | 13/17 real utterances accepted | quiet room, one speaker; noise untested |
| Rack mapping (ArUco) | 1.0 px median reprojection; markers found to 50° tilt | clips not used for fitting |
| Recording crash-safety | MPEG-TS kept 96/105 frames after an encoder kill (MP4: 69/105) | measured |

**Not measured (say so on the slide):** end-to-end camera-to-voice latency; the original "25 FPS, sub-150 ms"
targets are targets, not results — event latency is ~1 s by design; gloved-hand accuracy on a held-out session;
voice commands with background noise.

---

## 6. Honest limits (the judges will ask)

| Limit | Why / what we do instead |
|---|---|
| **HMR (3D body mesh) not used** | SMPL-based HMR is a heavy GPU model; the PS makes it optional. We track hands + objects relative to the rack. *We have not benchmarked HMR ourselves — don't quote a ms figure.* |
| **Rack mapping is planar** | ArUco markers lie flat on the rig floor → a homography (the correct maths for a plane), not a full 3D pose. Rack-space containment is built but **off by default**: it measured a tie with image space (17/18 each). |
| **Only the object detector is trained** | Hand skeletons are MediaPipe (off the shelf); "holding" and the activity line are rules on top. We present them as *derived activity*, not a trained HAR model. |
| **Gloves** | MediaPipe gives no skeleton on white latex gloves; the detector has a gloved-hand class, but no held-out gloved session exists yet. |
| **Kinematics library** | One Euro filter, grasp coherence, drift, intent are written and unit-tested but **not wired live**; only the fingertip cue runs. Drift needs a tracker and drift footage. |
| **loose_object** | Declared, non-overridable — but with the team rule "the whole camera view is the stow area" it can never trigger. Needs a real stow zone on the rig. |
| **Hover** | From above, a jar hovering over the open box reads as returned up to ~3 s early. |
| **New actions** | A genuinely new kind of action (pour, weigh) needs a new primitive in code; new order / rules / props do not. |

---

## 7. What makes it different (talking points)

1. **Deterministic safety core** — alerts come from a constraint graph, not a neural net's guess. Auditable.
2. **Protocol as data, editable in the GUI** — new experiment, new order, time limits, optional steps, rules; validated, hot-reloaded.
3. **The PS's bandwidth premise, solved and measured** — ~486 KB per session instead of video; store-and-forward; verified on the ground.
4. **Tamper-evident end to end** — hash-chained log on board, verified line by line on Earth; images attested inside the chain.
5. **Alert restraint** — one voice per root cause; a crew member who trusts the alerts keeps them on.
6. **Measured, not claimed** — held-out split by recording session (no leakage), real-clip replays, every number with its sample size.
7. **Offline, enforced** — detector, voice (Piper), speech commands (Vosk) all local; an audit hook in the process refuses any
   connection or DNS lookup outside the local network except the configured Earth IP (full live run: 0 blocked attempts);
   an OFFLINE badge shows it. Cameras must be local-network IPs.

---

## 8. Demo script (5 minutes)

1. Ground PC: start screen → **This PC is: EARTH** → read out its IP → **Start receiving**.
   Station PC: **SPACE STATION** → experiment, props, camera (IP camera… → Test) → tick **Send to Earth** (that IP) + **Moon delay** → Start.
2. Do the procedure correctly: prompts spoken, checklist ticks, "Now doing" line, EARTH badge counting KB.
3. Make mistakes on purpose: skip a step → "Missed on the red module…"; take a returned module out again → "That step is not part of the procedure."
4. On Mission Control: the same checklist, images arriving 1.3 s later marked VERIFIED, LOG VERIFIED.
5. Press **Simulate loss of signal** → NO SIGNAL; keep working; link returns → nothing lost.
6. Protocol editor: add a 30 s time limit to a step, save → running session enforces it immediately.
7. End session → open `report.txt`; Mission Control shows "SESSION COMPLETE".
**Fallback:** the same flow on a recorded clip (Video file… on the start screen) if the live camera misbehaves.

---

## 9. Glossary

| Term | Meaning |
|---|---|
| BAS | Bharatiya Antariksh Station |
| HAR | Human Activity Recognition |
| ArUco | Printed square markers; four on the rig give the image-to-rack mapping |
| Homography | The exact mapping between two planes (camera image ↔ rig floor) |
| k-of-n + hold | A state change needs k of the last n frames and must persist ≥ hold time before it counts |
| Hash chain | Each log line includes the previous line's hash: altering any line breaks every later one |
| Store-and-forward | Keep data until the receiver confirms it; resend after a drop |
| Protocol / profile | JSON of steps + rules / YAML binding roles (container, module) to detector classes |
| Settle window | Time an extra action must persist before it is alerted (filters detector jitter) |
