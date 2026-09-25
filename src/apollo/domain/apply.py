"""Apply typed domain commands (Triage/Planner output) to the database.

Every command is applied inside the caller's write transaction, so the mutation and
its outbox events commit together. Dispatch uses ``match`` class patterns so the
discriminated union is narrowed for both the runtime and the type checker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.domain.commands import (
    AskQuestion,
    CaptureNote,
    CaptureTask,
    CaptureTasks,
    Command,
    CompleteReview,
    CompleteTask,
    CreateGoal,
    CreateHabit,
    CreatePractice,
    CreateProject,
    LogCheckIn,
    LogMetric,
    UpdateGoal,
    UpdateProject,
)
from apollo.tools.time import parse_datetime


def _enum(value: Any, enum_cls: Any, default: Any) -> Any:
    """Coerce a model-provided string to an enum, falling back to a safe default."""
    if value is None:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


def apply_batch(
    session: Session,
    commands: list[Command],
    *,
    actor: str = "agent",
    run_id: str | None = None,
    vault: Any | None = None,
) -> list[str]:
    results: list[str] = []
    for command in commands:
        try:
            results.append(apply_command(session, command, actor=actor, run_id=run_id, vault=vault))
        except Exception as exc:
            results.append(f"failed: {exc}")
    return results


def apply_command(
    session: Session,
    command: Command,
    *,
    actor: str = "agent",
    run_id: str | None = None,
    vault: Any | None = None,
) -> str:
    match command:
        case CaptureTask():
            task = repo.create_task(
                session,
                m.Task(
                    title=command.title,
                    notes=command.notes,
                    due_at=parse_datetime(command.due_at),
                    priority=command.priority,
                    project_id=command.project_id,
                    goal_id=command.goal_id,
                    practice_id=command.practice_id,
                ),
                actor=actor,
            )
            return f"task #{task.id} {task.title}"

        case CaptureTasks():
            parts = [
                apply_command(session, sub, actor=actor, run_id=run_id, vault=vault)
                for sub in command.tasks
            ]
            return "; ".join(parts) if parts else "no tasks"

        case LogCheckIn():
            checkin = logrepo.log_checkin(
                session,
                m.CheckIn(
                    kind=_enum(command.checkin_kind, m.CheckInKind, m.CheckInKind.REFLECTION),
                    ref_id=command.ref_id,
                    value_num=command.value_num,
                    value_text=command.value_text,
                    note=command.note,
                    occurred_at=parse_datetime(command.occurred_at) or _now(),
                    source="agent",
                    triggers=command.triggers,
                    friction=command.friction,
                    mood=command.mood,
                    wins=command.wins,
                ),
                actor=actor,
            )
            return f"checkin #{checkin.id} ({command.checkin_kind})"

        case LogMetric():
            metric_id = command.metric_id
            if metric_id is None and command.name:
                metric_id = _find_or_create_metric(session, command)
            if metric_id is None:
                raise ValueError("log_metric needs metric_id or name")
            _, checkin, below = logrepo.record_metric(
                session,
                metric_id,
                command.value,
                occurred_at=parse_datetime(command.occurred_at),
                source="agent",
            )
            suffix = " (below target)" if below else ""
            return f"metric #{metric_id}={command.value}{suffix}"

        case CreateGoal():
            goal = repo.create_goal(
                session,
                m.Goal(
                    title=command.title,
                    outcome=command.outcome,
                    area_id=command.area_id,
                    success_criteria=command.success_criteria,
                    horizon_end=parse_datetime(command.horizon_end),
                ),
                actor=actor,
            )
            return f"goal #{goal.id} {goal.title}"

        case CreatePractice():
            practice = repo.create_practice(
                session,
                m.Practice(
                    name=command.name,
                    goal_id=command.goal_id,
                    description=command.description,
                    cadence=command.cadence,
                    review_cadence=_enum(command.review_cadence, m.ReviewCadence, None),
                ),
            )
            return f"practice #{practice.id} {practice.name}"

        case CreateProject():
            project = repo.create_project(
                session,
                m.Project(
                    title=command.title,
                    goal_id=command.goal_id,
                    practice_id=command.practice_id,
                    done_when=command.done_when,
                    due_at=parse_datetime(command.due_at),
                ),
            )
            return f"project #{project.id} {project.title}"

        case CreateHabit():
            habit = repo.create_habit(
                session,
                m.Habit(
                    practice_id=command.practice_id,
                    name=command.name,
                    rrule=command.rrule,
                    target_per_period=command.target_per_period,
                ),
            )
            return f"habit #{habit.id} {habit.name}"

        case UpdateGoal():
            goal = repo.update_goal(
                session,
                command.goal_id,
                actor=actor,
                run_id=run_id,
                title=command.title,
                outcome=command.outcome,
                success_criteria=command.success_criteria,
                priority=command.priority,
            )
            return f"updated goal #{goal.id}"

        case CompleteTask():
            task = repo.complete_task(session, command.task_id, actor=actor, run_id=run_id)
            return f"completed task #{task.id}"

        case UpdateProject():
            project = repo.update_project(
                session,
                command.project_id,
                status=_enum(command.status, m.ProjectStatus, None),
                done_when=command.done_when,
            )
            return f"updated project #{project.id}"

        case CompleteReview():
            review_id = command.review_id
            if review_id is None:
                pending = [
                    r for r in logrepo.list_reviews(session) if r.status == m.ReviewStatus.PENDING
                ]
                review_id = pending[-1].id if pending else None
            if review_id is None:
                return "no review to complete"
            logrepo.complete_review(
                session,
                review_id,
                summary=command.summary,
                insights=command.insights,
                adjustments=command.adjustments,
                actor=actor,
            )
            return f"completed review #{review_id}"

        case CaptureNote():
            if vault is None:
                return "note captured (vault unavailable)"
            from apollo.tools import db_tools

            result = db_tools.capture_note_to_vault(
                vault,
                session,
                body=command.body,
                title=command.title,
                tags=command.tags,
                occurred_at=parse_datetime(command.occurred_at),
            )
            return f"note {result.get('path')}"

        case AskQuestion():
            return f"question: {command.question}"

        case _:  # pragma: no cover - exhaustive by construction
            raise ValueError(f"unknown command {command!r}")


def _find_or_create_metric(session: Session, command: Any) -> int:
    row = session.execute(
        select(t.Metric).where(t.Metric.name == command.name)
    ).scalar_one_or_none()
    if row is None:
        metric = repo.create_metric(
            session,
            m.Metric(
                name=command.name,
                unit=command.unit,
                target=command.target,
                direction=_enum(command.direction, m.Direction, m.Direction.INCREASE),
            ),
        )
        return int(metric.id or 0)
    return int(row.id)


def _now() -> datetime:
    return datetime.now(UTC)
