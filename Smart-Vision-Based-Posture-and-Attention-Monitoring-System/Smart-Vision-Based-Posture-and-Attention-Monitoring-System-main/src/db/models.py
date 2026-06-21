"""SQLAlchemy ORM models for sessions, telemetry, and sensor data."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.database import Base


class Session(Base):
    """Monitoring session summary."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    device_id: Mapped[str | None] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    total_focused_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_distracted_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    final_focus_percentage: Mapped[float | None] = mapped_column(Float)

    telemetry_samples: Mapped[list["TelemetrySample"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sensor_readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TelemetrySample(Base):
    """Per-frame or periodic posture and attention telemetry."""

    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    posture_score: Mapped[float | None] = mapped_column(Float)
    posture_state: Mapped[str | None] = mapped_column(String(64))
    attention_state: Mapped[str | None] = mapped_column(String(64))
    focused_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    distracted_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    continuous_distraction_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bad_posture_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    focus_percentage: Mapped[float | None] = mapped_column(Float)
    alert_message: Mapped[str | None] = mapped_column(Text)
    frame_path: Mapped[str | None] = mapped_column(String(512))

    session: Mapped[Session] = relationship(back_populates="telemetry_samples")


class SensorReading(Base):
    """Flexible sensor reading for future hardware or environmental inputs."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    sensor_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    metadata_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)

    session: Mapped[Session] = relationship(back_populates="sensor_readings")
