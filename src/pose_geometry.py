"""Shared geometry helpers for turning MediaPipe pose landmarks into the
normalized ratios used by posture scoring, attention detection, and
per-user calibration.

Every ratio here is normalized by shoulder width, so a reading means the
same thing whether the user is sitting close to the camera or further back.
This is the fix for the original formulas, which compared raw normalized
frame coordinates against fixed constants (e.g. "neck offset > 0.05") with
no correction for how far away the person was sitting.
"""

from __future__ import annotations

MIN_SHOULDER_WIDTH = 1e-4


def extract_ratios(nose, left_shoulder, right_shoulder) -> dict:
    """Return normalized geometry ratios for the current frame.

    ``nose``, ``left_shoulder``, ``right_shoulder`` are MediaPipe pose
    landmarks (each with ``.x``, ``.y``, ``.z`` in normalized coordinates).
    """

    shoulder_mid_x = (left_shoulder.x + right_shoulder.x) / 2.0
    shoulder_width = max(abs(left_shoulder.x - right_shoulder.x), MIN_SHOULDER_WIDTH)

    # MediaPipe's z is an approximate depth (same scale as x), relative and
    # noisier than x/y since it is inferred rather than directly observed —
    # but it is a genuine forward-lean signal a purely 2D (x, y) formula
    # cannot see at all, which is exactly the gap called out in this
    # project's own Future Work section ("3D Landmark Integration").
    shoulder_mid_z = (left_shoulder.z + right_shoulder.z) / 2.0

    return {
        "shoulder_width": shoulder_width,
        # Head turned/leaning sideways relative to the shoulders.
        "lateral_ratio": (nose.x - shoulder_mid_x) / shoulder_width,
        # Head pushed toward the camera relative to the shoulders (hunching).
        "forward_lean_ratio": (shoulder_mid_z - nose.z) / shoulder_width,
        # One shoulder higher than the other.
        "shoulder_tilt_ratio": abs(left_shoulder.y - right_shoulder.y) / shoulder_width,
    }
