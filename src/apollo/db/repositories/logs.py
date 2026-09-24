"""Repositories for logged evidence: CheckIn, Review, JournalEntry.

This is where the feedback loop closes: habits and metrics produce check-ins,
check-ins feed reviews, and reviews feed memory.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories.base import audit, emit, to_model, utcnow
from apollo.domain import models as m
from apollo.domain.events import EventType


# ---------------------------------------------------------------------------
# CheckIn
# ---------------------------------------------------------------------------
def log_checkin(session: Session, checkin: m.CheckIn, *, actor: str = "system") -> m.CheckIn:
    row = t.CheckIn(**checkin.model_dump(exclude={"id", "created_at"}))
    session.add(row)
    session.flush()
    result = to_model(m.CheckIn, row)
    emit(
        session,
        EventType.CHECKIN_LOGGED,
        {"id": row.id, "kind": row.kind, "ref_id": row.ref_id, "occurred_at": row.occurred_at},
    )
    return result


def get_checkin(session: Session, checkin_id: int) -> m.CheckIn | None:
    row = session.get(t.CheckIn, checkin_id)
    return to_model(m.CheckIn, row) if row else None


def list_checkins(
    session: Session,
    *,
    kind: m.CheckInKind | None = None,
    ref_id: int | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[m.CheckIn]:
    stmt = select(t.CheckIn)
    if kind is not None:
        stmt = stmt.where(t.CheckIn.kind == kind.value)
    if ref_id is not None:
        stmt = stmt.where(t.CheckIn.ref_id == ref_id)
    if since is not None:
        stmt = stmt.where(t.CheckIn.occurred_at >= since)
    stmt = stmt.order_by(t.CheckIn.occurred_at.desc()).limit(limit)
    return [to_model(m.CheckIn, row) for row in session.execute(stmt).scalars()]


def last_checkin_in(session: Session, kind: m.CheckInKind) -> m.CheckIn | None:
    stmt = (
        select(t.CheckIn)
        .where(t.CheckIn.kind == kind.value)
        .order_by(t.CheckIn.occurred_at.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    return to_model(m.CheckIn, row) if row else None


# ---------------------------------------------------------------------------
# Habits (logging updates streaks)
# ---------------------------------------------------------------------------
def _rrule_is_daily(rrule: str) -> bool:
    return "FREQ=DAILY" in rrule.upper() or rrule.strip() == ""


def _streak_after(habit: m.Habit, now: datetime) -> int:
    if habit.last_done_at is None:
        return 1
    last_date = habit.last_done_at.date()
    gap = (now.date() - last_date).days
    if gap <= 0:
        return habit.current_streak or 1
    if _rrule_is_daily(habit.rrule):
        return habit.current_streak + 1 if gap == 1 else 1
    # Non-daily cadences tolerate gaps without breaking the streak.
    return habit.current_streak + 1


def log_habit(
    session: Session,
    habit_id: int,
    *,
    occurred_at: datetime | None = None,
    note: str | None = None,
    source: str = "telegram",
) -> tuple[m.Habit, m.CheckIn]:
    row = session.get(t.Habit, habit_id)
    if row is None:
        raise KeyError(f"habit {habit_id} not found")
    now = occurred_at or utcnow()
    streak = _streak_after(to_model(m.Habit, row), now)
    row.current_streak = streak
    row.best_streak = max(row.best_streak or 0, streak)
    row.last_done_at = now
    row.updated_at = utcnow()
    session.flush()
    checkin = log_checkin(
        session,
        m.CheckIn(
            kind=m.CheckInKind.HABIT,
            ref_id=habit_id,
            note=note,
            occurred_at=now,
            source=source,
        ),
    )
    emit(
        session,
        EventType.HABIT_LOGGED,
        {"id": habit_id, "name": row.name, "streak": streak, "occurred_at": now},
    )
    return to_model(m.Habit, row), checkin


def habit_streak_broken(session: Session, habit_id: int, now: datetime) -> bool:
    row = session.get(t.Habit, habit_id)
    if row is None or row.last_done_at is None:
        return False
    if not _rrule_is_daily(row.rrule):
        return False
    return (now.date() - row.last_done_at.date()).days > 1


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def record_metric(
    session: Session,
    metric_id: int,
    value: float,
    *,
    occurred_at: datetime | None = None,
    note: str | None = None,
    source: str = "telegram",
) -> tuple[m.Metric, m.CheckIn, bool]:
    row = session.get(t.Metric, metric_id)
    if row is None:
        raise KeyError(f"metric {metric_id} not found")
    now = occurred_at or utcnow()
    checkin = log_checkin(
        session,
        m.CheckIn(
            kind=m.CheckInKind.METRIC,
            ref_id=metric_id,
            value_num=value,
            note=note,
            occurred_at=now,
            source=source,
        ),
    )
    emit(session, EventType.METRIC_RECORDED, {"id": metric_id, "value": value, "occurred_at": now})
    below = _below_target(to_model(m.Metric, row), value)
    if below:
        emit(
            session,
            EventType.METRIC_BELOW_TARGET,
            {"id": metric_id, "name": row.name, "value": value, "target": row.target},
        )
    return to_model(m.Metric, row), checkin, below


def _below_target(metric: m.Metric, value: float) -> bool:
    if metric.target is None:
        return False
    if metric.direction == m.Direction.INCREASE:
        return value < metric.target
    if metric.direction == m.Direction.DECREASE:
        return value > metric.target
    return False


def metric_series(session: Session, metric_id: int, *, limit: int = 30) -> list[m.CheckIn]:
    stmt = (
        select(t.CheckIn)
        .where(t.CheckIn.kind == m.CheckInKind.METRIC.value, t.CheckIn.ref_id == metric_id)
        .order_by(t.CheckIn.occurred_at.desc())
        .limit(limit)
    )
    return [to_model(m.CheckIn, row) for row in session.execute(stmt).scalars()]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
def create_review(session: Session, review: m.Review) -> m.Review:
    row = t.Review(**review.model_dump(exclude={"id", "created_at", "updated_at"}))
    session.add(row)
    session.flush()
    return to_model(m.Review, row)


def get_review(session: Session, review_id: int) -> m.Review | None:
    row = session.get(t.Review, review_id)
    return to_model(m.Review, row) if row else None


def list_reviews(session: Session, cadence: m.ReviewCadence | None = None) -> list[m.Review]:
    stmt = select(t.Review)
    if cadence is not None:
        stmt = stmt.where(t.Review.cadence == cadence.value)
    return [to_model(m.Review, row) for row in session.execute(stmt.order_by(t.Review.id)).scalars()]


def due_reviews(session: Session, now: datetime) -> list[m.Review]:
    stmt = (
        select(t.Review)
        .where(t.Review.status == m.ReviewStatus.PENDING.value)
        .where(t.Review.period_end <= now)
    )
    return [to_model(m.Review, row) for row in session.execute(stmt).scalars()]


def ensure_review(
    session: Session, cadence: m.ReviewCadence, period_start: datetime, period_end: datetime
) -> m.Review | None:
    """Get or create the pending review for a period; emits ``review.due`` if created."""
    existing = session.execute(
        select(t.Review).where(
            t.Review.cadence == cadence.value, t.Review.period_start == period_start
        )
    ).scalar_one_or_none()
    if existing is not None:
        return to_model(m.Review, existing)
    review = create_review(
        session,
        m.Review(
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            status=m.ReviewStatus.PENDING,
        ),
    )
    emit(
        session,
        EventType.REVIEW_DUE,
        {"id": review.id, "cadence": cadence.value, "period_start": period_start},
    )
    return review


def complete_review(
    session: Session,
    review_id: int,
    *,
    summary: str | None = None,
    insights: str | None = None,
    adjustments: dict | None = None,
    actor: str = "system",
) -> m.Review:
    row = session.get(t.Review, review_id)
    if row is None:
        raise KeyError(f"review {review_id} not found")
    row.status = m.ReviewStatus.COMPLETED.value
    row.summary = summary
    row.insights = insights
    row.adjustments = adjustments or {}
    row.completed_at = utcnow()
    row.updated_at = utcnow()
    session.flush()
    audit(
        session,
        actor=actor,
        action="review.complete",
        entity_type="reviews",
        entity_id=review_id,
        after={"status": row.status},
    )
    emit(session, EventType.REVIEW_COMPLETED, {"id": review_id, "cadence": row.cadence})
    return to_model(m.Review, row)


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------
def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def upsert_journal_entry(
    session: Session, entry: m.JournalEntry, *, body_hash: str
) -> tuple[m.JournalEntry, bool, bool]:
    """Insert or update journal metadata by ``body_path``.

    Returns ``(entry, changed, created)``.
    """
    row = session.execute(
        select(t.JournalEntry).where(t.JournalEntry.body_path == entry.body_path)
    ).scalar_one_or_none()
    if row is None:
        row = t.JournalEntry(
            occurred_at=entry.occurred_at,
            title=entry.title,
            body_path=entry.body_path,
            tags=entry.tags,
            content_hash=body_hash,
        )
        session.add(row)
        session.flush()
        emit(session, EventType.JOURNAL_CAPTURED, {"id": row.id, "path": row.body_path, "title": row.title})
        return to_model(m.JournalEntry, row), True, True
    changed = row.content_hash != body_hash
    if changed:
        row.occurred_at = entry.occurred_at
        row.title = entry.title
        row.tags = entry.tags
        row.content_hash = body_hash
        row.updated_at = utcnow()
        session.flush()
        emit(session, EventType.JOURNAL_CAPTURED, {"id": row.id, "path": row.body_path, "title": row.title})
    return to_model(m.JournalEntry, row), changed, False


def list_journal(session: Session, limit: int = 50) -> list[m.JournalEntry]:
    stmt = select(t.JournalEntry).order_by(t.JournalEntry.occurred_at.desc()).limit(limit)
    return [to_model(m.JournalEntry, row) for row in session.execute(stmt).scalars()]


def recent_window(session: Session, now: datetime, days: int) -> dict[str, int]:
    """Counts used by reviews and drift predicates."""
    since = now - timedelta(days=days)
    checkins = list_checkins(session, since=since, limit=1000)
    return {
        "checkins": len(checkins),
        "habits": sum(1 for c in checkins if c.kind == m.CheckInKind.HABIT),
        "metrics": sum(1 for c in checkins if c.kind == m.CheckInKind.METRIC),
        "reflections": sum(1 for c in checkins if c.kind == m.CheckInKind.REFLECTION),
    }
