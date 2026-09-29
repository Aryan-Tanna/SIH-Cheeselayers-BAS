# Earth laptop setup (Mission Control) — for the teammate

You run **Earth**: Mission Control receives, live, what the space station
laptop sends — the hash-chained log line by line, one image per completed
step and per alert, and the report at the end. You need **no camera, no
model, no voice** — only Python and Pillow (checked in a clean install).

The two laptops are in different places, so they connect over **Tailscale**
(a private network between your laptops, free). Tested: the station's
offline guard lets the Earth address through and still blocks everything
else.

## One-time setup (Earth laptop)

1. **Tailscale**: install from https://tailscale.com/download, sign in with
   the **same account as the station laptop**. Click the tray icon and note
   this laptop's address: `100.x.y.z`. Send it to the station teammate.
2. **Python 3.11+** from https://www.python.org (tick "Add python to PATH").
3. **Code + Pillow** (in a terminal):
   ```
   git clone https://github.com/Aryan-Tanna/SIH-Cheeselayers-BAS.git
   cd SIH-Cheeselayers-BAS
   py -m pip install pillow
   ```
4. **Firewall**: open port 5055 once — terminal **as Administrator**:
   ```
   netsh advfirewall firewall add rule name="BAS Mission Control" dir=in action=allow protocol=TCP localport=5055
   ```

## Every test

1. Earth laptop:
   ```
   cd SIH-Cheeselayers-BAS
   git pull
   py scripts\ground_station.py
   ```
   Leave the window open. Bottom line says "Listening...".
2. Station laptop (Aryan): `ping 100.x.y.z` must answer. Then on the start
   screen: **SPACE STATION** → tick **Send to Earth** → type
   `100.x.y.z:5055` (the **number**, not the Tailscale name — a name is
   blocked by the offline guard) → **Start experiment**.
3. Within ~2 s: Mission Control shows **● LIVE**; the station's EARTH badge
   turns green.

## What to check on Mission Control

| Look at | Expected |
|---|---|
| LINK badge | ● LIVE while running; "SESSION COMPLETE" at the end |
| LOG badge | **LOG VERIFIED**, line count going up (TAMPERED = a problem) |
| Checklist (left) | steps tick in the same order as on the station |
| Events from orbit | every step, every alert, "activity: ..." lines |
| Image (right) | one per step / alert, caption **VERIFIED - sha256 attested** |
| DELAY badge | the real delay between the two places (seconds) |
| DATA badge | a few hundred KB per session, not MB (no video is sent) |

Ask the station to make mistakes (skip a step, take a returned module out
again for >3 s, do a step out of order): each one must appear in red.

**Loss of signal test:** press **Simulate loss of signal** (or close
Mission Control and start it again) while the station keeps working. When
it reconnects, nothing may be missing: the log must still say VERIFIED and
the checklist must catch up.

## After a session

Everything received is in `ground_archive/<session_id>/`:
`session.jsonl` (identical to the station's log), `snapshots/*.jpg`,
`report.txt`. **Open session report** / **Open archive folder** buttons do
the same. Send the station teammate that folder if anything looked wrong,
with the time into the session.

## If it does not connect

| Symptom | Fix |
|---|---|
| `ping 100.x.y.z` fails | Tailscale not connected on one laptop, or different accounts |
| ping works, station says "EARTH: no link, N buffered" | firewall rule missing (step 4), or Mission Control not running |
| "Port 5055 is not free" | Mission Control is already open — use that window |
| Mission Control prints "OFFLINE GUARD: blocked ..." | expected for anything except the station; it never connects out |

Nothing is lost while the link is down: the station keeps everything and
sends it when the link comes back.

## For the real demo

Tailscale needs internet at both ends. At the venue, prefer **both laptops
on one phone hotspot** (no mobile data needed): then Mission Control shows
an address like `192.168.43.x:5055` — type that on the station instead.
