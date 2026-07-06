"""Parses sensor telemetry lines sent back from the ESP32 and keeps a short
rolling history for the dashboard and for correlating sensor readings with
focus/posture trends.

Wire protocol (one line per reading, newline terminated, sent by the ESP32):
    HR:<bpm>:<ibi_ms>:<quality0-100>      e.g.  HR:74:812:85
    LUX:<raw_adc_0_4095>                  e.g.  LUX:2130

A PPG pulse sensor like the MAX30102 only produces a clean reading when a
finger is resting still on it — normal typing/writing movement is a motion
artifact. Rather than smoothing over that and showing a fake-smooth number,
this module keeps ``quality`` alongside every reading and exposes
``hr_reliable`` in ``get_latest()``: the dashboard can then be honest about
when a heart-rate reading is trustworthy versus when it should be shown as
"no reliable signal", the same way consumer wearables handle motion
artifacts, instead of quietly inventing a number for every session.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

from src.utils.config import SENSOR_HR_MAX_BPM, SENSOR_HR_MIN_BPM

MIN_ACCEPTED_HR_QUALITY = 50
_STALE_AFTER_SECONDS = 10.0
_HISTORY_MAXLEN = 1200  # comfortably covers a long session at ~1 reading/sec

_lock = threading.Lock()
_latest_hr: Optional[dict[str, Any]] = None
_latest_lux: Optional[dict[str, Any]] = None
_hr_history: "deque[dict[str, Any]]" = deque(maxlen=_HISTORY_MAXLEN)
_lux_history: "deque[dict[str, Any]]" = deque(maxlen=_HISTORY_MAXLEN)


def reset() -> None:
    """Clear all sensor state. Called when a new monitoring session starts."""

    global _latest_hr, _latest_lux
    with _lock:
        _latest_hr = None
        _latest_lux = None
        _hr_history.clear()
        _lux_history.clear()


def handle_line(line: str) -> None:
    """Parse one line received from the ESP32 and update rolling state.

    Unrecognized lines (the boot banner, the "Received: ..." echo of a
    buzzer command, or a partially-received line) are expected and silently
    ignored — this is not an error condition.
    """

    line = line.strip()
    if not line:
        return

    try:
        if line.startswith("HR:"):
            _handle_hr_line(line)
        elif line.startswith("LUX:"):
            _handle_lux_line(line)
    except (ValueError, IndexError) as exc:
        print(f"[sensor] Ignoring malformed line {line!r}: {exc}")


def _handle_hr_line(line: str) -> None:
    _, bpm_s, ibi_s, quality_s = line.split(":", 3)
    bpm = float(bpm_s)
    ibi_ms = float(ibi_s)
    quality = max(0.0, min(100.0, float(quality_s)))

    reading = {
        "bpm": bpm,
        "ibi_ms": ibi_ms,
        "quality": quality,
        "plausible": SENSOR_HR_MIN_BPM <= bpm <= SENSOR_HR_MAX_BPM,
        "timestamp": time.time(),
    }

    global _latest_hr
    with _lock:
        _latest_hr = reading
        _hr_history.append(reading)


def _handle_lux_line(line: str) -> None:
    _, raw_s = line.split(":", 1)
    raw = int(float(raw_s))
    brightness_score = round(max(0.0, min(100.0, raw / 4095.0 * 100.0)), 1)

    reading = {
        "raw": raw,
        "brightness_score": brightness_score,
        "timestamp": time.time(),
    }

    global _latest_lux
    with _lock:
        _latest_lux = reading
        _lux_history.append(reading)


def get_latest() -> dict[str, Any]:
    """Return the latest HR and LUX readings. Either may be ``None`` if no
    (recent, non-stale) reading is available."""

    now = time.time()
    with _lock:
        hr = (
            dict(_latest_hr)
            if _latest_hr and (now - _latest_hr["timestamp"]) <= _STALE_AFTER_SECONDS
            else None
        )
        lux = (
            dict(_latest_lux)
            if _latest_lux and (now - _latest_lux["timestamp"]) <= _STALE_AFTER_SECONDS
            else None
        )

    return {
        "hr": hr,
        "hr_reliable": bool(hr and hr["quality"] >= MIN_ACCEPTED_HR_QUALITY and hr["plausible"]),
        "lux": lux,
    }


def get_history(limit: int = 200) -> dict[str, Any]:
    """Return recent HR/LUX history for correlation charts."""

    limit = max(1, min(limit, _HISTORY_MAXLEN))
    with _lock:
        hr = list(_hr_history)[-limit:]
        lux = list(_lux_history)[-limit:]
    return {"hr": hr, "lux": lux}
