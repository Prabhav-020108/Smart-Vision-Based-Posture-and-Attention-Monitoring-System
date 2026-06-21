"""Alert orchestration for posture and attention monitoring."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Callable

from src.db import crud
from src.serial_manager import send_alert
from src.utils.config import BAD_POSTURE_THRESHOLD_SECONDS, DISTRACTION_THRESHOLD_SECONDS

PAY_ATTENTION = "PAY ATTENTION"
FOCUS_ON_STUDY = "FOCUS ON STUDY"
CRITICAL_DISTRACTION = "CRITICAL DISTRACTION"
FIX_YOUR_POSTURE = "FIX YOUR POSTURE"

DEFAULT_ALERT_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "5"))


class AlertService:
    """Evaluate, persist, and emit user alerts.

    The service centralizes alert-related side effects so the vision pipeline can
    stay focused on extracting posture and attention metrics. Alerts are emitted
    only when an alert condition exists and the cooldown permits another buzzer
    event.
    """

    def __init__(
        self,
        *,
        cooldown_seconds: float = DEFAULT_ALERT_COOLDOWN_SECONDS,
        serial_sender: Callable[[str], bool | None] = send_alert,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.serial_sender = serial_sender
        self._last_emitted_at: float | None = None

    def evaluate_alert(
        self,
        continuous_distraction_time: float,
        bad_posture_time: float,
    ) -> str:
        """Return the alert message for the current metrics, or an empty string."""

        warning = ""

        if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS:
            warning = PAY_ATTENTION

        if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS * 2:
            warning = FOCUS_ON_STUDY

        if continuous_distraction_time > DISTRACTION_THRESHOLD_SECONDS * 4:
            warning = CRITICAL_DISTRACTION

        if bad_posture_time > BAD_POSTURE_THRESHOLD_SECONDS:
            warning = FIX_YOUR_POSTURE

        return warning

    def should_emit_alert(self, alert_message: str, *, now: float | None = None) -> bool:
        """Return whether an alert should be emitted after applying cooldown."""

        if not alert_message:
            return False

        current_time = now if now is not None else time.time()
        if self._last_emitted_at is None:
            return True

        return current_time - self._last_emitted_at >= self.cooldown_seconds

    def handle_metrics(
        self,
        metrics: dict[str, Any],
        *,
        db: Any | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Evaluate metrics, persist an alert telemetry event, and notify ESP32.

        Returns True when the alert was accepted for emission. Missing or failed
        serial hardware is treated as a soft failure after any telemetry event is
        saved, allowing the application to keep running without an ESP32.
        """

        alert_message = self.evaluate_alert(
            metrics.get("continuous_distraction_time", 0.0),
            metrics.get("bad_posture_time", 0.0),
        )
        metrics["alert_message"] = alert_message

        if not self.should_emit_alert(alert_message):
            return False

        self._save_alert_telemetry(metrics, db=db, session_id=session_id)

        try:
            self.serial_sender(alert_message)
        except Exception as exc:
            print(f"Alert serial send skipped: {exc}")

        self._last_emitted_at = time.time()
        return True

    def _save_alert_telemetry(
        self,
        metrics: dict[str, Any],
        *,
        db: Any | None,
        session_id: str | None,
    ) -> None:
        """Save alert details on a telemetry sample when database context exists."""

        alert_message = metrics.get("alert_message")
        if db is None or session_id is None or not alert_message:
            return

        try:
            crud.create_telemetry_sample(
                db,
                session_id=session_id,
                timestamp=datetime.utcnow(),
                posture_score=metrics.get("posture_score"),
                posture_state=metrics.get("posture_state"),
                attention_state=metrics.get("attention_state"),
                focused_time=metrics.get("focused_time", 0.0),
                distracted_time=metrics.get("distracted_time", 0.0),
                continuous_distraction_time=metrics.get("continuous_distraction_time", 0.0),
                bad_posture_time=metrics.get("bad_posture_time", 0.0),
                focus_percentage=metrics.get("focus_percentage"),
                alert_message=alert_message,
            )
        except Exception as exc:
            print(f"Alert telemetry save skipped: {exc}")
