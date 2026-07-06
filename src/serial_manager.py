"""Serial communication manager for the ESP32.

Two independent responsibilities now share one serial connection:
  - Sending short alert strings to the ESP32 (buzzer commands) — unchanged
    behaviour from the original design.
  - Reading sensor telemetry lines the ESP32 sends back (HRV-proxy readings
    from the MAX30102, ambient-light readings from the LDR) — new.

Reads and writes are handled by a single dedicated reader thread plus the
caller's own thread for writes, which is the standard safe pattern for a
shared serial port (one reader, one writer, a lock around writes only).

Connects to the configured COM port at import time. If the port does not
exist (ESP32 unplugged) the module continues to operate in degraded mode:
all sends are silently skipped and the reader thread never starts, so the
rest of the application keeps running exactly as before.
"""

from __future__ import annotations

import threading
import time

import serial

from src.utils.config import SERIAL_BAUDRATE, SERIAL_PORT

# ── Connection attempt ────────────────────────────────────────────────────────
esp32 = None  # type: serial.Serial | None
SERIAL_CONNECTED: bool = False
_write_lock = threading.Lock()

try:
    esp32 = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1, write_timeout=1)
    # Brief settle delay — reduced from 2 s to 0.5 s to avoid blocking startup
    time.sleep(0.5)
    SERIAL_CONNECTED = True
    print(f"[serial] ESP32 connected on {SERIAL_PORT} @ {SERIAL_BAUDRATE} baud")
except Exception as exc:
    esp32 = None
    SERIAL_CONNECTED = False
    print(f"[serial] ESP32 not found ({exc}). Running without buzzer or sensors.")

# ── Duplicate-message guard for alerts ────────────────────────────────────────
_last_message: str = ""


def send_alert(message: str) -> bool:
    """Send a warning string to the ESP32. Returns True if sent, False otherwise."""

    global _last_message

    if not SERIAL_CONNECTED or esp32 is None:
        return False

    if message == _last_message:
        return False  # Suppress duplicate spam

    try:
        with _write_lock:
            esp32.write(f"{message}\n".encode())
            esp32.flush()
        print(f"[serial] Sent: {message}")
        _last_message = message
        return True
    except Exception as exc:
        print(f"[serial] Send failed: {exc}")
        return False


# ── Sensor reader thread ───────────────────────────────────────────────────────
_reader_thread = None  # type: threading.Thread | None
_reader_running = False


def start_serial_reader() -> bool:
    """Start a background thread that reads sensor lines from the ESP32.

    Safe to call even when no ESP32 is connected (it simply does nothing),
    and safe to call more than once (a second call while a reader is
    already running is a no-op).
    """

    global _reader_thread, _reader_running

    if not SERIAL_CONNECTED or esp32 is None:
        return False
    if _reader_running:
        return True

    from src.sensor_manager import handle_line  # local import avoids a cycle

    def _run() -> None:
        global _reader_running
        _reader_running = True
        print("[serial] Sensor reader thread started.")
        while SERIAL_CONNECTED:
            try:
                raw = esp32.readline()
            except Exception as exc:
                print(f"[serial] Reader stopped: {exc}")
                break
            if not raw:
                continue  # readline() timeout with nothing received — normal
            try:
                line = raw.decode(errors="replace")
            except Exception:
                continue
            handle_line(line)
        _reader_running = False
        print("[serial] Sensor reader thread stopped.")

    _reader_thread = threading.Thread(
        target=_run, daemon=True, name="postureguard-serial-reader"
    )
    _reader_thread.start()
    return True
