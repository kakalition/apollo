"""Typed domain commands produced by the Triage agent.

The Triage specialist turns unstructured text into one of these. Commands are
pure data — repositories apply them — so they are safe to log and replay.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apollo.domain.models import (
    CheckInKind,
    Direction,
    ProjectStatus,
    ReviewCadence,
    TaskStatus,
)


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureTask(_Command):
    kind: Literal["capture_task"] = "capture_task"
    title: str
    notes: str | None = None
    due_at: datetime | None = None
    priority: int = 3
    project_id: int | None = None
    goal_id: int | None = None
    practice_id: int | None = None


class CaptureTasks(_Command):
    kind: Literal["capture_tasks"] = "capture_tasks"
    tasks: list[CaptureTask] = Field(default_factory=list)


class LogCheckIn(_Command):
    kind: Literal["log_checkin"] = "log_checkin"
    checkin_kind: CheckInKind
    ref_id: int | None = None
    value_num: float | None = None
    value_text: str | None = None
    note: str | None = None
    occurred_at: datetime | None = None
    triggers: list[str] = Field(default_factory=list)
    friction: str | None = None
    mood: int | None = None
    wins: list[str] = Field(default_factory=list)


class CreateGoal(_Command):
    kind: Literal["create_goal"] = "create_goal"
    title: str
    outcome: str | None = None
    area_id: int | None = None
    success_criteria: str | None = None
    horizon_end: datetime | None = None


class CreatePractice(_Command):
    kind: Literal["create_practice"] = "create_practice"
    name: str
    goal_id: int | None = None
    description: str | None = None
    cadence: str | None = None
    review_cadence: ReviewCadence | None = None


class CreateProject(_Command):
    kind: Literal["create_project"] = "create_project"
    title: str
    goal_id: int | None = None
    practice_id: int | None = None
    done_when: str | None = None
    due_at: datetime | None = None


class CreateHabit(_Command):
    kind: Literal["create_habit"] = "create_habit"
    practice_id: int
    name: str
    rrule: str
    target_per_period: int = 1


class LogMetric(_Command):
    kind: Literal["log_metric"] = "log_metric"
    metric_id: int | None = None
    name: str | None = None
    unit: str | None = None
    target: float | None = None
    direction: Direction = Direction.INCREASE
    value: float
    occurred_at: datetime | None = None


class UpdateGoal(_Command):
    kind: Literal["update_goal"] = "update_goal"
    goal_id: int
    title: str | None = None
    outcome: str | None = None
    success_criteria: str | None = None
    priority: int | None = None


class CompleteTask(_Command):
    kind: Literal["complete_task"] = "complete_task"
    task_id: int
    status: TaskStatus = TaskStatus.DONE


class UpdateProject(_Command):
    kind: Literal["update_project"] = "update_project"
    project_id: int
    status: ProjectStatus | None = None
    done_when: str | None = None


class CaptureNote(_Command):
    kind: Literal["capture_note"] = "capture_note"
    body: str
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None


class CompleteReview(_Command):
    kind: Literal["complete_review"] = "complete_review"
    review_id: int | None = None
    cadence: ReviewCadence | None = None
    summary: str | None = None
    insights: str | None = None
    adjustments: dict[str, Any] = Field(default_factory=dict)


class AskQuestion(_Command):
    kind: Literal["ask_question"] = "ask_question"
    question: str
    context: str | None = None


Command = Annotated[
    CaptureTask
    | CaptureTasks
    | LogCheckIn
    | CreateGoal
    | CreatePractice
    | CreateProject
    | CreateHabit
    | LogMetric
    | UpdateGoal
    | CompleteTask
    | UpdateProject
    | CaptureNote
    | CompleteReview
    | AskQuestion,
    Field(discriminator="kind"),
]


class CommandBatch(BaseModel):
    """Triage output: zero or more commands plus an optional clarifying question."""

    commands: list[Command] = Field(default_factory=list)
    reply: str | None = None
