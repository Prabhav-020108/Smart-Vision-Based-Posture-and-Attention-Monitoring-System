"""Per-session posture calibration.

MediaPipe gives geometry, not context: it cannot tell whether the person in
frame is sitting close to the camera or far from it, whether the webcam is
mounted slightly off-centre, or what "sitting normally" looks like for their
particular body. The original code used one fixed threshold for every user
and every camera setup — which is also why the posture score could only ever
land on a handful of discrete values instead of moving smoothly.

``CalibrationSession`` fixes this by recording a short window of ratios right
after a session starts, while the user just sits normally, and averaging
that window into this session's personal zero-point. Every subsequent score
is then measured as a deviation from that baseline instead of from a
one-size-fits-all assumption.
"""

from __future__ import annotations

import time
from typing import Optional

from src.utils.config import CALIBRATION_DURATION_SECONDS

_RATIO_KEYS = ("lateral_ratio", "forward_lean_ratio", "shoulder_tilt_ratio")


class CalibrationSession:
    """Collects a short window of pose ratios and averages them into a baseline."""

    def __init__(self, duration_seconds: float = CALIBRATION_DURATION_SECONDS):
        self.duration_seconds = max(1.0, duration_seconds)
        self._started_at: Optional[float] = None
        self._sums = {key: 0.0 for key in _RATIO_KEYS}
        self._count = 0
        self._baseline: Optional[dict] = None

    def start(self) -> None:
        """Begin (or restart) the calibration window."""

        self._started_at = time.monotonic()
        self._sums = {key: 0.0 for key in _RATIO_KEYS}
        self._count = 0
        self._baseline = None

    @property
    def is_calibrating(self) -> bool:
        return self._baseline is None

    @property
    def seconds_remaining(self) -> float:
        if self._started_at is None:
            return 0.0
        elapsed = time.monotonic() - self._started_at
        return max(0.0, self.duration_seconds - elapsed)

    def add_sample(self, ratios: dict) -> None:
        """Feed one frame's ratios into the running average.

        Once the calibration window elapses, the accumulated average is
        frozen as the baseline and further samples are ignored (calling this
        again after that point is a harmless no-op).
        """

        if self._baseline is not None or self._started_at is None:
            return

        for key in _RATIO_KEYS:
            self._sums[key] += ratios.get(key, 0.0)
        self._count += 1

        if self.seconds_remaining <= 0 and self._count > 0:
            self._baseline = {key: self._sums[key] / self._count for key in _RATIO_KEYS}

    def get_baseline(self) -> Optional[dict]:
        """Return the frozen baseline, or ``None`` while still calibrating."""

        return self._baseline
