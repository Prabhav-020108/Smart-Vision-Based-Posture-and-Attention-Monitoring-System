"""Composite focus scoring layer -- blends the existing camera-based focus
percentage with HRV (heart-rate variability proxy) and ambient light, using
a camera-anchored, confidence-scaled, bounded modifier rather than a plain
weighted average. See project docs for the full design rationale; in short:
camera stays the anchor and ground truth, HRV/light only nudge it within a
small capped range, and that nudge shrinks further when the camera reading
is already confident (near 0 or 100). With no sensors connected the output
is mathematically identical to the camera-only percentage -- this is a new
read-only display metric, not a replacement for the existing focus_percentage
used everywhere else in the app (alerts, timers, gamification, CSV export).
"""

from __future__ import annotations

import math
from typing import Optional

HRV_STABILITY_WIDTH_PCT = 25.0   # Gaussian falloff width for HR deviation
HRV_MAX_SWING = 6.0              # max points HRV can move the score
ENV_MAX_SWING = 4.0              # max points light can move the score
ENV_IDEAL_MIN = 30.0             # comfortable light band (brightness_score %)
ENV_IDEAL_MAX = 75.0
HR_BASELINE_MIN_SAMPLES = 5      # reliable readings needed before HRV counts


class CompositeFocusEngine:
    """Tracks a per-session HR baseline and blends camera + HRV + light.

    Instantiate once per VisionService (i.e. once per monitoring session)
    so that the HR baseline accumulates correctly across frames.
    """

    def __init__(self) -> None:
        self._hr_baseline_samples: list[float] = []
        self._hr_baseline: Optional[float] = None

    # ── Baseline ─────────────────────────────────────────────────────────────

    def _update_hr_baseline(self, bpm: float) -> None:
        """Quietly average the first HR_BASELINE_MIN_SAMPLES reliable readings
        into a personal baseline for this session.  Once the baseline is set
        it is never updated again (it represents 'resting normal' for this
        user at the start of the session).
        """
        if self._hr_baseline is not None:
            return  # already locked in
        self._hr_baseline_samples.append(bpm)
        if len(self._hr_baseline_samples) >= HR_BASELINE_MIN_SAMPLES:
            self._hr_baseline = sum(self._hr_baseline_samples) / len(
                self._hr_baseline_samples
            )

    # ── Sub-scores ────────────────────────────────────────────────────────────

    @staticmethod
    def _hrv_stability_score(current_bpm: float, baseline_bpm: float) -> float:
        """Gaussian falloff centred on the personal baseline.

        Returns 100 when current_bpm == baseline_bpm (perfectly stable),
        falling smoothly toward 0 as the deviation grows.  Using a Gaussian
        instead of a hard cutoff means ordinary fluctuation (±5 bpm) barely
        moves the score while a significant stress response (±30 bpm) is
        clearly reflected.
        """
        deviation_pct = abs(current_bpm - baseline_bpm) / baseline_bpm * 100.0
        return 100.0 * math.exp(-((deviation_pct / HRV_STABILITY_WIDTH_PCT) ** 2))

    @staticmethod
    def _env_score(brightness_pct: float) -> float:
        """Environment quality score (0-100) based on ambient light.

        A comfortable, glare-free middle band [ENV_IDEAL_MIN, ENV_IDEAL_MAX]
        scores 100.  Below that band (too dark) and above it (too bright /
        glare risk) both fall off linearly.  This is deliberately symmetric
        rather than 'brighter is better'.
        """
        if ENV_IDEAL_MIN <= brightness_pct <= ENV_IDEAL_MAX:
            return 100.0
        if brightness_pct < ENV_IDEAL_MIN:
            return 100.0 * (brightness_pct / ENV_IDEAL_MIN)
        # brightness > ENV_IDEAL_MAX
        return 100.0 * max(0.0, (100.0 - brightness_pct) / (100.0 - ENV_IDEAL_MAX))

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(self, camera_focus_pct: float, sensors: dict) -> dict:
        """Return the composite focus result dict.

        Parameters
        ----------
        camera_focus_pct:
            The existing camera-only focus percentage (0-100), already
            computed by calculate_focus_percentage().  This is the anchor —
            it is never replaced, only nudged.
        sensors:
            The dict returned by sensor_manager.get_latest()
            (keys: 'hr', 'hr_reliable', 'lux').

        Returns
        -------
        dict with keys:
            composite_focus_percentage  – the final blended value (0-100)
            camera_focus_percentage     – the unmodified camera anchor
            components                  – sub-scores that were available
            modifier_applied            – actual points added/subtracted
            hr_baseline_bpm             – locked-in baseline, or None
            formula                     – metadata for transparency
        """

        components: dict = {"camera": round(camera_focus_pct, 1)}
        raw_modifier = 0.0

        # ── HRV contribution ─────────────────────────────────────────────────
        hr = sensors.get("hr")
        if hr and sensors.get("hr_reliable"):
            self._update_hr_baseline(hr["bpm"])
            if self._hr_baseline is not None:
                hrv_score = self._hrv_stability_score(hr["bpm"], self._hr_baseline)
                components["hrv"] = round(hrv_score, 1)
                # hrv_score of 50 → 0 modifier; 100 → +HRV_MAX_SWING; 0 → -HRV_MAX_SWING
                raw_modifier += (hrv_score - 50.0) / 50.0 * HRV_MAX_SWING

        # ── Ambient light contribution ────────────────────────────────────────
        lux = sensors.get("lux")
        if lux:
            env_score = self._env_score(lux["brightness_score"])
            components["env"] = round(env_score, 1)
            raw_modifier += (env_score - 50.0) / 50.0 * ENV_MAX_SWING

        # ── Confidence scaling ────────────────────────────────────────────────
        # At camera=50 (maximally ambiguous) → scale=1.0 (full modifier)
        # At camera=0 or 100 (camera is sure) → scale=0.0 (modifier vanishes)
        confidence_scale = 1.0 - abs(camera_focus_pct - 50.0) / 50.0
        effective_modifier = raw_modifier * confidence_scale

        composite = max(0.0, min(100.0, camera_focus_pct + effective_modifier))

        return {
            "composite_focus_percentage": round(composite, 1),
            "camera_focus_percentage": round(camera_focus_pct, 1),
            "components": components,
            "modifier_applied": round(effective_modifier, 1),
            "hr_baseline_bpm": (
                round(self._hr_baseline, 1) if self._hr_baseline is not None else None
            ),
            "formula": {
                "method": "camera-anchored confidence-scaled bounded modifier",
                "hrv_max_swing": HRV_MAX_SWING,
                "env_max_swing": ENV_MAX_SWING,
                "confidence_scale_applied": round(confidence_scale, 2),
            },
        }
