"""Threshold checks for posture and attention monitoring."""
from src.utils.config import (
    BAD_POSTURE_THRESHOLD_SECONDS,
    DISTRACTION_THRESHOLD_SECONDS,
)


def check_thresholds(continuous_distraction_time: float, bad_posture_time: float) -> str:
    """Return the current alert message based on accumulated timer values."""

    warning = ""

    # ── Distraction alerts ──────────────────────────────────────────────────
    if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS:
        warning = "PAY ATTENTION"

    if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS * 2:
        warning = "FOCUS ON STUDY"

    if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS * 4:
        warning = "CRITICAL DISTRACTION"

    # ── Posture alert ────────────────────────────────────────────────────────
    if bad_posture_time > BAD_POSTURE_THRESHOLD_SECONDS:
        warning = "FIX YOUR POSTURE"

    return warning
