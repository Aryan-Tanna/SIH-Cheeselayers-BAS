# Demo video script — BAS Co-Pilot (about 3 minutes)

Record the screen with **OBS** (free) or the Windows Game Bar (`Win + Alt + R`),
1080p. A phone on a stand films the glovebox for the "real world" shots.
Speak slowly; every line below is ≤ 2 sentences. Times are targets.

**Before recording (checklist)**
- Space station laptop: camera fixed on a stand, props in the box (container closed, both modules inside, caps on).
- Earth laptop: `py scripts\ground_station.py` open (or the app → **EARTH** → Start receiving).
- Close other apps (the co-pilot needs ~1 GB free memory).
- Test the voice once: "Hey BAS, repeat".
- Delete old test sessions you do not want on screen (`logs/`), or just start fresh.

---

## Scene 1 — The problem (0:00–0:20)
**Show:** title slide → a photo of a space station / glovebox.
**Say:** "On the Bharatiya Antariksh Station, nobody on Earth can watch an
experiment live — signals are delayed and the link is too thin for video.
We built a co-pilot that watches instead."

## Scene 2 — Start screen (0:20–0:40)
**Show:** the app's start screen. Point at **This PC is: SPACE STATION**.
Select *Dual specimen module inspection*, show the 12 steps, the camera
(**IP camera… → Test**, the preview appears), tick **Send to Earth**.
**Say:** "Everything runs on this laptop, offline. We pick the experiment,
the camera — here a phone over Wi-Fi — and the Earth station's address."

## Scene 3 — Doing it right (0:40–1:20)
**Show:** press **Start experiment**. Split screen: glovebox (phone) + co-pilot window.
Open the box, take out the red module, unscrew the cap, put it down, screw it back, return it.
**Say (while it happens):** "It tells me the next step… recognises each action…
and ticks it off. The green line shows what the camera sees me doing."
**Point at:** the checklist ticking, "Now doing: Handling the red module cap", the OFFLINE ✓ badge.

## Scene 4 — Mistakes (1:20–1:55)
**Do:** take the yellow module out and **skip** resealing it — put it straight back unsealed.
**Hear:** the voice alert. **Then:** take the red module out again (it was already done) and hold it 5 s.
**Hear:** "That step is not part of the procedure."
**Say:** "One clear voice alert per mistake — never a stream of beeps, so the
crew keeps it switched on. Skipped steps, wrong order, and steps that
shouldn't be there at all."

## Scene 5 — Earth / Mission Control (1:55–2:25)
**Show:** the Earth laptop. LIVE badge, the same checklist with the red ✗,
the alert in the event feed, a photo of the moment, **VERIFIED**.
**Say:** "On Earth, Mission Control sees the same checklist, every alert, and a
photo of each step — not a video: about half a megabyte per experiment
instead of several. Every line is checked against a hash chain; change one
character and it says TAMPERED."
**Do:** press **Simulate loss of signal**, keep working 5 s on the station, the link returns.
**Say:** "If the link drops, nothing is lost — the station keeps everything and resends."

## Scene 6 — Fully offline + send later (2:25–2:40)
**Show:** station → end session → start screen → **Sessions** tab → a session marked *not sent* → **Send to Earth**.
Mission Control shows it arriving, marked **SENT LATER**.
**Say:** "With no link at all, everything is stored on board and sent later with one click."

## Scene 7 — Change the experiment (2:40–2:55)
**Show:** **Protocol editor** (key E) → add a 30-second time limit to a step → **Save & apply**.
**Say:** "New experiment, new order, new rules — edited here, checked, and live immediately. No code."

## Scene 8 — Close (2:55–3:05)
**Show:** the report (`Open report`) and a final slide with the measured numbers
(0.89 detection accuracy on unseen recordings, 17/18 steps, 16/16 rule scenarios with 0 false alarms, 0.5 MB per session).
**Say:** "BAS Co-Pilot: it watches, guides, warns and reports — offline, on a laptop. Thank you."

---

## If something goes wrong while recording
| Problem | Do |
|---|---|
| A step is not ticked | say "Hey BAS, next step" — it is logged as confirmed by the operator (that is a feature: the astronaut is always in charge) |
| Voice not heard | check the MIC badge; use the N key instead |
| Earth not LIVE | the station keeps everything; show Scene 6 (send later) instead |
| Camera problems | start screen → **Video file…** → use a recorded clip: the whole flow works on a video |

## Shots for the slides
Already in `docs/img/`: co-pilot during an experiment, Mission Control, both start screens.
