"""Built-in routines seeded on install and period review provisioning."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.domain.models import ReviewCadence
from apollo.scheduler.rules import add_rule, get_rule
from apollo.tools.clock import Clock
from apollo.tools.time import day_window, month_window, week_window

DEFAULT_AREAS = ["Health", "Career", "Finance", "Relationships"]

DEFAULT_RULES: list[dict] = [
    {
        "name": "morning_briefing",
        "trigger_type": "time",
        "action": "job",
        "cron": "0 7 * * *",
        "payload": {"job_kind": "briefing.generate"},
        "cooldown_seconds": 3600,
    },
    {
        "name": "evening_checkin",
        "trigger_type": "time",
        "action": "skill",
        "cron": "0 21 * * *",
        "payload": {"skill": "evening-checkin", "topic": "today"},
        "cooldown_seconds": 3600,
    },
    {
        "name": "weekly_review",
        "trigger_type": "time",
        "action": "job",
        "cron": "0 18 * * 0",
        "payload": {"job_kind": "review.generate"},
        "cooldown_seconds": 3600,
    },
    {
        "name": "drift_check",
        "trigger_type": "time",
        "action": "skill",
        "cron": "0 8 * * *",
        "payload": {"skill": "drift-detect", "topic": "system"},
        "cooldown_seconds": 3600,
    },
    {
        "name": "overdue_sweep",
        "trigger_type": "time",
        "action": "job",
        "cron": "0 * * * *",
        "payload": {"job_kind": "overdue.sweep"},
        "cooldown_seconds": 1800,
    },
    {
        "name": "vault_sync",
        "trigger_type": "time",
        "action": "job",
        "cron": "*/5 * * * *",
        "payload": {"job_kind": "vault.sync"},
        "cooldown_seconds": 60,
    },
    {
        "name": "no_checkin_nudge",
        "trigger_type": "condition",
        "action": "skill",
        "predicate": "no_checkin_days(2)",
        "payload": {"skill": "drift-detect", "topic": "system"},
        "cooldown_seconds": 86400,
        "enabled": False,
    },
]


def seed_defaults(session: Session) -> int:
    created = 0
    for name in DEFAULT_AREAS:
        exists = session.execute(select(t.Area).where(t.Area.name == name)).scalar_one_or_none()
        if exists is None:
            session.add(t.Area(name=name))
            created += 1
    for spec in DEFAULT_RULES:
        if get_rule(session, spec["name"]) is None:
            add_rule(
                session,
                name=spec["name"],
                trigger_type=spec["trigger_type"],
                action=spec["action"],
                payload=spec.get("payload"),
                cron=spec.get("cron"),
                event_type=spec.get("event_type"),
                predicate=spec.get("predicate"),
                enabled=spec.get("enabled", True),
                cooldown_seconds=spec.get("cooldown_seconds", 0),
            )
            created += 1
    session.flush()
    return created


def ensure_period_reviews(session: Session, clock: Clock) -> int:
    """Ensure pending reviews exist for the current day, week and month."""
    created = 0
    windows = [
        (ReviewCadence.DAILY, day_window(clock)),
        (ReviewCadence.WEEKLY, week_window(clock)),
        (ReviewCadence.MONTHLY, month_window(clock)),
    ]
    for cadence, (start, end) in windows:
        existing = session.execute(
            select(t.Review).where(t.Review.cadence == cadence.value, t.Review.period_start == start)
        ).scalar_one_or_none()
        if existing is None:
            logrepo.ensure_review(session, cadence, start, end)
            created += 1
    return created


def current_period_start(cadence: m.ReviewCadence, clock: Clock):
    if cadence == ReviewCadence.DAILY:
        return day_window(clock)[0]
    if cadence == ReviewCadence.WEEKLY:
        return week_window(clock)[0]
    return month_window(clock)[0]
