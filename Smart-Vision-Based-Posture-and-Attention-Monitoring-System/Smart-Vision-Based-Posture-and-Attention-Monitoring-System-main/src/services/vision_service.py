import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import cv2
import mediapipe as mp

from src.attention_tracker import detect_attention
from src.posture_detector import calculate_posture
from src.score_manager import calculate_focus_percentage
from src.services.alert_service import AlertService
from src.timer_manager import update_timers
from src.utils.config import CAMERA_INDEX


@dataclass
class VisionMetrics:
    frame: Any
    posture_score: Optional[int]
    posture_state: Optional[str]
    attention_state: Optional[str]
    focused_time: float
    distracted_time: float
    continuous_distraction_time: float
    bad_posture_time: float
    focus_percentage: float
    alert_message: str
    landmarks_detected: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "posture_score": self.posture_score,
            "posture_state": self.posture_state,
            "attention_state": self.attention_state,
            "focused_time": self.focused_time,
            "distracted_time": self.distracted_time,
            "continuous_distraction_time": self.continuous_distraction_time,
            "bad_posture_time": self.bad_posture_time,
            "focus_percentage": self.focus_percentage,
            "alert_message": self.alert_message,
            "landmarks_detected": self.landmarks_detected,
        }


class VisionService:
    def __init__(self, camera_index=CAMERA_INDEX, alert_service=None):
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose()
        self.mp_draw = mp.solutions.drawing_utils
        self.cap = cv2.VideoCapture(camera_index)
        self.alert_service = alert_service or AlertService()

        self.focused_time = 0
        self.distracted_time = 0
        self.continuous_distraction_time = 0
        self.bad_posture_time = 0
        self.prev_time = time.time()

    def process_next_frame(self, draw_overlay=True):
        ret, frame = self.cap.read()

        if not ret:
            return None

        return self.process_frame(frame, draw_overlay=draw_overlay)

    def process_frame(self, frame, draw_overlay=True):
        current_time = time.time()
        dt = current_time - self.prev_time
        self.prev_time = current_time

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_frame)

        posture_score = None
        posture_state = None
        attention_state = None
        alert_message = ""
        landmarks_detected = results.pose_landmarks is not None

        if landmarks_detected:
            landmarks = results.pose_landmarks.landmark
            nose = landmarks[0]
            left_shoulder = landmarks[11]
            right_shoulder = landmarks[12]

            posture_score, posture_state, posture_color = calculate_posture(
                nose,
                left_shoulder,
                right_shoulder,
            )
            attention_state, attention_color = detect_attention(nose)

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
                )

        focus_percentage = calculate_focus_percentage(
            self.focused_time,
            self.distracted_time,
        )

        return VisionMetrics(
            frame=frame,
            posture_score=posture_score,
            posture_state=posture_state,
            attention_state=attention_state,
            focused_time=self.focused_time,
            distracted_time=self.distracted_time,
            continuous_distraction_time=self.continuous_distraction_time,
            bad_posture_time=self.bad_posture_time,
            focus_percentage=focus_percentage,
            alert_message=alert_message,
            landmarks_detected=landmarks_detected,
        ).to_dict()

    def release(self):
        self.cap.release()
        self.pose.close()

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
    ):
        self.mp_draw.draw_landmarks(
            frame,
            results.pose_landmarks,
            self.mp_pose.POSE_CONNECTIONS,
        )

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
        cv2.putText(
            frame,
            alert_message,
            (20, 420),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            3,
        )
