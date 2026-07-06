"""Attention (focused/distracted) detection from normalized MediaPipe pose ratios.

The original version flagged distraction using the nose's *absolute*
position in the frame (``nose.x < 0.30 or nose.x > 0.70``), which silently
assumes the user's face always sits dead-centre in the shot. A webcam
mounted slightly off-axis, or a monitor placed slightly to one side, biases
every reading regardless of what the user's head is actually doing.

This version instead measures the nose's position *relative to the
shoulder midpoint*, normalized by shoulder width (see
``src.pose_geometry``), and compares that against this session's own
calibration baseline — so what counts as "facing the screen" is defined by
how this user actually sits, not by where the camera happens to be pointed.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_LATERAL_BASELINE = 0.0
DISTRACTION_RATIO_THRESHOLD = 0.35


def detect_attention(ratios: dict, baseline: Optional[dict] = None, threshold: float = DISTRACTION_RATIO_THRESHOLD):
    """Return ``(attention_state, color, lateral_ratio)`` for the current frame.

    ``ratios`` — output of ``src.pose_geometry.extract_ratios``.
    ``baseline`` — this session's personal calibration baseline, or ``None``
    while calibration is still in progress.
    """

    baseline_lateral = (baseline or {}).get("lateral_ratio", DEFAULT_LATERAL_BASELINE)
    lateral_ratio = ratios["lateral_ratio"]
    deviation = abs(lateral_ratio - baseline_lateral)

    if deviation > threshold:
        return "DISTRACTED", (0, 0, 255), lateral_ratio
    return "FOCUSED", (0, 255, 0), lateral_ratio
