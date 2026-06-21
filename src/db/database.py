"""Database configuration for the posture monitoring application.

The MVP uses SQLite via SQLAlchemy. Keeping the rest of the application behind
SQLAlchemy's engine/session abstractions makes it straightforward to move to
PostgreSQL or TimescaleDB later by changing the database URL.
"""

from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session as SQLAlchemySession, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/posture_monitoring.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def get_db() -> Generator[SQLAlchemySession, None, None]:
    """Yield a database session and ensure it is closed after use."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all configured tables.

    Importing models here ensures SQLAlchemy has registered their metadata
    before table creation is attempted. For local SQLite databases, the parent
    directory is created automatically so first-run startup succeeds.
    """

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.removeprefix("sqlite:///")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    from src.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
