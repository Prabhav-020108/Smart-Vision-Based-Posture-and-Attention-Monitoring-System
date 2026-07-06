"""Application configuration loaded from environment variables.

Each value falls back to a safe default when the environment variable is
missing or cannot be converted to the expected type.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load variables from .env file into the environment
load_dotenv()


def _get_int_env(name: str, default: int) -> int:
    """Return an integer environment variable or the provided default."""

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    """Return a float environment variable or the provided default."""

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _get_optional_int_env(name: str, default: Optional[int] = None) -> Optional[int]:
    """Return an optional integer environment variable or the default."""

    value = os.getenv(name)

    if value is None or value == "":
        return default

    try:
        return int(value)
    except ValueError:
        return default


# ── Camera / vision (existing) ─────────────────────────────────────────────
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
SERIAL_BAUDRATE = _get_int_env("SERIAL_BAUDRATE", 9600)
CAMERA_INDEX = _get_int_env("CAMERA_INDEX", 0)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/posture_monitor.db")
DISTRACTION_THRESHOLD_SECONDS = _get_int_env("DISTRACTION_THRESHOLD_SECONDS", 5)
BAD_POSTURE_THRESHOLD_SECONDS = _get_int_env("BAD_POSTURE_THRESHOLD_SECONDS", 15)
SNAPSHOT_INTERVAL_SECONDS = _get_optional_int_env("SNAPSHOT_INTERVAL_SECONDS", 10)
ALERT_COOLDOWN_SECONDS = _get_float_env("ALERT_COOLDOWN_SECONDS", 5.0)

# ── Camera reliability (new — fixes the freeze-on-dropped-frame bug) ───────
# A lower resolution and the lightest MediaPipe model are meaningfully easier
# on a weaker CPU with no real accuracy cost for shoulder/nose landmarks.
CAMERA_WIDTH = _get_int_env("CAMERA_WIDTH", 640)
CAMERA_HEIGHT = _get_int_env("CAMERA_HEIGHT", 480)
VISION_MODEL_COMPLEXITY = _get_int_env("VISION_MODEL_COMPLEXITY", 0)  # 0=lite,1=full,2=heavy
# Consecutive dropped frames tolerated before attempting a full camera
# reconnect (rather than the original behaviour of giving up on frame one).
CAMERA_FAILURE_BACKOFF_THRESHOLD = _get_int_env("CAMERA_FAILURE_BACKOFF_THRESHOLD", 15)
CAMERA_MAX_RECONNECT_ATTEMPTS = _get_int_env("CAMERA_MAX_RECONNECT_ATTEMPTS", 5)

# ── Calibration (new — Cognitive Endurance Engine) ─────────────────────────
CALIBRATION_DURATION_SECONDS = _get_float_env("CALIBRATION_DURATION_SECONDS", 15.0)

# ── Predictive focus-decay nudges (new — Cognitive Endurance Engine) ──────
DECAY_TREND_WINDOW_SECONDS = _get_float_env("DECAY_TREND_WINDOW_SECONDS", 240.0)
DECAY_ALERT_COOLDOWN_SECONDS = _get_float_env("DECAY_ALERT_COOLDOWN_SECONDS", 300.0)

# ── Sensors: MAX30102 (HRV proxy) + LDR (ambient light) (new) ─────────────
SENSOR_HR_MIN_BPM = _get_float_env("SENSOR_HR_MIN_BPM", 40.0)
SENSOR_HR_MAX_BPM = _get_float_env("SENSOR_HR_MAX_BPM", 180.0)
SENSOR_SAVE_INTERVAL_SECONDS = _get_float_env("SENSOR_SAVE_INTERVAL_SECONDS", 5.0)

# ── IoT: Telegram alert channel (new) ──────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Gamification: streaks derived from session history (new) ──────────────
GAMIFICATION_GOOD_SESSION_FOCUS_PCT = _get_float_env("GAMIFICATION_GOOD_SESSION_FOCUS_PCT", 60.0)
GAMIFICATION_GOOD_SESSION_MIN_MINUTES = _get_float_env("GAMIFICATION_GOOD_SESSION_MIN_MINUTES", 5.0)
