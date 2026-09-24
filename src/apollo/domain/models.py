"""Domain kernel — Pydantic models for every entity in the ontology.

Anchor rule: a **Goal** is what you want; a **Practice** is what you run to get it.
Everything else hangs off those two.

Classification test (see ``classify_entity``): wanted → Goal · practised (ongoing,
has cadence) → Practice · completable → Project · repeats (has rrule) → Habit ·
single action → Task · measures → Metric.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GoalStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class PracticeStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    DROPPED = "dropped"


class TaskStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    CANCELLED = "cancelled"


class CheckInKind(StrEnum):
    HABIT = "habit"
    METRIC = "metric"
    TASK = "task"
    REFLECTION = "reflection"


class ReviewCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class Direction(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    MAINTAIN = "maintain"


class EntityKind(StrEnum):
    AREA = "area"
    GOAL = "goal"
    PRACTICE = "practice"
    PROJECT = "project"
    HABIT = "habit"
    TASK = "task"
    METRIC = "metric"


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Area(Base):
    id: int | None = None
    name: str
    description: str | None = None
    archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Goal(Base):
    id: int | None = None
    area_id: int | None = None
    title: str
    outcome: str | None = None
    horizon_start: datetime | None = None
    horizon_end: datetime | None = None
    success_criteria: str | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    priority: int = 3
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Practice(Base):
    """A repeatable practice that produces a goal (the domain entity behind
    the product phrase "personal system")."""

    id: int | None = None
    goal_id: int | None = None
    name: str
    description: str | None = None
    cadence: str | None = None
    policy: str | None = None
    status: PracticeStatus = PracticeStatus.ACTIVE
    review_cadence: ReviewCadence | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Project(Base):
    id: int | None = None
    goal_id: int | None = None
    practice_id: int | None = None
    title: str
    done_when: str | None = None
    status: ProjectStatus = ProjectStatus.PLANNED
    due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Task(Base):
    id: int | None = None
    goal_id: int | None = None
    project_id: int | None = None
    practice_id: int | None = None
    title: str
    notes: str | None = None
    status: TaskStatus = TaskStatus.TODO
    due_at: datetime | None = None
    priority: int = 3
    energy: str | None = None
    est_minutes: int | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Habit(Base):
    id: int | None = None
    practice_id: int
    name: str
    rrule: str
    target_per_period: int = 1
    current_streak: int = 0
    best_streak: int = 0
    last_done_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Metric(Base):
    id: int | None = None
    goal_id: int | None = None
    name: str
    unit: str | None = None
    target: float | None = None
    direction: Direction = Direction.INCREASE
    cadence: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CheckIn(Base):
    id: int | None = None
    kind: CheckInKind
    ref_id: int | None = None
    value_num: float | None = None
    value_text: str | None = None
    note: str | None = None
    occurred_at: datetime
    source: str = "telegram"
    triggers: list[str] = Field(default_factory=list)
    friction: str | None = None
    mood: int | None = None
    wins: list[str] = Field(default_factory=list)


class Review(Base):
    id: int | None = None
    cadence: ReviewCadence
    period_start: datetime
    period_end: datetime
    status: ReviewStatus = ReviewStatus.PENDING
    summary: str | None = None
    insights: str | None = None
    adjustments: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None


class JournalEntry(Base):
    id: int | None = None
    occurred_at: datetime
    title: str | None = None
    body_path: str
    tags: list[str] = Field(default_factory=list)
    content_hash: str | None = None


def classify_entity(
    *,
    wanted: bool = False,
    practised: bool = False,
    completable: bool = False,
    repeats: bool = False,
    measures: bool = False,
) -> EntityKind:
    """Return the entity kind for a described intention.

    The order encodes the anchor rule: measurement and completion are the most
    specific claims, then recurrence, then ongoing practice, then desire.
    """
    if measures:
        return EntityKind.METRIC
    if repeats:
        return EntityKind.HABIT
    if completable:
        return EntityKind.PROJECT
    if practised:
        return EntityKind.PRACTICE
    if wanted:
        return EntityKind.GOAL
    return EntityKind.TASK


LifeDomain = Literal["Health", "Career", "Finance", "Relationships"]


class PendingAction(Base):
    id: int | None = None
    run_id: str | None = None
    kind: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    created_at: datetime | None = None
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None


class AuditLog(Base):
    id: int | None = None
    actor: str = "system"
    action: str
    entity_type: str | None = None
    entity_id: int | None = None
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    run_id: str | None = None
    created_at: datetime | None = None


class Notification(Base):
    id: int | None = None
    kind: str
    ref_id: str | None = None
    period: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    urgent: bool = False
    attempts: int = 0
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    error: str | None = None


class RunLog(Base):
    id: int | None = None
    run_id: str
    agent: str
    tier: str | None = None
    model: str | None = None
    input_text: str | None = None
    output_text: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    status: str = "ok"
    error: str | None = None
    created_at: datetime | None = None


class Conversation(Base):
    id: int | None = None
    conversation_id: str
    channel: str = "telegram"
    telegram_user_id: int | None = None
    topic_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
