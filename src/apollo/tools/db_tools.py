"""Read/write helpers shared by the MCP server and agent tools.

Writes go through the repositories (audit + outbox events). Approval gating is a
*policy* concern applied by the caller (MCP server / agent tool layer), not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.db.repositories.base import to_model
from apollo.domain import models as m
from apollo.tools.clock import Clock
from apollo.tools.time import day_window, is_due, week_window


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_context(session: Session, clock: Clock) -> dict[str, Any]:
    from apollo.db.repositories import infra

    goals = repo.list_goals(session, status=m.GoalStatus.ACTIVE)
    return {
        "now": clock.now().isoformat(),
        "timezone": str(clock.tz),
        "paused": infra.is_paused(session),
        "goals": [_dump(g) for g in goals],
        "practices": [_dump(p) for p in repo.list_practices(session, status=m.PracticeStatus.ACTIVE)],
        "open_tasks": len(repo.list_tasks(session, status=m.TaskStatus.TODO)),
        "latest_review": _maybe_dump(latest_review(session)),
    }


def today_view(session: Session, clock: Clock) -> dict[str, Any]:
    start, end = day_window(clock)
    tasks = [
        t
        for t in repo.list_tasks(session, status=m.TaskStatus.TODO)
        if t.due_at is not None and t.due_at < end
    ]
    overdue = repo.overdue_tasks(session, clock.now())
    habits_due = [h for h in repo.list_habits(session) if is_due(h.rrule, clock.now())]
    week_start, week_end = week_window(clock)
    week_tasks = [
        t
        for t in repo.list_tasks(session, status=m.TaskStatus.DONE)
        if t.completed_at is not None and week_start <= t.completed_at < week_end
    ]
    return {
        "date": start.date().isoformat(),
        "tasks_due": [_dump(t) for t in tasks],
        "overdue": [_dump(t) for t in overdue],
        "habits_due": [_dump(h) for h in habits_due],
        "completed_this_week": len(week_tasks),
    }


def what_should_i_do_now(session: Session, clock: Clock, *, limit: int = 5) -> list[dict[str, Any]]:
    now = clock.now()
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for task in repo.overdue_tasks(session, now):
        candidates.append((0, "overdue task", _dump(task)))
    _, end = day_window(clock)
    for task in repo.list_tasks(session, status=m.TaskStatus.TODO):
        if task.due_at is not None and task.due_at < end:
            candidates.append((1, "due today", _dump(task)))
        elif task.priority <= 2:
            candidates.append((2, "high priority", _dump(task)))
    for habit in repo.list_habits(session):
        if is_due(habit.rrule, now):
            candidates.append((3, "habit due", _dump(habit)))
    candidates.sort(key=lambda row: (row[0], -int(row[2].get("priority", 3))))
    return [
        {"reason": reason, "kind": _kind(payload), **payload}
        for _, reason, payload in candidates[:limit]
    ]


def _kind(payload: dict[str, Any]) -> str:
    if "rrule" in payload:
        return "habit"
    return "task"


def _coerce(enum_cls: Any, value: Any, default: Any = None) -> Any:
    """Model-supplied filters ("open", "in progress") must never raise."""
    if not value:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


def list_goals(session: Session, status: str | None = None) -> list[dict[str, Any]]:
    return [_dump(g) for g in repo.list_goals(session, status=_coerce(m.GoalStatus, status))]


def get_goal(session: Session, goal_id: int) -> dict[str, Any] | None:
    goal = repo.get_goal(session, goal_id)
    if goal is None:
        return None
    data = _dump(goal)
    data["practices"] = [_dump(p) for p in repo.list_practices(session, goal_id=goal_id)]
    data["projects"] = [_dump(p) for p in repo.list_projects(session, goal_id=goal_id)]
    data["metrics"] = [_dump(x) for x in repo.list_metrics(session, goal_id=goal_id)]
    return data


def list_practices(session: Session, goal_id: int | None = None) -> list[dict[str, Any]]:
    return [_dump(p) for p in repo.list_practices(session, goal_id=goal_id)]


def list_tasks(
    session: Session,
    *,
    status: str | None = None,
    project_id: int | None = None,
    goal_id: int | None = None,
) -> list[dict[str, Any]]:
    task_status = _coerce(m.TaskStatus, status)
    return [
        _dump(t)
        for t in repo.list_tasks(
            session, status=task_status, project_id=project_id, goal_id=goal_id
        )
    ]


def list_habits(session: Session) -> list[dict[str, Any]]:
    return [_dump(h) for h in repo.list_habits(session)]


def list_metrics(session: Session) -> list[dict[str, Any]]:
    metrics = repo.list_metrics(session)
    out: list[dict[str, Any]] = []
    for metric in metrics:
        data = _dump(metric)
        series = logrepo.metric_series(session, metric.id or 0, limit=5)
        data["recent"] = [_dump(c) for c in series]
        out.append(data)
    return out


def latest_review(session: Session) -> m.Review | None:
    reviews = logrepo.list_reviews(session)
    return reviews[-1] if reviews else None


def get_review(session: Session, review_id: int | None = None) -> dict[str, Any] | None:
    review = logrepo.get_review(session, review_id) if review_id else latest_review(session)
    return _dump(review) if review else None


def search_vault(session: Session, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    from apollo.db.fts import search_vault as fts_search

    return fts_search(session.connection(), query, limit=limit)


def recall_memory(memory: Any, query: str, *, k: int = 6) -> list[dict[str, Any]]:
    return [
        {"text": item.text, "score": item.score, "metadata": item.metadata}
        for item in memory.recall(query, k=k)
    ]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def create_goal(session: Session, *, title: str, **fields: Any) -> dict[str, Any]:
    return _dump(repo.create_goal(session, m.Goal(title=title, **fields)))


def update_goal(session: Session, goal_id: int, **changes: Any) -> dict[str, Any]:
    return _dump(repo.update_goal(session, goal_id, **changes))


def create_practice(session: Session, *, name: str, **fields: Any) -> dict[str, Any]:
    return _dump(repo.create_practice(session, m.Practice(name=name, **fields)))


def create_project(session: Session, *, title: str, **fields: Any) -> dict[str, Any]:
    return _dump(repo.create_project(session, m.Project(title=title, **fields)))


def find_recent_duplicate_task(
    session: Session, title: str, due_at: datetime | None, *, within_minutes: int = 10
) -> m.Task | None:
    """Detect the same task captured twice in quick succession.

    Agent retries (and a model calling a write tool plus emitting the same command)
    otherwise produce duplicate open tasks.
    """
    since = _now() - timedelta(minutes=within_minutes)
    stmt = (
        select(t.Task)
        .where(t.Task.title == title)
        .where(t.Task.status.in_([m.TaskStatus.TODO.value, m.TaskStatus.DOING.value]))
        .where(t.Task.created_at >= since)
    )
    if due_at is None:
        stmt = stmt.where(t.Task.due_at.is_(None))
    else:
        stmt = stmt.where(t.Task.due_at == due_at)
    row = session.execute(stmt.order_by(t.Task.id.desc())).scalars().first()
    return to_model(m.Task, row) if row is not None else None


def create_task(session: Session, *, title: str, **fields: Any) -> dict[str, Any]:
    due_at = fields.get("due_at")
    duplicate = find_recent_duplicate_task(session, title, due_at)
    if duplicate is not None:
        return _dump(duplicate)
    return _dump(repo.create_task(session, m.Task(title=title, **fields)))


def complete_task(session: Session, task_id: int) -> dict[str, Any]:
    return _dump(repo.complete_task(session, task_id))


def log_checkin(session: Session, *, kind: str | None = None, **fields: Any) -> dict[str, Any]:
    checkin = m.CheckIn(
        kind=_coerce(m.CheckInKind, kind or fields.pop("checkin_kind", "reflection"), m.CheckInKind.REFLECTION),
        occurred_at=fields.pop("occurred_at", None) or _now(),
        **fields,
    )
    return _dump(logrepo.log_checkin(session, checkin))


def log_metric(session: Session, metric_id: int, value: float, *, note: str | None = None) -> dict[str, Any]:
    metric, checkin, below = logrepo.record_metric(session, metric_id, value, note=note)
    return {"metric": _dump(metric), "checkin": _dump(checkin), "below_target": below}


def complete_review(
    session: Session, review_id: int, *, summary: str | None = None, insights: str | None = None,
    adjustments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dump(
        logrepo.complete_review(
            session, review_id, summary=summary, insights=insights, adjustments=adjustments
        )
    )


def capture_note_to_vault(
    vault: Any,
    session: Session,
    *,
    body: str,
    title: str | None = None,
    tags: list[str] | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    stamp = (occurred_at or _now()).date().isoformat()
    slug = _slug(title or body)
    rel = f"notes/{stamp}-{slug}.md"
    lines = ["---"]
    lines.append(f"date: {(occurred_at or _now()).isoformat()}")
    if title:
        lines.append(f"title: {title}")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path = vault.write(rel, "\n".join(lines))
    vault.sync(session)
    return {"path": path, "title": title}


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.strip()][:48]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "note"


def _dump(model: m.Base) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _maybe_dump(model: m.Base | None) -> dict[str, Any] | None:
    return _dump(model) if model is not None else None


def _now() -> datetime:

    return datetime.now(UTC)
