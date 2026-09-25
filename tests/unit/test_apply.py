"""Command application tolerates near-miss enum values from the model."""

from __future__ import annotations

from datetime import UTC

from apollo.db.repositories import domain as repo
from apollo.domain import models as m
from apollo.domain.apply import apply_command
from apollo.domain.commands import (
    CompleteReview,
    CompleteTask,
    LogCheckIn,
    LogMetric,
    UpdateProject,
)


def test_complete_task_accepts_unknown_status(db) -> None:
    with db.write() as session:
        task = repo.create_task(session, m.Task(title="Ship it"))
        assert task.id is not None
        summary = apply_command(  # model wrote status="open"
            session, CompleteTask.model_validate({"task_id": task.id, "status": "open"})
        )
    assert "completed" in summary
    with db.session() as session:
        stored = repo.get_task(session, task.id)
    assert stored is not None and stored.status == m.TaskStatus.DONE


def test_update_project_ignores_unknown_status(db) -> None:
    with db.write() as session:
        project = repo.create_project(session, m.Project(title="Launch"))
        assert project.id is not None
        apply_command(
            session,
            UpdateProject.model_validate({"project_id": project.id, "status": "in flight"}),
        )
    with db.session() as session:
        stored = repo.get_project(session, project.id)
    assert stored is not None and stored.status == m.ProjectStatus.PLANNED


def test_log_checkin_unknown_kind_falls_back_to_reflection(db) -> None:
    with db.write() as session:
        apply_command(
            session, LogCheckIn.model_validate({"checkin_kind": "sleep", "value_num": 7.5})
        )
    with db.session() as session:
        from apollo.db.repositories import logs as logrepo

        assert logrepo.last_checkin_in(session, m.CheckInKind.REFLECTION) is not None


def test_log_metric_unknown_direction_defaults_to_increase(db) -> None:
    with db.write() as session:
        apply_command(
            session,
            LogMetric.model_validate(
                {"name": "Pushups", "unit": "reps", "target": 50, "direction": "up", "value": 30}
            ),
        )
    with db.session() as session:
        metrics = repo.list_metrics(session)
    assert metrics and metrics[0].direction == m.Direction.INCREASE


def test_unknown_command_kind_is_rejected_by_schema() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CompleteReview.model_validate({"kind": "not_a_kind"})


def test_list_tools_tolerate_loose_status_filters(db) -> None:
    """Tool calls like list_tasks(status='open') must not raise."""
    from apollo.tools import db_tools

    with db.write() as session:
        repo.create_task(session, m.Task(title="One"))
        repo.create_goal(session, m.Goal(title="G"))
        db_tools.log_checkin(session, kind="sleep", value_num=7.0)
    with db.session() as session:
        assert len(db_tools.list_tasks(session, status="open")) == 1
        assert len(db_tools.list_goals(session, status="in progress")) == 1
    with db.session() as session:
        from apollo.db.repositories import logs as logrepo

        assert logrepo.last_checkin_in(session, m.CheckInKind.REFLECTION) is not None


def test_capture_task_is_deduped_within_window(db) -> None:
    from datetime import datetime

    from apollo.domain.commands import CaptureTask
    from apollo.tools import db_tools

    due = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
    payload = {"title": "Call the dentist", "due_at": due.isoformat()}
    with db.write() as session:
        first = apply_command(session, CaptureTask.model_validate(payload))
        second = apply_command(session, CaptureTask.model_validate(payload))
    assert first == second  # same task, not a duplicate
    with db.session() as session:
        tasks = db_tools.list_tasks(session)
    assert len(tasks) == 1
