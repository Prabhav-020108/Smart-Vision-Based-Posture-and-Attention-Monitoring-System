"""Serial communication manager for ESP32 buzzer integration.

Connects to the configured COM port at import time. If the port does not exist
(ESP32 unplugged) the module continues to operate in degraded mode: all serial
sends are silently skipped so the rest of the application keeps running.
"""

from __future__ import annotations

import time

import serial

from src.utils.config import SERIAL_BAUDRATE, SERIAL_PORT

# ── Connection attempt ────────────────────────────────────────────────────────
esp32: serial.Serial | None = None
SERIAL_CONNECTED: bool = False

try:
    esp32 = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
    # Brief settle delay — reduced from 2 s to 0.5 s to avoid blocking startup
    time.sleep(0.5)
    SERIAL_CONNECTED = True
    print(f"[serial] ESP32 connected on {SERIAL_PORT} @ {SERIAL_BAUDRATE} baud")
except Exception as exc:
    esp32 = None
    SERIAL_CONNECTED = False
    print(f"[serial] ESP32 not found ({exc}). Running without buzzer.")

# ── Duplicate-message guard ───────────────────────────────────────────────────
_last_message: str = ""


def send_alert(message: str) -> bool:
    """Send a warning string to the ESP32. Returns True if sent, False otherwise."""

    global _last_message

    if not SERIAL_CONNECTED or esp32 is None:
        return False

    if message == _last_message:
        return False  # Suppress duplicate spam

    try:
        esp32.write(f"{message}\n".encode())
        esp32.flush()
        print(f"[serial] Sent: {message}")
        _last_message = message
        return True
    except Exception as exc:
        print(f"[serial] Send failed: {exc}")
        return False
