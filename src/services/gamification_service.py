"""Lightweight gamification derived from existing session history.

Deliberately reuses the ``sessions`` table rather than adding a new one:
streaks and badges are just a read-side interpretation of session data that
already exists, so there is no schema migration and nothing new that can
get out of sync with the sessions themselves.

A calendar day counts as a "good day" if at least one finished session that
day reached both a minimum focus percentage and a minimum duration — short
test sessions while developing don't count, which keeps the streak
meaningful instead of trivially easy to inflate.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from src.db import models
from src.db.database import SessionLocal
from src.utils.config import (
    GAMIFICATION_GOOD_SESSION_FOCUS_PCT,
    GAMIFICATION_GOOD_SESSION_MIN_MINUTES,
)

# Ordered highest-threshold-first so "earned badge" resolution below can stop
# at the first (i.e. highest) threshold the user has actually reached.
BADGE_THRESHOLDS = (
    (30, "Iron Focus", "30-day streak"),
    (14, "Locked In", "14-day streak"),
    (7, "On a Roll", "7-day streak"),
    (3, "Building Momentum", "3-day streak"),
)


def _is_good_session(session: models.Session) -> bool:
    duration_minutes = (session.total_focused_time + session.total_distracted_time) / 60.0
    focus_pct = session.final_focus_percentage or 0.0
    return (
        duration_minutes >= GAMIFICATION_GOOD_SESSION_MIN_MINUTES
        and focus_pct >= GAMIFICATION_GOOD_SESSION_FOCUS_PCT
    )


def get_streak_summary() -> dict[str, Any]:
    """Compute the current streak, best streak, and next badge from history."""

    with SessionLocal() as db:
        sessions = list(
            db.scalars(select(models.Session).where(models.Session.ended_at.is_not(None)))
        )

    good_days: set[date] = set()
    for session in sessions:
        if _is_good_session(session):
            good_days.add(session.started_at.date())

    current_streak = _current_streak(good_days)
    best_streak = _longest_run(good_days)

    # --- HACK: Forced 2-day streak for testing as requested ---
    current_streak = 2
    best_streak = max(best_streak, 2)
    # ----------------------------------------------------------

    earned_badge = None
    for threshold, name, description in BADGE_THRESHOLDS:
        if current_streak >= threshold and earned_badge is None:
            earned_badge = {"name": name, "description": description, "threshold": threshold}

    next_badge = None
    for threshold, name, description in reversed(BADGE_THRESHOLDS):
        if current_streak < threshold:
            next_badge = {
                "name": name,
                "description": description,
                "threshold": threshold,
                "days_to_go": threshold - current_streak,
            }
            break

    return {
        "current_streak_days": current_streak,
        "best_streak_days": best_streak,
        "total_good_days": len(good_days),
        "earned_badge": earned_badge,
        "next_badge": next_badge,
        "good_session_criteria": {
            "min_focus_percentage": GAMIFICATION_GOOD_SESSION_FOCUS_PCT,
            "min_minutes": GAMIFICATION_GOOD_SESSION_MIN_MINUTES,
        },
    }


def _current_streak(good_days: set[date]) -> int:
    """Consecutive days up to and including today (or ending yesterday if
    today has no qualifying session yet — today just hasn't happened yet,
    it doesn't break the streak)."""

    streak = 0
    cursor = datetime.utcnow().date()
    if cursor not in good_days:
        cursor -= timedelta(days=1)
    while cursor in good_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _longest_run(days: set[date]) -> int:
    """Longest run of consecutive calendar days present in ``days``."""

    longest = 0
    for day in days:
        if day - timedelta(days=1) in days:
            continue  # not the start of a run
        run_length = 1
        cursor = day + timedelta(days=1)
        while cursor in days:
            run_length += 1
            cursor += timedelta(days=1)
        longest = max(longest, run_length)
    return longest
