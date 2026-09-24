"""Event types and payload helpers for the transactional outbox."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    GOAL_CREATED = "goal.created"
    GOAL_UPDATED = "goal.updated"
    GOAL_ACHIEVED = "goal.achieved"

    PRACTICE_CREATED = "practice.created"
    PRACTICE_UPDATED = "practice.updated"

    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"

    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_OVERDUE = "task.overdue"

    HABIT_CREATED = "habit.created"
    HABIT_LOGGED = "habit.logged"
    HABIT_MISSED_STREAK = "habit.missed_streak"

    METRIC_CREATED = "metric.created"
    METRIC_RECORDED = "metric.recorded"
    METRIC_BELOW_TARGET = "metric.below_target"

    CHECKIN_LOGGED = "checkin.logged"

    REVIEW_DUE = "review.due"
    REVIEW_COMPLETED = "review.completed"

    JOURNAL_CAPTURED = "journal.captured"

    MESSAGE_RECEIVED = "message.received"
    JOB_FAILED = "job.failed"

    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"


def payload(**kwargs: Any) -> dict[str, Any]:
    """Normalise an event payload (drops ``None`` values, JSON-safe datetimes)."""
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out
