# PostureGuard — Smart Vision-Based Posture & Attention Monitoring System

A webcam-based posture and attention monitor with a personalised "Cognitive
Endurance Engine", ESP32 hardware alerts, two new sensors (MAX30102 HRV
proxy + LDR ambient light), a Telegram IoT alert channel, gamified streaks,
and a live analytics dashboard. Everything runs from one command:

```
uvicorn src.api.routes:app --reload
```

## What's in this build

- **Reliability fix** — the camera worker used to die permanently on a
  single dropped frame. It now retries, backs off, and fully reconnects the
  camera before giving up (`CAMERA_FAILURE_BACKOFF_THRESHOLD` /
  `CAMERA_MAX_RECONNECT_ATTEMPTS` in `.env`).
- **Per-session calibration** — the first `CALIBRATION_DURATION_SECONDS` of
  each session (default 15s) captures *your* neutral posture as a personal
  baseline, instead of one fixed threshold for every body and camera setup.
- **Continuous, explainable posture scoring** — replaces the old step
  function (which could only ever land on 5 discrete scores) with a
  continuous, shoulder-width-normalised formula, plus a live breakdown of
  exactly which factor is driving today's score.
- **Predictive focus-decay nudges** — a "Cognitive Endurance Engine" trend
  detector that flags a declining focus trend *before* it crosses the hard
  distraction threshold, grounded in vigilance-decrement research.
- **Two new sensors** — MAX30102 (HRV-proxy heart rate) and an LDR (ambient
  light), wired to the same ESP32, feeding the existing `SensorReading`
  table.
- **IoT alert channel** — a Telegram bot push for severe alerts, since the
  laptop is already online to serve the dashboard.
- **Gamification** — streaks and badges derived read-only from session
  history (no new table, no schema migration).
- **Dashboard upgrades** — donut charts, a radar session snapshot, a
  sensor-correlation chart, a calibration banner, and a score-breakdown
  panel.

## Step-by-step setup

**Step 1 — Extract the project** into any folder on your PC.

**Step 2 — Install Python 3.11** if you haven't already (MediaPipe 0.10.9
has no wheel for Python 3.12+ — this is exactly why the pinned version
matters).

**Step 3 — Open a terminal** in the project folder (the one containing
`src/`, `requirements.txt`, etc.) and create a virtual environment:

```
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

**Step 4 — Create your `.env` file:**

```
copy .env.example .env         # Windows
# cp .env.example .env         # Mac/Linux
```

Open `.env` and check `CAMERA_INDEX` (0 for the built-in webcam), and
`SERIAL_PORT` if you're using the ESP32. Everything else has a sensible
default — see the comments in `.env.example`.

**Step 5 — (Optional) Wire the hardware.** See "Hardware wiring" below.
If you skip this entirely, the app still runs fully — camera, dashboard,
calibration, and the decay engine all work with no ESP32 connected at all.

**Step 6 — (Optional) Upload the ESP32 sketch.**
Open `hardware/esp32_buzzer/esp32_buzzer.ino` in Arduino IDE.
Install the library: Tools → Manage Libraries → search **"MAX30105"** by
SparkFun Electronics → Install (this library also drives the MAX30102).
Select **Tools → Board → ESP32 Dev Module** and the correct **Port**, then
Upload. Close the Arduino Serial Monitor afterwards — Python needs the port.

**Step 7 — (Optional) Set up the Telegram bot.** See "Telegram IoT setup"
below. Leave `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` blank in `.env` to
skip this — everything else works identically without it.

**Step 8 — Run the server:**

```
uvicorn src.api.routes:app --reload
```

**Step 9 — Open `http://127.0.0.1:8000`** in your browser.

**Step 10 — Sit naturally for the first ~15 seconds.** You'll see a
"Calibrating…" banner on the camera feed and in the posture card — this is
building your personal baseline. Once it disappears, the score ring,
breakdown, and timers go live.

## Hardware wiring

```
ESP32 DevKit V1
      |
   GPIO 2  ----[+] ACTIVE BUZZER [-]---- GND
      |
   GPIO 21 (SDA) ---- MAX30102 SDA
   GPIO 22 (SCL) ---- MAX30102 SCL
   3.3V          ---- MAX30102 VIN
   GND           ---- MAX30102 GND
      |
   GPIO 34 (ADC) ---- LDR + 10kΩ resistor voltage divider ---- GND
                       (LDR's other leg -> 3.3V)
```

If your LDR readings come out backwards (a darker room reads a *higher*
number), swap which leg of the divider feeds GPIO34 vs. GND — that's just
the divider's polarity, not a bug.

| ESP32 Pin | Connection | Description |
|---|---|---|
| GPIO 2 | Buzzer positive | Alert output (also the onboard LED) |
| GPIO 21 | MAX30102 SDA | I2C data |
| GPIO 22 | MAX30102 SCL | I2C clock |
| GPIO 34 | LDR divider midpoint | Ambient light (ADC, input-only pin) |
| GND | Buzzer negative, MAX30102 GND, LDR divider | Common ground |
| USB (micro-B) | Laptop | Power + serial |

## Serial protocol

```
ESP32 -> Python   HR:<bpm>:<ibi_ms>:<quality0-100>      e.g. HR:74:812:85
ESP32 -> Python   LUX:<raw_adc_0_4095>                   e.g. LUX:2130
Python -> ESP32   PAY ATTENTION / FOCUS ON STUDY /
                  CRITICAL DISTRACTION / FIX YOUR POSTURE
```

The ESP32 only sends an `HR:` line while it currently has a plausible,
recent beat detection — if you haven't rested a finger on the MAX30102 (or
just took it off), no `HR:` line is sent at all, rather than sending a
stale or made-up number. The dashboard's HRV panel reflects this honestly
with a quality dot (green = reliable, amber = low quality, grey = no
signal) instead of always showing a confident-looking number.

## Telegram IoT setup (optional)

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts →
   copy the token it gives you into `TELEGRAM_BOT_TOKEN` in `.env`.
2. Send your new bot any message (e.g. "hi") so it has a chat to reply to.
3. Visit `https://api.telegram.org/bot<your-token>/getUpdates` in a browser
   and find `"chat":{"id": ...}` in the response — that number goes in
   `TELEGRAM_CHAT_ID`.
4. Restart the app. `CRITICAL DISTRACTION` and `FIX YOUR POSTURE` alerts
   will now also push to that chat. Check `/api/status` →
   `telegram_enabled` to confirm it's wired up.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Dashboard page |
| GET | `/video_feed` | MJPEG live camera stream |
| GET | `/api/status` | Camera / ESP32 / Telegram / session status |
| GET | `/api/live/metrics` | Latest frame metrics as JSON |
| GET | `/api/live/history` | Recent telemetry samples for the active session |
| GET | `/api/sensors/latest` | Latest HRV-proxy + light readings |
| GET | `/api/sensors/history` | Recent sensor history for correlation charts |
| GET | `/api/gamification/summary` | Current streak, best streak, badges |
| POST | `/api/sessions/start` | Manually start a session |
| POST | `/api/sessions/{id}/stop` | End and finalize a session |
| GET | `/api/sessions` | List sessions (paginated) |
| GET | `/api/sessions/{id}` | Get a specific session |
| GET | `/api/sessions/{id}/samples` | Telemetry samples for a session |
| GET | `/api/sessions/{id}/sensors` | Sensor readings for a session |
| GET | `/api/sessions/{id}/summary` | Computed summary statistics |
| GET | `/api/export/{id}.csv` | Download session data as CSV |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Camera worked, then froze | Original bug — a single dropped frame killed the pipeline | Fixed in this build; if it still happens, lower `CAMERA_WIDTH`/`CAMERA_HEIGHT` further or check Device Manager for a flaky driver |
| `mediapipe has no attribute 'solutions'` | MediaPipe upgraded past 0.10.9, which removed the legacy API this project uses | `pip install mediapipe==0.10.9` |
| Very slow frame rate | CPU overloaded | Close Zoom/Teams/other camera or CPU-heavy apps; lower `VISION_MODEL_COMPLEXITY` (already defaults to 0, the lightest) |
| "NO CAM" status | Camera in use by another app, or wrong index | Close other camera apps; try `CAMERA_INDEX=1` in `.env` |
| ESP32 not detected | Wrong COM port | Check Device Manager, update `SERIAL_PORT` in `.env` |
| No buzzer sound | Arduino Serial Monitor left open | Close Arduino IDE / Serial Monitor before starting Python |
| No HRV reading ever | Finger not on sensor, or MAX30102 wiring/library issue | Rest a finger fully on the sensor; check `sensorReady` printed at boot in Serial Monitor |
| HRV reading flickers a lot | Motion artifact — completely expected for a PPG sensor while typing | This is why every reading carries a quality flag; hold still briefly for a clean reading |
| LDR reads backwards | Voltage-divider polarity | Swap which leg feeds GPIO34 vs GND |
| Telegram never arrives | Token/chat id wrong, or blank | Check `/api/status` → `telegram_enabled`; re-verify token and chat id |

## Project structure

```
src/
├── main.py                      (legacy standalone OpenCV-window runner — optional, not used by uvicorn)
├── pose_geometry.py              NEW  shared normalized-ratio geometry
├── calibration.py                NEW  per-session personal baseline
├── decay_predictor.py            NEW  predictive focus-decay trend nudges
├── sensor_manager.py             NEW  HR/LUX parsing + rolling history
├── posture_detector.py           REWRITTEN  continuous, calibratable score
├── attention_tracker.py          REWRITTEN  shoulder-relative, calibratable
├── serial_manager.py             REWRITTEN  + bidirectional sensor reader thread
├── timer_manager.py / score_manager.py / threshold_manager.py   (unchanged)
├── api/routes.py                 REWRITTEN  reliability fix + new endpoints
├── services/
│   ├── vision_service.py         REWRITTEN  calibration + engine + sensor fusion
│   ├── session_service.py        + sensor reading persistence
│   ├── alert_service.py          + notifier hook, emit()
│   ├── telegram_notifier.py      NEW
│   └── gamification_service.py   NEW
├── db/  (models.py already had a SensorReading table — reused, not migrated)
└── dashboard/  (templates + static — new panels, charts, calibration banner)
hardware/esp32_buzzer/esp32_buzzer.ino   NEW  (was referenced before but missing from the repo)
.env.example                              NEW  (was referenced before but missing from the repo)
```

## Notes on the sensors

The MAX30102 is a PPG (photoplethysmography) sensor: it only produces a
clean signal when a finger sits still against it. Ordinary studying —
typing, writing, adjusting glasses — is a motion artifact from the
sensor's point of view. This build treats that honestly: every reading
carries a 0–100 quality score, values outside a plausible 40–180bpm range
are flagged rather than trusted, and the dashboard shows "no reliable
signal" instead of a smoothed-over fake number whenever the signal isn't
good. That's also the honest answer if a judge asks why the HRV number
isn't rock-steady throughout a session — a wearable fitness tracker handles
exactly the same problem the same way.