"""Repository invariants: transactional event emission and auditing."""

from __future__ import annotations

from sqlalchemy import select

from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.domain.events import EventType


def _events(db) -> list[str]:
    with db.session() as session:
        return [row.type for row in session.execute(select(t.Event).order_by(t.Event.id)).scalars()]


def test_create_goal_emits_event_in_same_transaction(db) -> None:
    with db.write() as session:
        repo.create_goal(session, m.Goal(title="Run a half marathon"))
    assert EventType.GOAL_CREATED in _events(db)


def test_update_goal_to_achieved_emits_achieved_and_audits(db) -> None:
    with db.write() as session:
        goal = repo.create_goal(session, m.Goal(title="Read 12 books"))
        assert goal.id is not None
        repo.update_goal(session, goal.id, status=m.GoalStatus.ACHIEVED)
    assert EventType.GOAL_ACHIEVED in _events(db)
    with db.session() as session:
        audits = list(session.execute(select(t.AuditLog)).scalars())
    assert any(a.action == "goal.update" and a.entity_id == goal.id for a in audits)


def test_failed_transaction_emits_nothing(db) -> None:
    try:
        with db.write() as session:
            repo.create_goal(session, m.Goal(title="Boom"))
            raise RuntimeError("rollback please")
    except RuntimeError:
        pass
    assert EventType.GOAL_CREATED not in _events(db)


def test_complete_task_sets_completed_at(db) -> None:
    with db.write() as session:
        task = repo.create_task(session, m.Task(title="Ship it"))
        assert task.id is not None
        done = repo.complete_task(session, task.id)
    assert done.status == m.TaskStatus.DONE
    assert done.completed_at is not None
    assert EventType.TASK_COMPLETED in _events(db)


def test_log_habit_updates_streak_and_logs_checkin(db) -> None:
    with db.write() as session:
        practice = repo.create_practice(session, m.Practice(name="Run"))
        assert practice.id is not None
        habit = repo.create_habit(session, m.Habit(practice_id=practice.id, name="Run 5k", rrule="FREQ=DAILY"))
        assert habit.id is not None
        updated, _checkin = logrepo.log_habit(session, habit.id, occurred_at=_dt("2026-03-01T07:00:00Z"))
        assert updated.current_streak == 1
        updated2, _ = logrepo.log_habit(session, habit.id, occurred_at=_dt("2026-03-02T07:00:00Z"))
    assert updated2.current_streak == 2
    assert updated2.best_streak == 2
    with db.session() as session:
        checkins = logrepo.list_checkins(session, kind=m.CheckInKind.HABIT, ref_id=habit.id)
    assert len(checkins) == 2


def test_metric_below_target_emits_event(db) -> None:
    with db.write() as session:
        metric = repo.create_metric(session, m.Metric(name="Weight", unit="kg", target=70, direction=m.Direction.DECREASE))
        assert metric.id is not None
        _, _, below = logrepo.record_metric(session, metric.id, 72.0)
    assert below is True
    assert EventType.METRIC_BELOW_TARGET in _events(db)


def _dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
