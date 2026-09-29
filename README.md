# BAS Co-Pilot

**An AI assistant that watches an experiment on the space station, tells
the astronaut what to do next, warns by voice when something goes wrong,
and keeps a tamper-proof record — fully offline.**

Smart India Hackathon · PS **26174** "AI Human Activity Recognition for On-board BAS Experiments" (ISRO) · Team **Cheeselayers**

![The co-pilot during an experiment](docs/img/copilot_session.jpg)

---

## The problem, in one paragraph

On the Bharatiya Antariksh Station there is no one on the ground watching
live: signals are delayed and the link to Earth is too thin for video. An
astronaut still has to do every step of an experiment in the right order.
BAS Co-Pilot is the second pair of eyes: a camera watches the work, the
software checks every step, and it speaks up the moment something is
skipped, out of order, or not part of the procedure.

## What it does

| | |
|---|---|
| 👀 **Watches** | A camera over the glovebox. A trained AI model recognises the container, the red and yellow modules, their caps and the astronaut's hands. |
| 🗣️ **Guides** | Says the next step out loud, and shows it on screen. |
| 🚨 **Warns** | By voice, once per mistake: a skipped step, a step out of order, the wrong object, an extra step that is not in the procedure. |
| 📝 **Records** | A timestamped log of every step and outcome, locked with a hash chain (any edit is detected), plus a readable report. Video is recorded too. |
| 🌍 **Reports to Earth** | Sends the log and one photo per step / alert to Mission Control — **live**, or **later** when a link is available. Never raw video. |
| 🔌 **Offline** | Runs on a normal laptop CPU. No internet, no cloud. The app itself blocks any connection outside the local network. |
| ✏️ **Editable** | Experiments are simple files. A built-in editor adds steps, order, time limits and rules — no coding. |

## How it works

```
 CAMERA ──► AI model finds objects & hands ──► "container opened", "red module out", "cap off" ...
                                                     │
                                                     ▼
                         PROCEDURE CHECKER (fixed rules, no guessing)
                          │           │             │              │
                          ▼           ▼             ▼              ▼
                   voice + screen   log file    report.txt    Earth link (live or later)
```

The AI only **sees**. The **decisions** (is this step correct? was one
skipped?) are made by a rule checker that always gives the same answer
for the same situation — nothing is "hallucinated" in the safety part.

---

## Two ways to talk to Earth

| | **LIVE** | **OFFLINE, SEND LATER** |
|---|---|---|
| When | there is a link during the experiment | no link during the experiment |
| What happens | every log line and photo goes to Mission Control as it happens | everything is saved on the laptop; press **Send to Earth** when a link is up |
| If the link drops | nothing lost: the station keeps it and resends | nothing lost: send again any time |
| Mission Control shows | live checklist, alerts, photos, delay | the same, marked "SENT LATER" |

Either way Mission Control checks **every line** of the log and **every
photo** as it arrives, and shows **LOG VERIFIED** — or **TAMPERED** if
anything was changed.

![Mission Control on Earth](docs/img/mission_control.jpg)

---

## Try it

### Option 1 — the Windows app (no Python needed)
1. Download `BAS-Copilot-windows.zip` (from the team / the Releases page) and unzip it.
2. Double-click **BAS-Copilot.exe**.
3. At the top right choose what this PC is: **SPACE STATION** or **EARTH**.

### Option 2 — from the source code
```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[vision,audio,dev]"
.venv\Scripts\python.exe scripts\run_gui.py
```
(one extra OpenCV step is in [docs/DEVELOPER.md](docs/DEVELOPER.md#setup))

Mission Control on a second laptop needs only Python + Pillow:
see **[EARTH_SETUP.md](EARTH_SETUP.md)**.

---

## Using it

**1. Space station laptop** — pick the experiment, the props and the camera
(webcam, phone camera by IP, or a video file). To report to Earth, tick
**Send to Earth** and type the Earth laptop's IP. Press **Start experiment**.

![Start screen, space station](docs/img/start_space_station.jpg)

**2. During the experiment** — just do the work. The screen shows the
checklist, the step to do now, and what the camera sees you doing.
Hands busy? Use your voice: *"Hey BAS, next step / repeat / pause / resume"*.
Keys: **Space** pause, **N** next step, **R** repeat, **H** help.

**3. Earth laptop** — choose **EARTH**, read out the IP it shows to the
station, press **Start receiving**.

![Start screen, Earth](docs/img/start_earth.jpg)

**4. After** — each session leaves a **report** (steps, times, alerts) and
a verified log. Both start screens list past **Sessions**; the station's
list has **Send to Earth** for sessions recorded offline.

---

## Measured results

| What | Result |
|---|---|
| Object detection on recordings it never saw | **0.89** mAP50 (standard accuracy score) |
| Steps recognised on 3 hand-checked test videos | **17 of 18** |
| Procedure checker, 16 scripted scenarios | **16/16** correct, **0** false alarms |
| Speed on a laptop CPU | 15–29 frames per second |
| Data sent to Earth for a 33-second experiment | **~0.5 MB** (log 30 KB + 12 photos) instead of 3.6 MB of video |
| Log after a link drop and ground restart | **byte-identical** on Earth |
| Automated tests | 600 passing |

Every number, with how it was measured: [ppt_context.md](ppt_context.md).

## What it does not do (yet)

- It is not a full-body 3D pose system (the PS lists that as optional); it tracks hands and objects relative to the rig.
- Gloved hands are detected, but finger tracking works on bare hands only.
- Voice commands are not yet tested in a noisy room.

---

## More

| For | Read |
|---|---|
| The presentation (all numbers, limits, talking points) | [ppt_context.md](ppt_context.md) |
| The demo video script | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Setting up the Earth laptop | [EARTH_SETUP.md](EARTH_SETUP.md) |
| Developers (code map, setup, tests, data pipeline) | [docs/DEVELOPER.md](docs/DEVELOPER.md) |
