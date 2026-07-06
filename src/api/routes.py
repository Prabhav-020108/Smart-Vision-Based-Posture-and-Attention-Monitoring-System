"""FastAPI routes for PostureGuard – Posture & Attention Monitoring Dashboard.

Architecture:
  - A single background daemon thread (_vision_worker) owns the camera.
  - It writes the latest JPEG frame and metrics dict into module-level globals.
  - /video_feed reads those globals and streams MJPEG to the browser.
  - /api/live/metrics returns the latest metrics as JSON (no frame data).
  - A second daemon thread (serial reader, started in on_startup) reads
    sensor lines from the ESP32 independently of the camera loop.
  - All other endpoints are CRUD against the SQLite/SQLAlchemy database.

Reliability: the original worker loop broke out permanently on the first
frame-read failure. It now tolerates a run of consecutive failures with a
brief backoff, and attempts a full camera reconnect before giving up — see
CAMERA_FAILURE_BACKOFF_THRESHOLD / CAMERA_MAX_RECONNECT_ATTEMPTS in
src/utils/config.py.

This means you still need only one process:
    uvicorn src.api.routes:app --reload
"""

from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Annotated, Any, Iterator

import cv2
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select

from src.db import crud, models
from src.db.database import SessionLocal, init_db
from src.services.session_service import SessionService
from src.utils.config import (
    CAMERA_FAILURE_BACKOFF_THRESHOLD,
    CAMERA_INDEX,
    CAMERA_MAX_RECONNECT_ATTEMPTS,
    SENSOR_SAVE_INTERVAL_SECONDS,
)

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = BASE_DIR / "dashboard"
STATIC_DIR = DASHBOARD_DIR / "static"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"

# ─── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="PostureGuard API", version="3.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ─── Global worker state ──────────────────────────────────────────────────────
_latest_frame: bytes | None = None          # latest JPEG bytes (from camera)
_latest_metrics: dict[str, Any] | None = None  # latest metrics without frame
_active_session_id: str | None = None
_worker_running: bool = False
_camera_ok: bool = False
_esp32_connected: bool = False
_session_start_epoch: float | None = None   # time.time() when session started

_SAVE_INTERVAL_S = 2.0   # telemetry DB write interval


def _get_esp32_status() -> bool:
    """Read serial connection status without crashing if import fails."""
    try:
        from src.serial_manager import SERIAL_CONNECTED  # noqa: PLC0415
        return bool(SERIAL_CONNECTED)
    except Exception:
        return False


def _get_telegram_status() -> bool:
    """Read Telegram configuration status without crashing if import fails."""
    try:
        from src.services.telegram_notifier import TELEGRAM_ENABLED  # noqa: PLC0415
        return bool(TELEGRAM_ENABLED)
    except Exception:
        return False


def _persist_sensor_readings(session_svc: SessionService, session_id: str) -> None:
    """Write the latest HR/LUX readings (if any) to the SensorReading table."""

    from src import sensor_manager  # noqa: PLC0415

    latest = sensor_manager.get_latest()

    hr = latest.get("hr")
    if hr:
        try:
            session_svc.save_sensor_reading(
                session_id,
                sensor_type="hrv_proxy",
                value=hr["bpm"],
                unit="bpm",
                metadata={
                    "ibi_ms": hr["ibi_ms"],
                    "quality": hr["quality"],
                    "plausible": hr["plausible"],
                    "reliable": latest.get("hr_reliable", False),
                },
            )
        except Exception as exc:
            print(f"[worker] Sensor save error (hr): {exc}")

    lux = latest.get("lux")
    if lux:
        try:
            session_svc.save_sensor_reading(
                session_id,
                sensor_type="ambient_light",
                value=lux["brightness_score"],
                unit="pct",
                metadata={"raw_adc": lux["raw"]},
            )
        except Exception as exc:
            print(f"[worker] Sensor save error (lux): {exc}")


# ─── Background vision worker ─────────────────────────────────────────────────

def _vision_worker() -> None:
    """Daemon thread: run MediaPipe vision loop, save telemetry, fire alerts."""
    global _latest_frame, _latest_metrics, _active_session_id
    global _worker_running, _camera_ok, _session_start_epoch

    # Lazy-import heavy libraries so startup isn't blocked
    from src.services.vision_service import VisionService   # noqa: PLC0415
    from src.services.session_service import SessionService  # noqa: PLC0415
    from src.services.alert_service import AlertService       # noqa: PLC0415
    from src.services.telegram_notifier import send_telegram_message_async  # noqa: PLC0415
    from src import sensor_manager                             # noqa: PLC0415

    vision: VisionService | None = None
    session_svc = SessionService()
    alert_svc = AlertService(notifier=send_telegram_message_async)

    consecutive_failures = 0
    reconnect_attempts = 0

    try:
        vision = VisionService(camera_index=CAMERA_INDEX, alert_service=alert_svc)

        # ── Sanity-check: can we actually read a frame? ───────────────────────
        probe = vision.process_next_frame(draw_overlay=False)
        if probe is None:
            print(f"[worker] Camera index {CAMERA_INDEX} unavailable. Stopping.")
            _camera_ok = False
            return

        _camera_ok = True
        sensor_manager.reset()
        session = session_svc.start_session()
        _active_session_id = session.session_id
        _session_start_epoch = time.time()
        print(f"[worker] Session started: {_active_session_id}")

        last_saved_at = 0.0
        last_sensor_saved_at = 0.0

        while _worker_running:
            raw = vision.process_next_frame(draw_overlay=True)

            # ── Frame read failed: back off, and reconnect after a run of
            #    consecutive failures instead of giving up on the first one.
            if raw is None:
                consecutive_failures += 1

                if consecutive_failures >= CAMERA_FAILURE_BACKOFF_THRESHOLD:
                    reconnect_attempts += 1
                    print(
                        f"[worker] {consecutive_failures} consecutive frame "
                        f"read failures — reconnecting camera "
                        f"(attempt {reconnect_attempts}/{CAMERA_MAX_RECONNECT_ATTEMPTS})."
                    )
                    if reconnect_attempts > CAMERA_MAX_RECONNECT_ATTEMPTS:
                        print("[worker] Camera reconnect attempts exhausted. Stopping.")
                        break
                    vision.reopen_capture()
                    consecutive_failures = 0
                    time.sleep(0.5)  # give the driver a moment after reopening
                else:
                    time.sleep(0.05)  # brief backoff before the next read attempt
                continue

            consecutive_failures = 0
            reconnect_attempts = 0

            # ── Encode frame → JPEG ─────────────────────────────────────────
            frame_arr = raw.pop("frame", None)
            if frame_arr is not None:
                ok, buf = cv2.imencode(
                    ".jpg", frame_arr, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if ok:
                    _latest_frame = buf.tobytes()

            # ── Build metrics snapshot ──────────────────────────────────────
            raw["timestamp"] = datetime.utcnow().isoformat() + "Z"
            raw["session_id"] = _active_session_id
            _latest_metrics = dict(raw)

            now = time.monotonic()

            # ── Periodic telemetry persistence ──────────────────────────────
            if now - last_saved_at >= _SAVE_INTERVAL_S and _active_session_id:
                try:
                    session_svc.save_telemetry_sample(_active_session_id, dict(raw))
                except Exception as exc:
                    print(f"[worker] Telemetry save error: {exc}")
                last_saved_at = now

            # ── Periodic sensor persistence ─────────────────────────────────
            if now - last_sensor_saved_at >= SENSOR_SAVE_INTERVAL_SECONDS and _active_session_id:
                _persist_sensor_readings(session_svc, _active_session_id)
                last_sensor_saved_at = now

            # ── Alert (cooldown-gated ESP32 buzz + Telegram push for severe ones) ─
            alert = raw.get("alert_message", "")
            if alert:
                alert_svc.emit(alert)

    except Exception as exc:
        print(f"[worker] Fatal error: {exc}")
        _camera_ok = False

    finally:
        if vision:
            vision.release()
        _worker_running = False
        print("[worker] Vision worker stopped.")

        # ── Finalize session ─────────────────────────────────────────────────
        if _active_session_id and _latest_metrics:
            try:
                session_svc.end_session(
                    _active_session_id,
                    final_summary={
                        "focused_time": _latest_metrics.get("focused_time", 0.0),
                        "distracted_time": _latest_metrics.get("distracted_time", 0.0),
                        "focus_percentage": _latest_metrics.get("focus_percentage", 0.0),
                    },
                )
                print(f"[worker] Session ended: {_active_session_id}")
            except Exception as exc:
                print(f"[worker] Session end error: {exc}")


# ─── FastAPI lifecycle ────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    global _worker_running, _esp32_connected
    init_db()
    _esp32_connected = _get_esp32_status()

    from src.serial_manager import start_serial_reader  # noqa: PLC0415
    start_serial_reader()

    _worker_running = True
    t = threading.Thread(
        target=_vision_worker, daemon=True, name="postureguard-vision"
    )
    t.start()
    print("[api] PostureGuard started. Camera worker launched.")


@app.on_event("shutdown")
def on_shutdown() -> None:
    global _worker_running
    _worker_running = False
    print("[api] Shutdown requested.")


# ─── MJPEG video stream ───────────────────────────────────────────────────────

def _frame_generator() -> Iterator[bytes]:
    """Yield MJPEG chunks from the latest camera frame."""
    empty_streak = 0
    while True:
        frame = _latest_frame
        if frame is not None:
            empty_streak = 0
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        else:
            empty_streak += 1
            if empty_streak > 300:        # ~10 s with 30 ms sleep → give up
                break
        time.sleep(0.033)                 # ~30 fps cap


@app.get("/video_feed", include_in_schema=False)
def video_feed() -> StreamingResponse:
    """Stream annotated camera frames as MJPEG."""
    return StreamingResponse(
        _frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ─── Dashboard page ───────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(request, "dashboard.html")


# ─── System status ────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status() -> dict[str, Any]:
    """Return system-level status: camera, ESP32, Telegram, active session."""
    session_elapsed: float | None = None
    if _session_start_epoch is not None:
        session_elapsed = time.time() - _session_start_epoch

    return {
        "camera_ok": _camera_ok,
        "worker_running": _worker_running,
        "esp32_connected": _esp32_connected or _get_esp32_status(),
        "telegram_enabled": _get_telegram_status(),
        "active_session_id": _active_session_id,
        "session_elapsed_seconds": session_elapsed,
    }


# ─── Live metrics ─────────────────────────────────────────────────────────────

@app.get("/api/live/metrics")
def get_live_metrics() -> dict[str, Any]:
    """Return the most-recent frame metrics from the vision worker."""
    if _latest_metrics is None:
        return {
            "available": False,
            "camera_ok": _camera_ok,
            "worker_running": _worker_running,
        }
    return jsonable_encoder({"available": True, **_latest_metrics})


@app.get("/api/live/history")
def get_live_history(
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
) -> dict[str, Any]:
    """Return the last N telemetry samples from the active session."""
    if not _active_session_id:
        return {"samples": [], "session_id": None}
    svc = SessionService()
    samples = svc.get_recent_samples(_active_session_id, limit=limit)
    return jsonable_encoder({"samples": samples, "session_id": _active_session_id})


# ─── Sensors ─────────────────────────────────────────────────────────────────

@app.get("/api/sensors/latest")
def get_sensors_latest() -> dict[str, Any]:
    """Return the latest HRV-proxy and ambient-light readings."""
    from src import sensor_manager  # noqa: PLC0415
    return jsonable_encoder(sensor_manager.get_latest())


@app.get("/api/sensors/history")
def get_sensors_history(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Return recent HRV-proxy and ambient-light history for correlation charts."""
    from src import sensor_manager  # noqa: PLC0415
    return jsonable_encoder(sensor_manager.get_history(limit=limit))


# ─── Gamification ────────────────────────────────────────────────────────────

@app.get("/api/gamification/summary")
def get_gamification_summary() -> dict[str, Any]:
    """Return the current streak, best streak, and badge progress."""
    from src.services.gamification_service import get_streak_summary  # noqa: PLC0415
    return jsonable_encoder(get_streak_summary())


# ─── Sessions ────────────────────────────────────────────────────────────────

@app.post("/api/sessions/start")
def start_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    session = SessionService().start_session(
        user_id=payload.get("user_id"),
        device_id=payload.get("device_id"),
        session_id=payload.get("session_id"),
    )
    return jsonable_encoder({"session": SessionService._session_to_dict(session)})


@app.post("/api/sessions/{session_id}/stop")
def stop_session(session_id: str) -> dict[str, Any]:
    svc = SessionService()
    try:
        session = svc.end_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return jsonable_encoder({"session": svc._session_to_dict(session)})


@app.get("/api/sessions")
def list_sessions(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    sessions = SessionService().get_session_history(limit=limit, offset=offset)
    return jsonable_encoder({"sessions": sessions})


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        session = crud.get_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        return jsonable_encoder({"session": SessionService._session_to_dict(session)})


@app.get("/api/sessions/{session_id}/samples")
def get_session_samples(
    session_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 120,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    with SessionLocal() as db:
        if crud.get_session(db, session_id) is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        samples = crud.list_telemetry_samples(db, session_id, limit=limit, offset=offset)
        return jsonable_encoder(
            {"samples": [SessionService._sample_to_dict(s) for s in samples]}
        )


@app.get("/api/sessions/{session_id}/sensors")
def get_session_sensors(
    session_id: str,
    sensor_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    with SessionLocal() as db:
        if crud.get_session(db, session_id) is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    readings = SessionService().get_recent_sensor_readings(
        session_id, sensor_type=sensor_type, limit=limit
    )
    return jsonable_encoder({"readings": readings})


@app.get("/api/sessions/{session_id}/summary")
def get_session_summary(session_id: str) -> dict[str, Any]:
    try:
        summary = SessionService().calculate_session_summary(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return jsonable_encoder({"summary": summary.to_dict()})


# ─── Export ──────────────────────────────────────────────────────────────────

@app.get("/api/export/{session_id}.csv")
def export_session_csv(session_id: str) -> StreamingResponse:
    with SessionLocal() as db:
        if crud.get_session(db, session_id) is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        samples = crud.list_telemetry_samples(db, session_id, limit=50000)

    fieldnames = [
        "id", "session_id", "timestamp", "posture_score", "posture_state",
        "attention_state", "focused_time", "distracted_time",
        "continuous_distraction_time", "bad_posture_time",
        "focus_percentage", "alert_message", "frame_path",
    ]
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for s in samples:
        row = jsonable_encoder(SessionService._sample_to_dict(s))
        writer.writerow(row)

    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{session_id}.csv"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)
