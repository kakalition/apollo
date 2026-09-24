"""Registered condition predicates."""

from __future__ import annotations

from datetime import timedelta

from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.domain import predicates


def test_no_checkin_days_true_when_none(db, clock) -> None:
    with db.session() as session:
        assert predicates.evaluate(session, clock, "no_checkin_days(2)") is True


def test_no_checkin_days_false_after_recent_checkin(db, clock) -> None:
    with db.write() as session:
        logrepo.log_checkin(session, m.CheckIn(kind=m.CheckInKind.REFLECTION, occurred_at=clock.now()))
    with db.session() as session:
        assert predicates.evaluate(session, clock, "no_checkin_days(2)") is False
        # A check-in logged exactly now counts as a check-in within 0 days too.
        assert predicates.evaluate(session, clock, "no_checkin_days(0)") is False


def test_overdue_tasks_predicate(db, clock) -> None:
    with db.write() as session:
        repo.create_task(session, m.Task(title="Late", due_at=clock.now() - timedelta(days=1)))
    with db.session() as session:
        assert predicates.evaluate(session, clock, "overdue_tasks(1)") is True
        assert predicates.evaluate(session, clock, "overdue_tasks(5)") is False


def test_metric_below_target_predicate(db, clock) -> None:
    with db.write() as session:
        metric = repo.create_metric(session, m.Metric(name="Pushups", target=50, direction=m.Direction.INCREASE))
        assert metric.id is not None
        logrepo.record_metric(session, metric.id, 30)
    with db.session() as session:
        assert predicates.evaluate(session, clock, f"metric_below_target({metric.id})") is True


def test_habit_streak_broken_predicate(db, clock) -> None:
    with db.write() as session:
        practice = repo.create_practice(session, m.Practice(name="Journal"))
        assert practice.id is not None
        habit = repo.create_habit(session, m.Habit(practice_id=practice.id, name="Journal", rrule="FREQ=DAILY"))
        assert habit.id is not None
        logrepo.log_habit(session, habit.id, occurred_at=clock.now() - timedelta(days=3))
    with db.session() as session:
        assert predicates.evaluate(session, clock, f"habit_streak_broken({habit.id})") is True


def test_parse_unknown_predicate_is_safe(db, clock) -> None:
    with db.session() as session:
        assert predicates.evaluate(session, clock, "not_a_predicate(1)") is False
