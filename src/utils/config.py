"""Application configuration loaded from environment variables.

Each value falls back to a safe default when the environment variable is
missing or cannot be converted to the expected type.
"""

import os
from typing import Optional


def _get_int_env(name: str, default: int) -> int:
    """Return an integer environment variable or the provided default."""

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
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


SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
SERIAL_BAUDRATE = _get_int_env("SERIAL_BAUDRATE", 9600)
CAMERA_INDEX = _get_int_env("CAMERA_INDEX", 0)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/posture_monitor.db")
DISTRACTION_THRESHOLD_SECONDS = _get_int_env("DISTRACTION_THRESHOLD_SECONDS", 5)
BAD_POSTURE_THRESHOLD_SECONDS = _get_int_env("BAD_POSTURE_THRESHOLD_SECONDS", 15)
SNAPSHOT_INTERVAL_SECONDS = _get_optional_int_env("SNAPSHOT_INTERVAL_SECONDS", 10)
