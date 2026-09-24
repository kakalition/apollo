"""Dispatcher scheduler tick: evaluate due cron rules and condition predicates."""

from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from apollo.domain import predicates
from apollo.observability import get_logger
from apollo.queue.jobs import enqueue_job
from apollo.scheduler.rules import cooling_down, job_spec, list_rules
from apollo.tools.clock import Clock

log = get_logger("apollo.scheduler")


def run_tick(session: Session, now: datetime, clock: Clock) -> dict[str, int]:
    cron_jobs = _run_cron(session, now, clock)
    condition_jobs = _run_conditions(session, now, clock)
    if cron_jobs or condition_jobs:
        log.info("scheduler.tick", cron_jobs=cron_jobs, condition_jobs=condition_jobs)
    return {"cron_jobs": cron_jobs, "condition_jobs": condition_jobs}


def _run_cron(session: Session, now: datetime, clock: Clock) -> int:
    from datetime import timedelta

    count = 0
    for rule in list_rules(session, trigger_type="time"):
        if not rule.enabled or not rule.cron:
            continue
        try:
            trigger = CronTrigger.from_crontab(rule.cron, timezone=clock.tz)
        except ValueError as exc:
            log.warning("scheduler.bad_cron", rule=rule.name, cron=rule.cron, error=str(exc))
            continue
        # Next fire strictly after the last run (or a search horizon on first run),
        # then check whether that scheduled time has already passed.
        base = rule.last_run_at or (now - timedelta(days=70))
        previous = trigger.get_next_fire_time(base, now)
        if previous is None or previous > now:
            continue
        if rule.last_run_at is not None and previous <= rule.last_run_at:
            continue
        if cooling_down(rule, now):
            continue
        kind, payload, priority = job_spec(rule)
        payload["scheduled_for"] = previous.isoformat()
        enqueue_job(session, kind=kind, payload=payload, priority=priority)
        rule.last_run_at = now
        count += 1
    session.flush()
    return count


def _run_conditions(session: Session, now: datetime, clock: Clock) -> int:
    count = 0
    for rule in list_rules(session, trigger_type="condition"):
        if not rule.enabled or not rule.predicate:
            continue
        if cooling_down(rule, now):
            continue
        try:
            matched = predicates.evaluate(session, clock, rule.predicate)
        except Exception as exc:
            log.warning("scheduler.bad_predicate", rule=rule.name, predicate=rule.predicate, error=str(exc))
            continue
        if not matched:
            continue
        kind, payload, priority = job_spec(rule)
        enqueue_job(session, kind=kind, payload=payload, priority=priority)
        rule.last_run_at = now
        count += 1
    session.flush()
    return count


def next_fire(rule_name: str, now: datetime, clock: Clock, cron: str) -> datetime | None:
    """Return the next fire time for a cron expression (used by inspection/tests)."""
    trigger = CronTrigger.from_crontab(cron, timezone=clock.tz)
    return trigger.get_next_fire_time(None, now)
