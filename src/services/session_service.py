"""Session-level persistence and summary helpers.

This service is intentionally framework-agnostic so it can be used by the
current OpenCV loop in ``main.py`` and by a future FastAPI worker that processes
camera frames in the background.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session as SQLAlchemySession

from src.db import crud, models
from src.db.database import SessionLocal


@dataclass(frozen=True)
class SessionSummary:
    """Calculated summary for a monitoring session."""

    session_id: str
    started_at: datetime
    ended_at: datetime | None
    focused_time: float
    distracted_time: float
    focus_percentage: float
    sample_count: int
    bad_posture_time: float
    continuous_distraction_time: float
    latest_attention_state: str | None
    latest_posture_state: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "focused_time": self.focused_time,
            "distracted_time": self.distracted_time,
            "focus_percentage": self.focus_percentage,
            "sample_count": self.sample_count,
            "bad_posture_time": self.bad_posture_time,
            "continuous_distraction_time": self.continuous_distraction_time,
            "latest_attention_state": self.latest_attention_state,
            "latest_posture_state": self.latest_posture_state,
        }


class SessionService:
    """Persist sessions and telemetry samples to SQLite via SQLAlchemy."""

    def __init__(self, db: SQLAlchemySession | None = None):
        self._external_db = db

    def start_session(
        self,
        *,
        user_id: str | None = None,
        device_id: str | None = None,
        session_id: str | None = None,
    ) -> models.Session:
        """Start a new monitoring session with a generated session ID."""

        with self._session_scope() as db:
            return crud.create_session(
                db,
                session_id=session_id or self.generate_session_id(),
                user_id=user_id,
                device_id=device_id,
            )

    def end_session(
        self,
        session_id: str,
        *,
        final_summary: dict[str, Any] | SessionSummary | None = None,
    ) -> models.Session | None:
        """End a session and store its final summary totals."""

        summary = final_summary or self.calculate_session_summary(session_id)
        summary_data = summary.to_dict() if isinstance(summary, SessionSummary) else summary

        with self._session_scope() as db:
            return crud.end_session(
                db,
                session_id=session_id,
                total_focused_time=float(summary_data.get("focused_time", 0.0)),
                total_distracted_time=float(summary_data.get("distracted_time", 0.0)),
                final_focus_percentage=float(summary_data.get("focus_percentage", 0.0)),
            )

    def save_telemetry_sample(
        self,
        session_id: str,
        metrics: dict[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> models.TelemetrySample:
        """Save one processed telemetry sample.

        The raw OpenCV frame is deliberately ignored; callers should pass a
        ``frame_path`` in metrics if a frame snapshot is persisted separately.
        """

        with self._session_scope() as db:
            return crud.create_telemetry_sample(
                db,
                session_id=session_id,
                timestamp=timestamp,
                posture_score=metrics.get("posture_score"),
                posture_state=metrics.get("posture_state"),
                attention_state=metrics.get("attention_state"),
                focused_time=float(metrics.get("focused_time") or 0.0),
                distracted_time=float(metrics.get("distracted_time") or 0.0),
                continuous_distraction_time=float(metrics.get("continuous_distraction_time") or 0.0),
                bad_posture_time=float(metrics.get("bad_posture_time") or 0.0),
                focus_percentage=metrics.get("focus_percentage"),
                alert_message=metrics.get("alert_message"),
                frame_path=metrics.get("frame_path"),
            )

    def get_recent_samples(self, session_id: str, *, limit: int = 60) -> list[dict[str, Any]]:
        """Retrieve the most recent samples for dashboard charts."""

        limit = max(1, min(limit, 1000))
        with self._session_scope() as db:
            samples = list(
                db.scalars(
                    select(models.TelemetrySample)
                    .where(models.TelemetrySample.session_id == session_id)
                    .order_by(desc(models.TelemetrySample.timestamp))
                    .limit(limit)
                )
            )
            return [self._sample_to_dict(sample) for sample in reversed(samples)]

    def save_sensor_reading(
        self,
        session_id: str,
        *,
        sensor_type: str,
        value: float | None,
        unit: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> models.SensorReading:
        """Persist one flexible sensor reading (HRV-proxy BPM, ambient light, ...)."""

        with self._session_scope() as db:
            return crud.create_sensor_reading(
                db,
                session_id=session_id,
                sensor_type=sensor_type,
                timestamp=timestamp,
                value=value,
                unit=unit,
                metadata_json=metadata,
            )

    def get_recent_sensor_readings(
        self,
        session_id: str,
        *,
        sensor_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Retrieve recent sensor readings for the dashboard's correlation charts."""

        limit = max(1, min(limit, 2000))
        with self._session_scope() as db:
            stmt = select(models.SensorReading).where(
                models.SensorReading.session_id == session_id
            )
            if sensor_type:
                stmt = stmt.where(models.SensorReading.sensor_type == sensor_type)
            stmt = stmt.order_by(desc(models.SensorReading.timestamp)).limit(limit)
            readings = list(db.scalars(stmt))
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "sensor_type": r.sensor_type,
                    "value": r.value,
                    "unit": r.unit,
                    "metadata": r.metadata_json,
                }
                for r in reversed(readings)
            ]

    def get_session_history(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve recent monitoring sessions for history views."""

        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        with self._session_scope() as db:
            sessions = list(
                db.scalars(
                    select(models.Session)
                    .order_by(desc(models.Session.started_at))
                    .offset(offset)
                    .limit(limit)
                )
            )
            return [self._session_to_dict(session) for session in sessions]

    def calculate_session_summary(self, session_id: str) -> SessionSummary:
        """Calculate a session summary from its saved telemetry samples."""

        with self._session_scope() as db:
            session = crud.get_session(db, session_id)
            if session is None:
                raise ValueError(f"Session not found: {session_id}")

            latest_sample = db.scalar(
                select(models.TelemetrySample)
                .where(models.TelemetrySample.session_id == session_id)
                .order_by(desc(models.TelemetrySample.timestamp))
                .limit(1)
            )
            sample_count = db.scalar(
                select(func.count(models.TelemetrySample.id)).where(
                    models.TelemetrySample.session_id == session_id
                )
            ) or 0

            focused_time = latest_sample.focused_time if latest_sample else session.total_focused_time
            distracted_time = latest_sample.distracted_time if latest_sample else session.total_distracted_time
            total_time = focused_time + distracted_time
            focus_percentage = (
                latest_sample.focus_percentage
                if latest_sample and latest_sample.focus_percentage is not None
                else (focused_time / total_time * 100 if total_time else 0.0)
            )

            return SessionSummary(
                session_id=session.session_id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                focused_time=float(focused_time or 0.0),
                distracted_time=float(distracted_time or 0.0),
                focus_percentage=float(focus_percentage or 0.0),
                sample_count=int(sample_count),
                bad_posture_time=float(latest_sample.bad_posture_time if latest_sample else 0.0),
                continuous_distraction_time=float(
                    latest_sample.continuous_distraction_time if latest_sample else 0.0
                ),
                latest_attention_state=latest_sample.attention_state if latest_sample else None,
                latest_posture_state=latest_sample.posture_state if latest_sample else None,
            )

    @staticmethod
    def generate_session_id() -> str:
        return uuid4().hex

    def _session_scope(self):
        if self._external_db is not None:
            return _ExistingSessionScope(self._external_db)
        return _ManagedSessionScope()

    @staticmethod
    def _sample_to_dict(sample: models.TelemetrySample) -> dict[str, Any]:
        return {
            "id": sample.id,
            "session_id": sample.session_id,
            "timestamp": sample.timestamp,
            "posture_score": sample.posture_score,
            "posture_state": sample.posture_state,
            "attention_state": sample.attention_state,
            "focused_time": sample.focused_time,
            "distracted_time": sample.distracted_time,
            "continuous_distraction_time": sample.continuous_distraction_time,
            "bad_posture_time": sample.bad_posture_time,
            "focus_percentage": sample.focus_percentage,
            "alert_message": sample.alert_message,
            "frame_path": sample.frame_path,
        }

    @staticmethod
    def _session_to_dict(session: models.Session) -> dict[str, Any]:
        return {
            "id": session.id,
            "session_id": session.session_id,
            "user_id": session.user_id,
            "device_id": session.device_id,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "total_focused_time": session.total_focused_time,
            "total_distracted_time": session.total_distracted_time,
            "final_focus_percentage": session.final_focus_percentage,
        }


class _ManagedSessionScope:
    def __enter__(self) -> SQLAlchemySession:
        self.db = SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None:
            self.db.rollback()
        self.db.close()


class _ExistingSessionScope:
    def __init__(self, db: SQLAlchemySession):
        self.db = db

    def __enter__(self) -> SQLAlchemySession:
        return self.db

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None:
            self.db.rollback()
