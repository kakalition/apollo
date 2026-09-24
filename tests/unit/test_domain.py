"""Domain classification and cardinality edge cases."""

from __future__ import annotations

from apollo.db.repositories import domain as repo
from apollo.domain.models import EntityKind, Goal, Metric, Practice, Project, Task, classify_entity


def test_classification_order() -> None:
    assert classify_entity(measures=True) is EntityKind.METRIC
    assert classify_entity(repeats=True) is EntityKind.HABIT
    assert classify_entity(completable=True) is EntityKind.PROJECT
    assert classify_entity(practised=True) is EntityKind.PRACTICE
    assert classify_entity(wanted=True) is EntityKind.GOAL
    assert classify_entity() is EntityKind.TASK
    # Measurement beats practice even if both described.
    assert classify_entity(measures=True, practised=True) is EntityKind.METRIC


def test_metric_without_goal_is_allowed(db) -> None:
    with db.write() as session:
        metric = repo.create_metric(session, Metric(name="Sleep hours", unit="h", target=7.5))
    assert metric.id is not None
    assert metric.goal_id is None


def test_unparented_task_lands_in_inbox(db) -> None:
    with db.write() as session:
        task = repo.create_task(session, Task(title="Call the dentist"))
    assert task.id is not None
    assert task.project_id is None and task.goal_id is None and task.practice_id is None
    with db.session() as session:
        inbox = repo.list_tasks(session, status=None)
    assert any(t.id == task.id for t in inbox)


def test_single_action_practice_keeps_practice_and_habit(db) -> None:
    """Edge case 1: 'meditate daily' keeps both Practice and Habit."""
    with db.write() as session:
        practice = repo.create_practice(session, Practice(name="Meditate", cadence="daily"))
        assert practice.id is not None
        from apollo.domain.models import Habit

        habit = repo.create_habit(
            session, Habit(practice_id=practice.id, name="Meditate 10m", rrule="FREQ=DAILY")
        )
    assert habit.practice_id == practice.id

    with db.session() as session:
        habits = repo.list_habits(session, practice_id=practice.id)
    assert len(habits) == 1


def test_goal_without_recurring_becomes_practice_plus_project(db) -> None:
    """Edge case 2: launching a side project = Practice + Project + Tasks."""
    with db.write() as session:
        goal = repo.create_goal(session, Goal(title="Launch side project"))
        practice = repo.create_practice(
            session, Practice(name="Weekly build sessions", goal_id=goal.id, cadence="1x/week")
        )
        assert practice.id is not None
        project = repo.create_project(
            session, Project(title="Ship v1", goal_id=goal.id, done_when="public URL exists")
        )
        repo.create_task(session, Task(title="Register domain", project_id=project.id))
    with db.session() as session:
        practices = repo.list_practices(session, goal_id=goal.id)
        projects = repo.list_projects(session, goal_id=goal.id)
        tasks = repo.list_tasks(session, project_id=project.id)
    assert len(practices) == 1 and len(projects) == 1 and len(tasks) == 1
