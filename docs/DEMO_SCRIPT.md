# Demo video script — BAS Co-Pilot (full version ≈ 9 min, short cut ≈ 3 min)

Everything the app does, in an order that tells one story: *a crew member on
the station does an experiment; Earth follows it; the system catches every
mistake; the record can't be faked; it works with or without a link.*
All spoken alert lines below are the app's **exact** words.

---

## 0. Cast, devices, recording

| Device | Role | What it runs |
|---|---|---|
| **Laptop A** (you) | 🛰 Space station | `BAS-Copilot.exe` → **SPACE STATION** |
| **Phone 1** on a stand over the box | the station camera | DroidCam app (fixed, never hand-held) |
| **Laptop B** (teammate) | 🌍 Earth | `BAS-Copilot.exe` → **EARTH**, or `py scripts\ground_station.py` |
| **Phone 2** | films the glovebox from the side; later shows the live video stream in VLC | camera app, VLC |

**Recording:** OBS on Laptop A (screen + Phone 2 as a second source if you can)
and OBS on Laptop B (screen). Start both, then **clap once in front of Phone 1**
so you can line the recordings up in editing.

**Props at the start:** container **closed**, red and yellow modules inside,
caps on. ArUco markers taped on the tub floor.

## 1. Pre-flight checklist (do it 10 min before)

- [ ] Laptop A: close browser + code editor → Task Manager shows **≥ 3 GB free**.
- [ ] Laptop B: Mission Control open; `ping <B's IP>` from A answers (hotspot or Tailscale).
- [ ] Phone 1: DroidCam running; A and phones on the same Wi-Fi / hotspot.
- [ ] Laptop A start screen: **IP camera… → Test** shows the picture.
- [ ] Say "Hey BAS, repeat" once — the MIC badge is not SILENT.
- [ ] Rack: markers visible → after Start the badge says **RACK ok** (else Rack setup [K] → Calibrate).
- [ ] A recorded clip is ready as a fallback (start screen → **Video file…**).
- [ ] Optional: start Laptop A's app with `BAS-Copilot.exe --stream-to <Phone 2 IP>` for Act 12.

---

## ACT 1 — The problem (0:00–0:25)
**Show:** title slide, then Phone 2's shot of the glovebox.
**Say:** "On the Bharatiya Antariksh Station nobody on Earth can watch an
experiment live — signals are delayed and the link is too thin for video.
BAS Co-Pilot watches instead: offline, on an ordinary laptop."

## ACT 2 — Two computers: station and Earth (0:25–1:00)
**Laptop B:** start screen → top right **EARTH (receiver)** → it shows its IP
in big green → **Start receiving**. Mission Control opens: *waiting for the co-pilot*.
**Laptop A:** start screen → **SPACE STATION (sender)**.
**Say:** "One app, two roles. This laptop is Earth — it tells the station
where to send. This one is the station."

## ACT 3 — Setting up the experiment (1:00–2:00)
**Laptop A, start screen:**
1. Select **Dual specimen module inspection** → the 12 steps appear on the right.
2. **Props on the rig** → *As the experiment specifies* (jars with screw caps).
3. **IP camera…** → DroidCam, type Phone 1's IP → **Test** → the preview appears → **Use this camera**.
4. *Offline proof:* open **IP camera…** again, type `8.8.8.8` → it refuses:
   *"8.8.8.8 is an internet address - the co-pilot only uses cameras on the local network."* Close it.
5. Tick **Send to Earth**, type Laptop B's IP, tick **simulate Moon light-time (1.3 s)**.
6. **Start experiment ▶**.
**Say:** "It runs fully offline — it even refuses an internet camera. The only
place it may send data is the Earth address we typed."

## ACT 4 — What the camera sees (2:00–2:30)
**Laptop A, session screen.** Point at the top badges: **RUNNING, MIC, DET … fps, RACK ok, REC, EARTH ●, OFFLINE ✓**.
Press **D** (detections on): boxes on the container and modules, the ArUco
markers, the hand skeleton. Press **H** for two seconds (help), close it.
**Say:** "A detector we trained on our own labelled frames finds the
container, both modules, their caps and my hands. Four markers on the rig
tell it where the rack is. Every badge is live health: speed, camera,
recording, Earth link — and OFFLINE, meaning nothing leaves this network."

## ACT 5 — A correct run (2:30–3:45)  · session 1
Just do it, calmly. The co-pilot speaks each step:
*"Open the payload container."* → open it → ✓ → *"Container open. Select a specimen module."*
*"Remove the first specimen module."* → take the **red** jar out → ✓
*"Unseal the module."* → unscrew the cap → ✓ (and *Secure the lid…* ✓ — the whole view is the stow area)
*"Reseal the module."* → screw it back → ✓
*"Return the module to the container."* → put it back → ✓ → *"First module secured."*
Point at: the checklist ticking, the big **NOW** bar, **Now doing: Handling the red module cap**.
Mid-way say **"Hey BAS, repeat"** → it repeats the current step.
**Cut to Laptop B:** the same ticks arrive ~1.3 s later, a photo for every step with
**VERIFIED - sha256 attested in the hash-chained log**, **DELAY 1.3 s**, **DATA** in KB.
Finish the yellow module and **seal the container** → *"Experiment complete. Log written."*
**Say:** "Earth gets the log line by line and one photo per step — never
video. About half a megabyte for the whole experiment."

## ACT 6 — Mistakes, one alert each (3:45–5:15)  · session 2
Restart: say **"Hey BAS, restart experiment"** twice (or the Restart button) → a new session and log.
Open the container, then make these mistakes **one at a time, slowly**:

| Do this | You hear |
|---|---|
| Take the **red** jar out, then also take the **yellow** jar out | *"Return the current module before accessing another."* |
| Put yellow back. Unscrew red's cap, **pull both hands out of view** for 6 s | *"Module left open. Return to the open module."* |
| Hands back, put red back in **without** screwing the cap on | *"Module returned unsealed."* (+ the skipped reseal is logged) |
| Take red out **again** (already returned) and hold it 5 s | *"That step is not part of the procedure."* |
| Put it back, **close the container** while yellow is still to do | *"Container sealed with a module still outside."* / *"Missed on the yellow module: …"* |

**Point at:** red ✗ lines in the checklist and EVENTS; on Laptop B the same
alerts in red, each with a photo of the moment.
**Say:** "One clear alert per mistake — never a stream of beeps, so the crew
keeps it on. The log keeps everything, the voice speaks only what matters.
And it never blocks the astronaut: they are always in charge."

## ACT 7 — Voice control, hands-free (5:15–5:45)
- **"Hey BAS, pause"** → *"Paused. Say hey bass, resume, to continue."* (badge PAUSED)
- **"Hey BAS, resume"** → *"Resuming."*
- **"Hey BAS, quiet mode"** → *"Quiet mode. Alerts only."*, then **"voice mode"**.
- Do a step with your hand hiding it from the camera, then **"Hey BAS, next step"** → *"Marked done."* — the checklist shows it **purple (confirmed by operator)**.
**Say:** "Gloved hands are busy, so everything works by voice — offline speech
recognition, no internet. If the camera misses something, the astronaut
confirms it, and the log records that it was the operator, not the camera."

## ACT 8 — Loss of signal (5:45–6:15)
**Laptop B:** press **Simulate loss of signal** → badge **NO SIGNAL - buffering on board**.
**Laptop A:** EARTH badge → *no link, N buffered*. Keep working (one step).
Link returns in a few seconds → Earth catches up, still **LOG VERIFIED**, nothing missing.
**Say:** "If the link drops, nothing is lost — the station keeps everything and
resends exactly what Earth is missing, never a duplicate."

## ACT 9 — End of session, the record (6:15–6:45)
**Laptop A:** **End session** → back on the start screen: *Last session … log verified* → **Open report**
(show `report.txt`: every step with its time and how it was seen, every violation).
**Sessions (this station)** tab: all sessions, steps, alerts, *log verified*.
**Laptop B:** **SESSION COMPLETE - all data received** → **Open session report** (the same report, on Earth).

## ACT 10 — No link at all: send later (6:45–7:20)  · session 3
**Laptop A:** untick **Send to Earth** → Start → open and close the container → End session.
**Sessions** tab → this session says **not sent** → select it → **🌍 Send to Earth**.
**Laptop B:** it arrives, marked **SENT LATER - recorded offline on board**, with its photos and report.
**Say:** "Most of the time a station has no link. Everything is stored on board
and sent in one click when a link window opens."

## ACT 11 — The record can't be faked (7:20–7:50)
Use a **throwaway** session (e.g. session 3 after sending, or a spare one):
open `logs\<session>.jsonl` in Notepad, change one character (e.g. a step name), save.
**Sessions** tab → **Refresh** → its log column says **BROKEN**.
Select it → **Send to Earth** → Laptop B: **LOG TAMPERED**, naming the line.
**Say:** "Every line is chained to the one before by a cryptographic hash —
change one character and both the station and Earth know."

## ACT 12 — Change the experiment, no code (7:50–8:30)
**Laptop A:** Start any session → **Protocol editor [E]** →
select *Open the payload container* → **Time limit (s): 15** → Apply →
**Save as new experiment…** → name it → the running session switches to it.
Wait 15 s without opening → *"This step is taking longer than planned."*
Show the **Rules** tab: every safety rule, on/off, severity, spoken alert (safety-critical ones LOCKED).
**Say:** "Experiments are data. New steps, order, time limits, rules — edited
here, checked by a validator, live immediately."

## ACT 13 — Video, stored and streamed (8:30–8:45)
**Phone 2:** VLC → Open network stream `udp://@:5000` → the station's live video
(only if Laptop A was started with `--stream-to <Phone 2 IP>`).
**Laptop A:** the `recordings\<session>` folder → play a segment in VLC.
**Say:** "Video is recorded on board and can be streamed on the local network —
but what goes to Earth is the log and the photos."

## ACT 14 — Close (8:45–9:00)
**Show:** a slide with the measured numbers:
0.89 detection accuracy on recordings it never saw · 17/18 steps on hand-checked test videos ·
16/16 rule scenarios, 0 false alarms · ~0.5 MB per experiment to Earth instead of video ·
600 automated tests.
**Say:** "BAS Co-Pilot watches, guides, warns and reports — offline, on a laptop.
Thank you."

---

## Short cut (≈ 3 min) for the submission
ACT 1 (20 s) → ACT 3 steps 3–6 (30 s) → ACT 5 red module only + Earth cut (50 s) →
ACT 6 rows 1, 4, 5 (45 s) → ACT 8 (15 s) → ACT 10 (15 s) → ACT 14 (10 s).

## Optional extras (if time)
- **Gloves:** put on a latex glove → the line says *"1 gloved hand (no skeleton)"*; the detector still sees the hand.
- **Rack setup [K]:** Auto-detect → Calibrate (4 s) → Save & apply → RACK ok.
- **The app as an .exe:** show the unzipped folder and double-click — "no Python, no installation".

## If something goes wrong while recording
| Problem | Do |
|---|---|
| A step is not ticked | "Hey BAS, next step" — shown purple, logged as operator-confirmed (a feature) |
| Voice not heard | check the MIC badge; use the N / Space / R keys |
| Earth not LIVE | the station keeps everything: do ACT 10 (send later) instead |
| Phone camera drops | it reconnects by itself in seconds; or use **Video file…** with a recorded clip |
| App closes by itself | memory: close other apps (≥ 3 GB free) and restart |

## Do not claim on camera
- Full-body 3D pose (HMR) — we track hands and objects relative to the rig.
- Finger tracking on gloves — the skeleton works on bare hands only.
- Voice in a noisy room — not yet tested; record in a quiet room.
