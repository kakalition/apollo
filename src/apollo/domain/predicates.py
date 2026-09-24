"""Registered condition predicates for schedule rules.

Rules store a predicate *string* like ``no_checkin_days(3)``; this registry maps it
to a safe Python callable. No ``eval`` anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.orm import Session

from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.tools.clock import Clock

Predicate = Callable[[Session, Clock, list[str]], bool]

_CALL = re.compile(r"^([a-zA-Z_][\w]*)\((.*)\)$")


def no_checkin_days(session: Session, clock: Clock, args: list[str]) -> bool:
    days = int(args[0]) if args else 2
    since = clock.now() - timedelta(days=days)
    return not logrepo.list_checkins(session, since=since, limit=1)


def metric_below_target(session: Session, clock: Clock, args: list[str]) -> bool:
    metric_id = int(args[0]) if args else 0
    metric = repo.get_metric(session, metric_id)
    if metric is None or metric.target is None:
        return False
    series = logrepo.metric_series(session, metric_id, limit=1)
    if not series:
        return False
    value = series[0].value_num
    if value is None:
        return False
    if metric.direction == m.Direction.INCREASE:
        return value < metric.target
    if metric.direction == m.Direction.DECREASE:
        return value > metric.target
    return False


def habit_streak_broken(session: Session, clock: Clock, args: list[str]) -> bool:
    habit_id = int(args[0]) if args else 0
    return logrepo.habit_streak_broken(session, habit_id, clock.now())


def goal_no_progress_days(session: Session, clock: Clock, args: list[str]) -> bool:
    days = int(args[0]) if args else 14
    cutoff = clock.now() - timedelta(days=days)
    for goal in repo.list_goals(session, status=m.GoalStatus.ACTIVE):
        if goal.id is None:
            continue
        tasks = repo.list_tasks(session, goal_id=goal.id)
        completed = [
            t for t in tasks if t.completed_at is not None and t.completed_at >= cutoff
        ]
        if completed:
            continue
        practices = repo.list_practices(session, goal_id=goal.id)
        practice_ids = {p.id for p in practices}
        checkins = [
            c
            for c in logrepo.list_checkins(session, since=cutoff, limit=500)
            if c.ref_id in practice_ids
        ]
        if not checkins:
            return True
    return False


def overdue_tasks(session: Session, clock: Clock, args: list[str]) -> bool:
    threshold = int(args[0]) if args else 1
    return len(repo.overdue_tasks(session, clock.now())) >= threshold


REGISTRY: dict[str, Predicate] = {
    "no_checkin_days": no_checkin_days,
    "metric_below_target": metric_below_target,
    "habit_streak_broken": habit_streak_broken,
    "goal_no_progress_days": goal_no_progress_days,
    "overdue_tasks": overdue_tasks,
}


def parse(spec: str) -> tuple[str, list[str]]:
    match = _CALL.match(spec.strip())
    if not match:
        return spec.strip(), []
    name, raw_args = match.groups()
    args = [a.strip() for a in raw_args.split(",") if a.strip()]
    return name, args


def evaluate(session: Session, clock: Clock, spec: str) -> bool:
    name, args = parse(spec)
    predicate = REGISTRY.get(name)
    if predicate is None:
        return False
    return predicate(session, clock, args)
