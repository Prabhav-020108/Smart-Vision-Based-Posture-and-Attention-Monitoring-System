"""Predictive focus-decay modelling.

Every alert elsewhere in this project is *reactive*: it fires only after the
user has already been distracted or slouching for N continuous seconds.
Sustained-attention research on the "vigilance decrement" (task performance
reliably declines the longer a monitoring task continues — first documented
in Mackworth's WWII radar-watch studies, and the reason productivity advice
often points to natural ~90 minute attention cycles) says the decline is
visible as a *trend* before it fully crosses a hard threshold.

This module looks at the trend in recent focus-percentage samples and raises
a softer, earlier nudge when things are heading downward — a genuinely
different signal from "you have already been distracted too long."

The trend itself is a plain least-squares slope over a recent time window —
deliberately simple and inspectable rather than a black-box model, both
because that is the honest way to describe it and because a simple formula
is something you can actually explain, live, in a viva.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from src.utils.config import DECAY_ALERT_COOLDOWN_SECONDS, DECAY_TREND_WINDOW_SECONDS

# Slope is in focus-percentage points lost per second. A sustained decline
# steeper than this over the trend window counts as "heading downward".
DECLINE_SLOPE_THRESHOLD = -0.35
MIN_SAMPLES_FOR_TREND = 6


class FocusDecayPredictor:
    """Tracks a rolling window of focus readings and flags a declining trend."""

    def __init__(
        self,
        window_seconds: float = DECAY_TREND_WINDOW_SECONDS,
        cooldown_seconds: float = DECAY_ALERT_COOLDOWN_SECONDS,
    ):
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._points: "deque[tuple[float, float]]" = deque()
        self._last_nudge_at: Optional[float] = None

    def add_sample(self, focus_percentage: float, *, now: Optional[float] = None) -> None:
        """Record one focus-percentage reading and drop anything outside the window."""

        now = now if now is not None else time.monotonic()
        self._points.append((now, focus_percentage))
        cutoff = now - self.window_seconds
        while self._points and self._points[0][0] < cutoff:
            self._points.popleft()

    def _slope(self) -> Optional[float]:
        """Least-squares slope of focus_percentage vs. time, in points/second."""

        n = len(self._points)
        if n < MIN_SAMPLES_FOR_TREND:
            return None

        t0 = self._points[0][0]
        xs = [p[0] - t0 for p in self._points]
        ys = [p[1] for p in self._points]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)

        if denominator == 0:
            return None
        return numerator / denominator

    def check(self, *, now: Optional[float] = None) -> Optional[dict]:
        """Return a nudge payload if focus is trending down, else ``None``."""

        now = now if now is not None else time.monotonic()
        slope = self._slope()
        if slope is None or slope > DECLINE_SLOPE_THRESHOLD:
            return None

        if self._last_nudge_at is not None and (now - self._last_nudge_at) < self.cooldown_seconds:
            return None

        self._last_nudge_at = now
        window_minutes = self.window_seconds / 60.0
        return {
            "type": "FOCUS_DECLINING",
            "message": (
                f"Focus has been trending down over the last "
                f"{window_minutes:.0f} minutes — a short break now tends to "
                f"help more than pushing through."
            ),
            "slope_per_minute": round(slope * 60.0, 2),
        }
