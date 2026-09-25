"""Typed domain commands produced by the Triage agent.

The Triage specialist turns unstructured text into one of these. Commands are
pure data — repositories apply them — so they are safe to log and replay.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# LLM-controlled fields use ``str`` rather than strict enums: models sometimes emit
# near-miss values ("open" for a task status), and a validation error would fail the
# whole run. ``apollo.domain.apply`` coerces to the real enum with a safe default.


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
    checkin_kind: str  # habit | metric | task | reflection
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
    review_cadence: str | None = None


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
    direction: str = "increase"  # increase | decrease | maintain
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
    status: str = "done"


class UpdateProject(_Command):
    kind: Literal["update_project"] = "update_project"
    project_id: int
    status: str | None = None  # planned | active | blocked | done | dropped
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
    cadence: str | None = None  # daily | weekly | monthly
    summary: str | None = None
    insights: str | None = None
    adjustments: dict[str, Any] = Field(default_factory=dict)


class AskQuestion(_Command):
    kind: Literal["ask_question"] = "ask_question"
    question: str
    context: str | None = None


class SetReminder(_Command):
    """Fire a one-off notification at an absolute time."""

    kind: Literal["set_reminder"] = "set_reminder"
    at: datetime
    text: str


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
    | AskQuestion
    | SetReminder,
    Field(discriminator="kind"),
]


class CommandBatch(BaseModel):
    """Planner/Coach output: the full command union plus an optional reply."""

    commands: list[Command] = Field(default_factory=list)
    reply: str | None = None


# ---------------------------------------------------------------------------
# Slim capture schema (triage)
#
# The full Command union has ~26 variants, which is hard and slow for models to
# emit. Capture only needs four things, so triage returns this small shape; the
# domain layer converts it to real commands.
# ---------------------------------------------------------------------------
class CaptureTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["task"] = "task"
    title: str
    due_at: str | None = None
    priority: int = 3


class CaptureCheckinItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["checkin"] = "checkin"
    checkin_kind: str = "reflection"  # habit | metric | task | reflection
    ref_id: int | None = None
    value_num: float | None = None
    note: str | None = None


class CaptureMetricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["metric"] = "metric"
    value: float
    metric_id: int | None = None
    name: str | None = None
    unit: str | None = None


class CaptureNoteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["note"] = "note"
    body: str
    title: str | None = None


class CaptureReminderItem(BaseModel):
    """A one-off reminder: `at` must be an absolute ISO-8601 timestamp."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["reminder"] = "reminder"
    at: str
    text: str


CaptureItem = Annotated[
    CaptureTaskItem | CaptureCheckinItem | CaptureMetricItem | CaptureNoteItem | CaptureReminderItem,
    Field(discriminator="kind"),
]


class CaptureResult(BaseModel):
    """What Triage returns: a short list of capture items plus an optional reply."""

    items: list[CaptureItem] = Field(default_factory=list)
    reply: str | None = None


# ---------------------------------------------------------------------------
# Slim planning schema (planner)
#
# Nested rather than a flat union so no id juggling is needed: a goal owns its
# practice (with habits/metrics), projects (with tasks) and loose tasks. Much
# smaller and faster for models to emit than the full Command union.
# ---------------------------------------------------------------------------
class PlannedHabit(BaseModel):
    name: str
    rrule: str = "FREQ=DAILY"
    target_per_period: int = 1


class PlannedMetric(BaseModel):
    name: str
    unit: str | None = None
    target: float | None = None
    direction: str = "increase"  # increase | decrease | maintain


class PlannedPractice(BaseModel):
    name: str
    cadence: str | None = None
    description: str | None = None
    habits: list[PlannedHabit] = Field(default_factory=list)
    metrics: list[PlannedMetric] = Field(default_factory=list)


class PlannedTask(BaseModel):
    title: str
    due_at: str | None = None
    priority: int = 3
    notes: str | None = None


class PlannedProject(BaseModel):
    title: str
    done_when: str | None = None
    due_at: str | None = None
    tasks: list[PlannedTask] = Field(default_factory=list)


class PlannedGoal(BaseModel):
    title: str
    outcome: str | None = None
    success_criteria: str | None = None
    horizon_end: str | None = None
    practice: PlannedPractice | None = None
    projects: list[PlannedProject] = Field(default_factory=list)
    tasks: list[PlannedTask] = Field(default_factory=list)


class PlanResult(BaseModel):
    goals: list[PlannedGoal] = Field(default_factory=list)
    tasks: list[PlannedTask] = Field(default_factory=list)
    reply: str | None = None
