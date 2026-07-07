"""VisionService — owns the camera + MediaPipe pipeline for one session.

Reliability: the original implementation returned ``None`` the moment a
single ``cap.read()`` call failed, and the caller simply gave up for good.
Integrated webcams do this occasionally under CPU load — a dropped USB
frame, a driver hiccup, Windows briefly reclaiming the camera — and one bad
frame should not end the whole session. ``process_next_frame`` keeps the
same simple contract (metrics dict on success, ``None`` on a failed read),
but ``reopen_capture`` now lets the *caller* (the worker loop in
``api/routes.py``) fully reconnect the camera after a run of failures
instead of the pipeline dying outright. The retry/backoff policy itself
lives in the worker loop, not here, so this class stays a straightforward
single-frame processor.

Everything else new here — calibration, the continuous posture/attention
formulas, the decay predictor, and sensor fusion — is implemented in the
modules this class delegates to; see their docstrings for the reasoning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import cv2
import mediapipe as mp

from src.attention_tracker import detect_attention
from src.calibration import CalibrationSession
from src.decay_predictor import FocusDecayPredictor
from src.focus_composite import CompositeFocusEngine
from src.pose_geometry import extract_ratios
from src.posture_detector import calculate_posture
from src.score_manager import calculate_focus_percentage
from src.sensor_manager import get_latest as get_latest_sensor_readings
from src.services.alert_service import AlertService
from src.timer_manager import update_timers
from src.utils.config import (
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    VISION_MODEL_COMPLEXITY,
)


@dataclass
class VisionMetrics:
    frame: Any
    posture_score: Optional[float]
    posture_state: Optional[str]
    posture_breakdown: Optional[Dict[str, float]]
    attention_state: Optional[str]
    focused_time: float
    distracted_time: float
    continuous_distraction_time: float
    bad_posture_time: float
    focus_percentage: float
    alert_message: str
    proactive_nudge: Optional[Dict[str, Any]]
    landmarks_detected: bool
    calibrating: bool
    calibration_seconds_remaining: float
    sensors: Dict[str, Any] = field(default_factory=dict)
    focus_composite: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "posture_score": self.posture_score,
            "posture_state": self.posture_state,
            "posture_breakdown": self.posture_breakdown,
            "attention_state": self.attention_state,
            "focused_time": self.focused_time,
            "distracted_time": self.distracted_time,
            "continuous_distraction_time": self.continuous_distraction_time,
            "bad_posture_time": self.bad_posture_time,
            "focus_percentage": self.focus_percentage,
            "alert_message": self.alert_message,
            "proactive_nudge": self.proactive_nudge,
            "landmarks_detected": self.landmarks_detected,
            "calibrating": self.calibrating,
            "calibration_seconds_remaining": self.calibration_seconds_remaining,
            "sensors": self.sensors,
            "focus_composite": self.focus_composite,
        }


class VisionService:
    def __init__(
        self,
        camera_index: int = CAMERA_INDEX,
        alert_service: Optional[AlertService] = None,
        camera_width: int = CAMERA_WIDTH,
        camera_height: int = CAMERA_HEIGHT,
        model_complexity: int = VISION_MODEL_COMPLEXITY,
    ):
        self.camera_index = camera_index
        self.camera_width = camera_width
        self.camera_height = camera_height
        self.model_complexity = model_complexity

        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(model_complexity=model_complexity)
        self.mp_draw = mp.solutions.drawing_utils
        self.cap = self._open_capture()
        self.alert_service = alert_service or AlertService()

        self.calibration = CalibrationSession()
        self.calibration.start()
        self.decay_predictor = FocusDecayPredictor()
        self.focus_engine = CompositeFocusEngine()

        self.focused_time = 0.0
        self.distracted_time = 0.0
        self.continuous_distraction_time = 0.0
        self.bad_posture_time = 0.0
        self.prev_time = time.time()

    # ── Camera lifecycle ────────────────────────────────────────────────────

    def _open_capture(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if self.camera_width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        if self.camera_height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        try:
            # Not every backend supports this; harmless if it's ignored.
            # Keeping the buffer at 1 frame avoids the driver silently
            # queuing up stale frames when processing falls behind.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def reopen_capture(self) -> bool:
        """Release and recreate the camera capture. Returns True on success.

        This is what the worker loop calls after a run of consecutive read
        failures — a full reconnect, rather than hoping the next read call
        magically works.
        """

        try:
            self.cap.release()
        except Exception:
            pass

        self.cap = self._open_capture()
        return bool(self.cap.isOpened())

    # ── Frame processing ────────────────────────────────────────────────────

    def process_next_frame(self, draw_overlay: bool = True):
        """Read and process one frame.

        Returns the processed metrics dict on success, or ``None`` if this
        particular read failed. The caller decides how many ``None``s in a
        row are worth tolerating before reconnecting — see
        ``api/routes.py``'s worker loop.
        """

        ret, frame = self.cap.read()

        if not ret:
            return None

        return self.process_frame(frame, draw_overlay=draw_overlay)

    def process_frame(self, frame, draw_overlay: bool = True):
        current_time = time.time()
        dt = max(0.0, current_time - self.prev_time)
        self.prev_time = current_time

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_frame)

        posture_score = None
        posture_state = None
        posture_breakdown = None
        posture_color = (255, 255, 255)
        attention_state = None
        attention_color = (255, 255, 255)
        alert_message = ""
        proactive_nudge = None
        landmarks_detected = results.pose_landmarks is not None

        focus_percentage = calculate_focus_percentage(self.focused_time, self.distracted_time)
        sensors = get_latest_sensor_readings()
        # Composite engine blends HRV + light on top of the camera anchor.
        # Note: focus_composite is a NEW read-only display metric and is
        # deliberately NOT fed into alert thresholds, timers, decay_predictor,
        # or gamification — those all keep using focus_percentage unchanged.
        focus_composite = self.focus_engine.compute(focus_percentage, sensors)

        if landmarks_detected:
            landmarks = results.pose_landmarks.landmark
            nose = landmarks[0]
            left_shoulder = landmarks[11]
            right_shoulder = landmarks[12]

            ratios = extract_ratios(nose, left_shoulder, right_shoulder)

            if self.calibration.is_calibrating:
                self.calibration.add_sample(ratios)

            baseline = self.calibration.get_baseline()

            posture_score, posture_state, posture_color, posture_breakdown = calculate_posture(
                ratios, baseline=baseline
            )
            attention_state, attention_color, _lateral = detect_attention(ratios, baseline=baseline)

            # Timers, alerts, and the decay trend only start accumulating
            # once calibration has finished — before that, the baseline
            # doesn't exist yet, so "distracted"/"bad posture" would just be
            # measured against a placeholder, not this user.
            if not self.calibration.is_calibrating:
                (
                    self.focused_time,
                    self.distracted_time,
                    self.continuous_distraction_time,
                    self.bad_posture_time,
                ) = update_timers(
                    attention_state,
                    posture_state,
                    dt,
                    self.focused_time,
                    self.distracted_time,
                    self.continuous_distraction_time,
                    self.bad_posture_time,
                )

                alert_message = self.alert_service.evaluate_alert(
                    self.continuous_distraction_time,
                    self.bad_posture_time,
                )

                focus_percentage_now = calculate_focus_percentage(
                    self.focused_time, self.distracted_time
                )
                self.decay_predictor.add_sample(focus_percentage_now)
                proactive_nudge = self.decay_predictor.check()

            if draw_overlay:
                self._draw_overlay(
                    frame,
                    results,
                    posture_score,
                    posture_state,
                    posture_color,
                    attention_state,
                    attention_color,
                    alert_message,
                    sensors,
                    focus_composite,
                )
        elif draw_overlay and self.calibration.is_calibrating:
            self._draw_calibration_banner(frame)

        return VisionMetrics(
            frame=frame,
            posture_score=posture_score,
            posture_state=posture_state,
            posture_breakdown=posture_breakdown,
            attention_state=attention_state,
            focused_time=self.focused_time,
            distracted_time=self.distracted_time,
            continuous_distraction_time=self.continuous_distraction_time,
            bad_posture_time=self.bad_posture_time,
            focus_percentage=focus_percentage,
            alert_message=alert_message,
            proactive_nudge=proactive_nudge,
            landmarks_detected=landmarks_detected,
            calibrating=self.calibration.is_calibrating,
            calibration_seconds_remaining=self.calibration.seconds_remaining,
            sensors=sensors,
            focus_composite=focus_composite,
        ).to_dict()

    def release(self):
        try:
            self.cap.release()
        except Exception:
            pass
        self.pose.close()

    # ── Overlay drawing ─────────────────────────────────────────────────────

    def _draw_calibration_banner(self, frame) -> None:
        cv2.putText(
            frame,
            f"Calibrating... sit naturally ({int(self.calibration.seconds_remaining) + 1}s)",
            (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 200, 255),
            2,
        )

    def _draw_overlay(
        self,
        frame,
        results,
        posture_score,
        posture_state,
        posture_color,
        attention_state,
        attention_color,
        alert_message,
        sensors: dict | None = None,
        focus_composite: dict | None = None,
    ):
        self.mp_draw.draw_landmarks(
            frame,
            results.pose_landmarks,
            self.mp_pose.POSE_CONNECTIONS,
        )

        if self.calibration.is_calibrating:
            self._draw_calibration_banner(frame)
            return

        cv2.putText(
            frame,
            f"Posture Score: {posture_score}",
            (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            posture_color,
            2,
        )
        cv2.putText(
            frame,
            f"Posture: {posture_state}",
            (20, 100),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            posture_color,
            2,
        )
        cv2.putText(
            frame,
            f"Attention: {attention_state}",
            (20, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            attention_color,
            2,
        )
        cv2.putText(
            frame,
            f"Focused Time: {int(self.focused_time)}s",
            (20, 220),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            f"Distracted Time: {int(self.distracted_time)}s",
            (20, 260),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        cv2.putText(
            frame,
            f"Focus Percentage: {int(calculate_focus_percentage(self.focused_time, self.distracted_time))}%",
            (20, 300),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            frame,
            f"Current Distraction: {int(self.continuous_distraction_time)}s",
            (20, 340),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        # ── NEW: HRV sensor line ─────────────────────────────────────────────
        if sensors:
            hr = sensors.get("hr")
            if hr and sensors.get("hr_reliable"):
                hrv_text = f"HRV: {int(round(hr['bpm']))} bpm"
                hrv_color = (0, 255, 128)     # green — reliable reading
            elif hr:
                hrv_text = f"HRV: {int(round(hr['bpm']))} bpm (low quality)"
                hrv_color = (0, 180, 255)     # amber — reading present but unreliable
            else:
                hrv_text = "HRV: --"
                hrv_color = (120, 120, 120)   # dim grey — no reading
        else:
            hrv_text = "HRV: --"
            hrv_color = (120, 120, 120)

        cv2.putText(
            frame,
            hrv_text,
            (20, 380),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            hrv_color,
            2,
        )

        # ── NEW: Ambient light line ──────────────────────────────────────────
        if sensors:
            lux = sensors.get("lux")
            light_text = (
                f"Light: {int(round(lux['brightness_score']))}%" if lux else "Light: --"
            )
        else:
            light_text = "Light: --"

        cv2.putText(
            frame,
            light_text,
            (20, 420),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        # ── NEW: Composite (blended) focus line ──────────────────────────────
        if focus_composite:
            composite_pct = focus_composite.get("composite_focus_percentage")
            blended_text = (
                f"Focus (blended): {int(round(composite_pct))}%"
                if composite_pct is not None
                else "Focus (blended): --"
            )
        else:
            blended_text = "Focus (blended): --"

        cv2.putText(
            frame,
            blended_text,
            (20, 460),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 220, 255),   # cyan — distinct from the white camera-only line
            2,
        )

        # ── Existing: Alert message (shifted down to avoid overlap) ──────────
        if alert_message:
            cv2.putText(
                frame,
                alert_message,
                (20, 510),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                3,
            )
