"""Posture scoring from normalized MediaPipe pose ratios.

The original version of this file was a hard step function:

    if shoulder_diff > 0.03: score -= 30
    if neck_offset > 0.05: score -= 40

That has two real problems. First, it is not normalized by shoulder width,
so identical posture scores differently purely depending on how far the user
is sitting from the camera. Second, being a step function, the score could
only ever land on five values (100 / 70 / 60 / 30 / 0) — which is also why
the dashboard's "smoothly filling" score ring could never actually move
smoothly.

This version fixes both: every ratio is normalized by shoulder width (see
``src.pose_geometry``), and the score is continuous. When a per-session
calibration baseline is supplied (see ``src.calibration``), penalties are
measured as *deviation from this user's own neutral posture* rather than one
fixed assumption for every body type and camera placement.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_BASELINE = {
    "lateral_ratio": 0.0,
    "forward_lean_ratio": 0.0,
    "shoulder_tilt_ratio": 0.0,
}

# Coefficients are tuned for a typical laptop-webcam distance (roughly
# 50-80cm). If your camera sits much closer or further away than that,
# these can be adjusted here.
LATERAL_PENALTY_SCALE = 80.0
LATERAL_PENALTY_CAP = 30.0
FORWARD_PENALTY_SCALE = 60.0
FORWARD_PENALTY_CAP = 45.0
TILT_PENALTY_SCALE = 150.0
TILT_PENALTY_CAP = 30.0

GOOD_THRESHOLD = 75.0
MODERATE_THRESHOLD = 50.0


def calculate_posture(ratios: dict, baseline: Optional[dict] = None):
    """Return ``(score, state, color, breakdown)`` for the current frame.

    ``ratios`` — output of ``src.pose_geometry.extract_ratios``.
    ``baseline`` — this session's personal calibration baseline, or ``None``
    while calibration is still in progress (in which case a neutral
    zero-point is used, so a live score is still shown, just not yet
    personalized).
    """

    base = {**DEFAULT_BASELINE, **(baseline or {})}

    lateral_drift = abs(ratios["lateral_ratio"] - base["lateral_ratio"])
    forward_drift = max(0.0, ratios["forward_lean_ratio"] - base["forward_lean_ratio"])
    tilt_drift = max(0.0, ratios["shoulder_tilt_ratio"] - base["shoulder_tilt_ratio"])

    lateral_penalty = min(LATERAL_PENALTY_CAP, lateral_drift * LATERAL_PENALTY_SCALE)
    forward_penalty = min(FORWARD_PENALTY_CAP, forward_drift * FORWARD_PENALTY_SCALE)
    tilt_penalty = min(TILT_PENALTY_CAP, tilt_drift * TILT_PENALTY_SCALE)

    score = 100.0 - lateral_penalty - forward_penalty - tilt_penalty
    score = max(0.0, min(100.0, score))

    if score >= GOOD_THRESHOLD:
        state, color = "GOOD", (0, 255, 0)
    elif score >= MODERATE_THRESHOLD:
        state, color = "MODERATE", (0, 255, 255)
    else:
        state, color = "BAD", (0, 0, 255)

    # Explainability breakdown: exactly which factor is dragging the score
    # down right now, so the number is never a black box.
    breakdown = {
        "lateral_lean": round(-lateral_penalty, 1),
        "forward_hunch": round(-forward_penalty, 1),
        "shoulder_tilt": round(-tilt_penalty, 1),
    }

    return round(score, 1), state, color, breakdown
