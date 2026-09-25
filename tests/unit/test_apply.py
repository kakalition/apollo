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


def test_capture_result_converts_to_commands_and_applies(db) -> None:
    from apollo.domain.apply import apply_capture, capture_result_to_commands
    from apollo.domain.commands import CaptureResult

    result = CaptureResult.model_validate(
        {
            "items": [
                {"kind": "task", "title": "Buy milk", "due_at": "2026-03-02T10:00:00+00:00"},
                {"kind": "checkin", "checkin_kind": "reflection", "note": "tired"},
                {"kind": "metric", "name": "Sleep", "value": 7.5},
                {"kind": "note", "body": "idea: meal prep"},
            ],
            "reply": "Captured.",
        }
    )
    commands = capture_result_to_commands(result)
    assert [c.kind for c in commands] == [
        "capture_tasks",
        "log_checkin",
        "log_metric",
        "capture_note",
    ]
    with db.write() as session:
        applied = apply_capture(session, result)
    assert len(applied) == 4
    with db.session() as session:
        from apollo.db.repositories import logs as logrepo

        assert len(repo.list_tasks(session)) == 1
        assert logrepo.last_checkin_in(session, m.CheckInKind.REFLECTION) is not None
        assert repo.list_metrics(session)[0].name == "Sleep"


def test_empty_capture_result_is_a_noop(db) -> None:
    from apollo.domain.apply import capture_result_to_commands
    from apollo.domain.commands import CaptureResult

    assert capture_result_to_commands(CaptureResult(items=[], reply="what did you mean?")) == []


def test_apply_plan_wires_parents_and_children(db) -> None:
    from apollo.domain.apply import apply_plan
    from apollo.domain.commands import PlanResult

    result = PlanResult.model_validate(
        {
            "goals": [
                {
                    "title": "Run a half marathon",
                    "outcome": "finish it",
                    "success_criteria": "21.1 km",
                    "practice": {
                        "name": "Run training",
                        "cadence": "3x/week",
                        "habits": [{"name": "Easy run", "rrule": "FREQ=DAILY"}],
                        "metrics": [{"name": "Weekly km", "unit": "km", "target": 30}],
                    },
                    "projects": [
                        {"title": "Register", "done_when": "entry confirmed", "tasks": [{"title": "Pick a race"}]}
                    ],
                    "tasks": [{"title": "Buy shoes"}],
                }
            ],
            "tasks": [{"title": "Loose task"}],
            "reply": "Here is the plan.",
        }
    )
    with db.write() as session:
        applied = apply_plan(session, result)
    assert any(item.startswith("goal #") for item in applied)
    with db.session() as session:
        goal = repo.list_goals(session)[0]
        assert goal.title == "Run a half marathon"
        assert repo.list_practices(session, goal_id=goal.id)[0].name == "Run training"
        assert repo.list_habits(session)[0].name == "Easy run"
        assert repo.list_metrics(session, goal_id=goal.id)[0].target == 30
        assert repo.list_projects(session, goal_id=goal.id)[0].title == "Register"
        titles = {task.title for task in repo.list_tasks(session)}
    assert {"Pick a race", "Buy shoes", "Loose task"} <= titles


def test_capture_reminder_schedules_a_one_off_job(db) -> None:
    from sqlalchemy import select

    from apollo.db import tables as t
    from apollo.domain.apply import apply_capture
    from apollo.domain.commands import CaptureResult

    result = CaptureResult.model_validate(
        {
            "items": [
                {"kind": "reminder", "at": "2026-03-02T10:00:00+00:00", "text": "drink water"}
            ]
        }
    )
    with db.write() as session:
        out = apply_capture(session, result)
    assert out and out[0].startswith("reminder #")
    with db.session() as session:
        job = session.execute(select(t.Job)).scalars().first()
    assert job is not None and job.kind == "reminder.fire"
    assert job.payload_json["text"] == "drink water"
