"""CRUD helpers for database-backed monitoring data."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as SQLAlchemySession

from src.db import models


def create_session(
    db: SQLAlchemySession,
    *,
    session_id: str,
    user_id: str | None = None,
    device_id: str | None = None,
    started_at: datetime | None = None,
) -> models.Session:
    """Create and persist a monitoring session."""

    session = models.Session(
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        started_at=started_at or datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: SQLAlchemySession, session_id: str) -> models.Session | None:
    """Return a session by its external session identifier."""

    return db.scalar(select(models.Session).where(models.Session.session_id == session_id))


def end_session(
    db: SQLAlchemySession,
    *,
    session_id: str,
    total_focused_time: float,
    total_distracted_time: float,
    final_focus_percentage: float,
    ended_at: datetime | None = None,
) -> models.Session | None:
    """Mark a monitoring session as ended and store aggregate totals."""

    session = get_session(db, session_id)
    if session is None:
        return None

    session.ended_at = ended_at or datetime.utcnow()
    session.total_focused_time = total_focused_time
    session.total_distracted_time = total_distracted_time
    session.final_focus_percentage = final_focus_percentage
    db.commit()
    db.refresh(session)
    return session


def create_telemetry_sample(
    db: SQLAlchemySession,
    *,
    session_id: str,
    timestamp: datetime | None = None,
    posture_score: float | None = None,
    posture_state: str | None = None,
    attention_state: str | None = None,
    focused_time: float = 0.0,
    distracted_time: float = 0.0,
    continuous_distraction_time: float = 0.0,
    bad_posture_time: float = 0.0,
    focus_percentage: float | None = None,
    alert_message: str | None = None,
    frame_path: str | None = None,
) -> models.TelemetrySample:
    """Create and persist one telemetry sample."""

    sample = models.TelemetrySample(
        session_id=session_id,
        timestamp=timestamp or datetime.utcnow(),
        posture_score=posture_score,
        posture_state=posture_state,
        attention_state=attention_state,
        focused_time=focused_time,
        distracted_time=distracted_time,
        continuous_distraction_time=continuous_distraction_time,
        bad_posture_time=bad_posture_time,
        focus_percentage=focus_percentage,
        alert_message=alert_message,
        frame_path=frame_path,
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


def list_telemetry_samples(
    db: SQLAlchemySession,
    session_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[models.TelemetrySample]:
    """Return telemetry samples for a session ordered by timestamp."""

    return list(
        db.scalars(
            select(models.TelemetrySample)
            .where(models.TelemetrySample.session_id == session_id)
            .order_by(models.TelemetrySample.timestamp)
            .offset(offset)
            .limit(limit)
        )
    )


def create_sensor_reading(
    db: SQLAlchemySession,
    *,
    session_id: str,
    sensor_type: str,
    timestamp: datetime | None = None,
    value: float | None = None,
    unit: str | None = None,
    metadata_json: dict[str, Any] | list[Any] | str | int | float | bool | None = None,
) -> models.SensorReading:
    """Create and persist a flexible sensor reading."""

    reading = models.SensorReading(
        session_id=session_id,
        timestamp=timestamp or datetime.utcnow(),
        sensor_type=sensor_type,
        value=value,
        unit=unit,
        metadata_json=metadata_json,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading
