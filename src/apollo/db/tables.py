"""SQLAlchemy 2.0 typed tables.

Domain tables mirror :mod:`apollo.domain.models`; the infrastructure tables
(``events``, ``jobs``, ``pending_actions``, ``notifications``, ``audit_log``,
``schedule_rules``, ``run_logs``) implement the transactional outbox, the job
queue, approvals and observability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apollo.db.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UTCDateTime,
        dict[str, Any]: JSON,
        list[str]: JSON,
        list[int]: JSON,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------
class Area(Base, TimestampMixin):
    __tablename__ = "areas"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Goal(Base, TimestampMixin):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    outcome: Mapped[str | None] = mapped_column(Text, default=None)
    horizon_start: Mapped[datetime | None] = mapped_column(default=None)
    horizon_end: Mapped[datetime | None] = mapped_column(default=None)
    success_criteria: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default="active")
    priority: Mapped[int] = mapped_column(Integer, default=3)


class Practice(Base, TimestampMixin):
    __tablename__ = "practices"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    cadence: Mapped[str | None] = mapped_column(String(200), default=None)
    policy: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default="active")
    review_cadence: Mapped[str | None] = mapped_column(String(32), default=None)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    practice_id: Mapped[int | None] = mapped_column(
        ForeignKey("practices.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300))
    done_when: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default="planned")
    due_at: Mapped[datetime | None] = mapped_column(default=None)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    practice_id: Mapped[int | None] = mapped_column(
        ForeignKey("practices.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(400))
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default="todo")
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    energy: Mapped[str | None] = mapped_column(String(32), default=None)
    est_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)

    __table_args__ = (Index("ix_tasks_status_due", "status", "due_at"),)


class Habit(Base, TimestampMixin):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(primary_key=True)
    practice_id: Mapped[int] = mapped_column(ForeignKey("practices.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    rrule: Mapped[str] = mapped_column(String(400))
    target_per_period: Mapped[int] = mapped_column(Integer, default=1)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_done_at: Mapped[datetime | None] = mapped_column(default=None)


class Metric(Base, TimestampMixin):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(64), default=None)
    target: Mapped[float | None] = mapped_column(default=None)
    direction: Mapped[str] = mapped_column(String(32), default="increase")
    cadence: Mapped[str | None] = mapped_column(String(64), default=None)


class CheckIn(Base):
    __tablename__ = "check_ins"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(Integer, default=None)
    value_num: Mapped[float | None] = mapped_column(default=None)
    value_text: Mapped[str | None] = mapped_column(Text, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    source: Mapped[str] = mapped_column(String(64), default="telegram")
    triggers: Mapped[list[str]] = mapped_column(JSON, default=list)
    friction: Mapped[str | None] = mapped_column(Text, default=None)
    mood: Mapped[int | None] = mapped_column(Integer, default=None)
    wins: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_checkins_kind_ref", "kind", "ref_id", "occurred_at"),)


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    cadence: Mapped[str] = mapped_column(String(32))
    period_start: Mapped[datetime]
    period_end: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(32), default="pending")
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    insights: Mapped[str | None] = mapped_column(Text, default=None)
    adjustments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)

    __table_args__ = (UniqueConstraint("cadence", "period_start", name="uq_review_period"),)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    title: Mapped[str | None] = mapped_column(String(300), default=None)
    body_path: Mapped[str] = mapped_column(String(500), unique=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(200), unique=True)
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    topic_id: Mapped[int | None] = mapped_column(Integer, default=None)


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_events_unprocessed", "processed_at", "id"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    lease_until: Mapped[datetime | None] = mapped_column(default=None)
    worker_id: Mapped[str | None] = mapped_column(String(128), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_jobs_claim", "status", "run_after", "priority", "id"),)


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(128), default=None)
    kind: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(String(128), default=None)

    __table_args__ = (Index("ix_pending_status", "status", "created_at"),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    ref_id: Mapped[str | None] = mapped_column(String(128), default=None)
    period: Mapped[str | None] = mapped_column(String(64), default=None)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_for: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("kind", "ref_id", "period", name="uq_notification_idempotency"),
        Index("ix_notifications_pending", "status", "scheduled_for"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str | None] = mapped_column(String(64), default=None)
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    run_id: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    trigger_type: Mapped[str] = mapped_column(String(32))
    cron: Mapped[str | None] = mapped_column(String(128), default=None)
    event_type: Mapped[str | None] = mapped_column(String(64), default=None)
    predicate: Mapped[str | None] = mapped_column(String(200), default=None)
    action: Mapped[str] = mapped_column(String(32), default="skill")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_policy: Mapped[str] = mapped_column(String(32), default="buffer")
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    agent: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str | None] = mapped_column(String(32), default=None)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    input_text: Mapped[str | None] = mapped_column(Text, default=None)
    output_text: Mapped[str | None] = mapped_column(Text, default=None)
    tool_calls: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cost_usd: Mapped[float | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Setting(Base):
    """Simple key/value store for runtime flags (pause switch, topics, pins)."""

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
