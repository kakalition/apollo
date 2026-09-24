"""Repositories for the planning aggregates: Area, Goal, Practice, Project,
Task, Habit, Metric.

All functions expect to run inside a write session (see ``Database.write``); they
mutate the row, write an ``audit_log`` entry, and append the matching outbox event
in the *same* transaction.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories.base import audit, emit, to_model, utcnow
from apollo.domain import models as m
from apollo.domain.events import EventType


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dump(model: m.Base) -> dict[str, Any]:
    return model.model_dump(exclude={"id", "created_at", "updated_at"})


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _create(
    session: Session, table_cls: Any, model: m.Base, event_type: EventType | None
) -> Any:
    row = table_cls(**_dump(model))
    session.add(row)
    session.flush()
    result = to_model(type(model), row)
    if event_type is not None:
        emit(
            session,
            event_type,
            {"id": row.id, "title": getattr(row, "title", None) or getattr(row, "name", None)},
        )
    return result


def _update(
    session: Session,
    *,
    table_cls: Any,
    model_cls: type[m.Base],
    entity_id: int,
    changes: dict[str, Any],
    event_type: EventType,
    action: str,
    actor: str = "system",
    run_id: str | None = None,
) -> Any:
    row = session.get(table_cls, entity_id)
    if row is None:
        raise KeyError(f"{table_cls.__tablename__} {entity_id} not found")
    before = to_model(model_cls, row).model_dump(mode="json")
    for key, value in changes.items():
        if value is not None:
            setattr(row, key, _value(value))
    row.updated_at = utcnow()
    session.flush()
    after = to_model(model_cls, row).model_dump(mode="json")
    audit(
        session,
        actor=actor,
        action=action,
        entity_type=table_cls.__tablename__,
        entity_id=entity_id,
        before={k: before[k] for k in changes if k in before},
        after={k: after[k] for k in changes if k in after},
        run_id=run_id,
    )
    emit(session, event_type, {"id": entity_id, "changed": list(changes)})
    return to_model(model_cls, row)


def _list(session: Session, table_cls: Any, model_cls: type[m.Base], **filters: Any) -> list[Any]:
    stmt = select(table_cls)
    for key, value in filters.items():
        if value is not None:
            stmt = stmt.where(getattr(table_cls, key) == _value(value))
    stmt = stmt.order_by(table_cls.id)
    return [to_model(model_cls, row) for row in session.execute(stmt).scalars()]


def _get(session: Session, table_cls: Any, model_cls: type[m.Base], entity_id: int) -> Any:
    row = session.get(table_cls, entity_id)
    return to_model(model_cls, row) if row is not None else None


# ---------------------------------------------------------------------------
# Area
# ---------------------------------------------------------------------------
def create_area(session: Session, area: m.Area) -> m.Area:
    return _create(session, t.Area, area, None)


def update_area(session: Session, area_id: int, **changes: Any) -> m.Area:
    return _update(
        session,
        table_cls=t.Area,
        model_cls=m.Area,
        entity_id=area_id,
        changes=changes,
        event_type=EventType.GOAL_UPDATED,
        action="area.update",
    )


def list_areas(session: Session, archived: bool | None = None) -> list[m.Area]:
    return _list(session, t.Area, m.Area, archived=archived)


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------
def create_goal(session: Session, goal: m.Goal, *, actor: str = "system") -> m.Goal:
    return _create(session, t.Goal, goal, EventType.GOAL_CREATED)


def update_goal(
    session: Session, goal_id: int, *, actor: str = "system", run_id: str | None = None, **changes: Any
) -> m.Goal:
    event = EventType.GOAL_UPDATED
    if _value(changes.get("status")) == m.GoalStatus.ACHIEVED.value:
        event = EventType.GOAL_ACHIEVED
    return _update(
        session,
        table_cls=t.Goal,
        model_cls=m.Goal,
        entity_id=goal_id,
        changes=changes,
        event_type=event,
        action="goal.update",
        actor=actor,
        run_id=run_id,
    )


def get_goal(session: Session, goal_id: int) -> m.Goal | None:
    return _get(session, t.Goal, m.Goal, goal_id)


def list_goals(session: Session, status: m.GoalStatus | None = None, area_id: int | None = None) -> list[m.Goal]:
    return _list(session, t.Goal, m.Goal, status=status, area_id=area_id)


# ---------------------------------------------------------------------------
# Practice
# ---------------------------------------------------------------------------
def create_practice(session: Session, practice: m.Practice) -> m.Practice:
    return _create(session, t.Practice, practice, EventType.PRACTICE_CREATED)


def update_practice(session: Session, practice_id: int, **changes: Any) -> m.Practice:
    return _update(
        session,
        table_cls=t.Practice,
        model_cls=m.Practice,
        entity_id=practice_id,
        changes=changes,
        event_type=EventType.PRACTICE_UPDATED,
        action="practice.update",
    )


def get_practice(session: Session, practice_id: int) -> m.Practice | None:
    return _get(session, t.Practice, m.Practice, practice_id)


def list_practices(session: Session, goal_id: int | None = None, status: m.PracticeStatus | None = None) -> list[m.Practice]:
    return _list(session, t.Practice, m.Practice, goal_id=goal_id, status=status)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def create_project(session: Session, project: m.Project) -> m.Project:
    return _create(session, t.Project, project, EventType.PROJECT_CREATED)


def update_project(session: Session, project_id: int, **changes: Any) -> m.Project:
    return _update(
        session,
        table_cls=t.Project,
        model_cls=m.Project,
        entity_id=project_id,
        changes=changes,
        event_type=EventType.PROJECT_UPDATED,
        action="project.update",
    )


def get_project(session: Session, project_id: int) -> m.Project | None:
    return _get(session, t.Project, m.Project, project_id)


def list_projects(session: Session, goal_id: int | None = None, status: m.ProjectStatus | None = None) -> list[m.Project]:
    return _list(session, t.Project, m.Project, goal_id=goal_id, status=status)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
def create_task(session: Session, task: m.Task, *, actor: str = "system") -> m.Task:
    return _create(session, t.Task, task, EventType.TASK_CREATED)


def update_task(session: Session, task_id: int, **changes: Any) -> m.Task:
    return _update(
        session,
        table_cls=t.Task,
        model_cls=m.Task,
        entity_id=task_id,
        changes=changes,
        event_type=EventType.TASK_UPDATED,
        action="task.update",
    )


def complete_task(session: Session, task_id: int, *, actor: str = "system", run_id: str | None = None) -> m.Task:
    row = session.get(t.Task, task_id)
    if row is None:
        raise KeyError(f"task {task_id} not found")
    row.status = m.TaskStatus.DONE.value
    row.completed_at = utcnow()
    row.updated_at = utcnow()
    session.flush()
    audit(
        session,
        actor=actor,
        action="task.complete",
        entity_type="tasks",
        entity_id=task_id,
        after={"status": row.status, "completed_at": _iso(row.completed_at)},
        run_id=run_id,
    )
    emit(session, EventType.TASK_COMPLETED, {"id": task_id, "title": row.title})
    return to_model(m.Task, row)


def get_task(session: Session, task_id: int) -> m.Task | None:
    return _get(session, t.Task, m.Task, task_id)


def list_tasks(
    session: Session,
    *,
    status: m.TaskStatus | None = None,
    project_id: int | None = None,
    goal_id: int | None = None,
    practice_id: int | None = None,
) -> list[m.Task]:
    return _list(
        session,
        t.Task,
        m.Task,
        status=status,
        project_id=project_id,
        goal_id=goal_id,
        practice_id=practice_id,
    )


def overdue_tasks(session: Session, now: datetime) -> list[m.Task]:
    stmt = (
        select(t.Task)
        .where(t.Task.status.in_([m.TaskStatus.TODO.value, m.TaskStatus.DOING.value]))
        .where(t.Task.due_at.is_not(None))
        .where(t.Task.due_at < now)
        .order_by(t.Task.due_at)
    )
    return [to_model(m.Task, row) for row in session.execute(stmt).scalars()]


def mark_overdue(session: Session, now: datetime) -> list[int]:
    ids: list[int] = []
    for task in overdue_tasks(session, now):
        assert task.id is not None
        ids.append(task.id)
        emit(session, EventType.TASK_OVERDUE, {"id": task.id, "title": task.title, "due_at": task.due_at})
    return ids


# ---------------------------------------------------------------------------
# Habit
# ---------------------------------------------------------------------------
def create_habit(session: Session, habit: m.Habit) -> m.Habit:
    return _create(session, t.Habit, habit, EventType.HABIT_CREATED)


def update_habit(session: Session, habit_id: int, **changes: Any) -> m.Habit:
    return _update(
        session,
        table_cls=t.Habit,
        model_cls=m.Habit,
        entity_id=habit_id,
        changes=changes,
        event_type=EventType.PRACTICE_UPDATED,
        action="habit.update",
    )


def get_habit(session: Session, habit_id: int) -> m.Habit | None:
    return _get(session, t.Habit, m.Habit, habit_id)


def list_habits(session: Session, practice_id: int | None = None) -> list[m.Habit]:
    return _list(session, t.Habit, m.Habit, practice_id=practice_id)


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------
def create_metric(session: Session, metric: m.Metric) -> m.Metric:
    return _create(session, t.Metric, metric, EventType.METRIC_CREATED)


def update_metric(session: Session, metric_id: int, **changes: Any) -> m.Metric:
    return _update(
        session,
        table_cls=t.Metric,
        model_cls=m.Metric,
        entity_id=metric_id,
        changes=changes,
        event_type=EventType.METRIC_CREATED,
        action="metric.update",
    )


def get_metric(session: Session, metric_id: int) -> m.Metric | None:
    return _get(session, t.Metric, m.Metric, metric_id)


def list_metrics(session: Session, goal_id: int | None = None) -> list[m.Metric]:
    return _list(session, t.Metric, m.Metric, goal_id=goal_id)
