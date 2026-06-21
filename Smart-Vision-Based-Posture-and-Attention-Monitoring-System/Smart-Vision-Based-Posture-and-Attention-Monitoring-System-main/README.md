# PostureGuard — Smart Vision-Based Posture & Attention Monitoring System

Real-time posture and attention monitoring using your PC webcam, MediaPipe,
FastAPI, SQLite, and an optional ESP32 buzzer — all accessible from a dark-tech
web dashboard at `http://localhost:8000`.

---

## Quick Start (Windows)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # edit SERIAL_PORT / CAMERA_INDEX if needed
uvicorn src.api.routes:app --reload
```

Then open **http://localhost:8000** in your browser.

---

## Quick Start (Mac / Linux)

```
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit SERIAL_PORT / CAMERA_INDEX if needed
uvicorn src.api.routes:app --reload
```

---

## Modes

| Mode | Command | What it does |
|---|---|---|
| **Dashboard** (recommended) | `uvicorn src.api.routes:app --reload` | Full web dashboard + camera + DB |
| **Local OpenCV window** | `python src/main.py --demo-window` | Camera with MediaPipe overlay, no browser needed |
| **Headless logger** | `python src/main.py` | Saves to DB only, no window, no browser |

> **Important:** do not run two modes at the same time — they would conflict
> over the camera.

---

## Project Structure

```
POSTURE_MONITOR_PROJECT/
├── src/
│   ├── main.py                   # Standalone OpenCV runner
│   ├── posture_detector.py       # MediaPipe → posture score/state
│   ├── attention_tracker.py      # Nose position → focused/distracted
│   ├── threshold_manager.py      # Threshold checks → alert string
│   ├── timer_manager.py          # dt-based time accumulators
│   ├── score_manager.py          # Focus % calculation
│   ├── serial_manager.py         # ESP32 serial communication
│   ├── logger.py                 # CSV session log (legacy)
│   ├── api/
│   │   └── routes.py             # FastAPI app + background vision worker
│   ├── db/
│   │   ├── database.py           # SQLAlchemy engine + init_db()
│   │   ├── models.py             # Session, TelemetrySample, SensorReading
│   │   └── crud.py               # CRUD helpers
│   ├── services/
│   │   ├── vision_service.py     # VisionService (OpenCV + MediaPipe)
│   │   ├── session_service.py    # Session start/stop + telemetry persistence
│   │   └── alert_service.py      # Alert evaluation + cooldown
│   ├── dashboard/
│   │   ├── templates/dashboard.html  # Dark-tech dashboard HTML
│   │   └── static/
│   │       ├── styles.css        # CSS variables, layout, components
│   │       └── dashboard.js      # Live polling + Chart.js + session history
│   └── utils/
│       └── config.py             # Environment variable configuration
├── hardware/
│   └── esp32_buzzer/
│       └── esp32_buzzer.ino      # Arduino sketch for the ESP32 buzzer
├── data/                         # SQLite DB and CSV log auto-created here
├── .env.example                  # Config template — copy to .env
├── requirements.txt
└── README.md
```

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `CAMERA_INDEX` | `0` | Webcam index. Try `1` or `2` if 0 doesn't work. |
| `SERIAL_PORT` | `COM5` | ESP32 port. Linux: `/dev/ttyUSB0` |
| `SERIAL_BAUDRATE` | `9600` | Must match the Arduino sketch. |
| `DATABASE_URL` | `sqlite:///data/posture_monitor.db` | SQLite path. |
| `DISTRACTION_THRESHOLD_SECONDS` | `5` | Seconds before distraction alert. |
| `BAD_POSTURE_THRESHOLD_SECONDS` | `15` | Seconds before posture alert. |
| `ALERT_COOLDOWN_SECONDS` | `5` | Minimum gap between buzzer alerts. |

---

## ESP32 Setup

1. Open `hardware/esp32_buzzer/esp32_buzzer.ino` in Arduino IDE.
2. Install ESP32 board support (Boards Manager → search "esp32").
3. Select board: **ESP32 Dev Module**, port: **COM5** (or your port).
4. Upload the sketch.
5. Connect the active buzzer **positive pin → GPIO 2**, **negative → GND**.
6. **Close Arduino Serial Monitor** before running Python.
7. Set `SERIAL_PORT=COM5` (or your port) in `.env`.

> The system runs perfectly without an ESP32 — alerts still appear on-screen.

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard page |
| `GET /video_feed` | MJPEG camera stream |
| `GET /api/status` | Camera / ESP32 / session status |
| `GET /api/live/metrics` | Latest frame metrics (JSON) |
| `GET /api/live/history?limit=80` | Recent samples for active session |
| `GET /api/sessions` | List past sessions |
| `GET /api/sessions/{id}/samples` | Telemetry samples for a session |
| `GET /api/sessions/{id}/summary` | Session summary |
| `GET /api/export/{id}.csv` | Download session as CSV |

---

## Python Version

Requires **Python 3.11**. MediaPipe has compatibility issues with Python 3.12+.
