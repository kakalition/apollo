"""Schedule rules: CRUD and the dispatcher evaluation (cron / event / condition)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t

TRIGGER_TYPES = ("time", "event", "condition")
ACTIONS = ("job", "skill", "agent", "notify")


def add_rule(
    session: Session,
    *,
    name: str,
    trigger_type: str,
    action: str = "job",
    payload: dict[str, Any] | None = None,
    cron: str | None = None,
    event_type: str | None = None,
    predicate: str | None = None,
    enabled: bool = True,
    cooldown_seconds: int = 0,
    quiet_hours_policy: str = "buffer",
) -> t.ScheduleRule:
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"trigger_type must be one of {TRIGGER_TYPES}")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    rule = t.ScheduleRule(
        name=name,
        trigger_type=trigger_type,
        action=action,
        payload_json=payload or {},
        cron=cron,
        event_type=event_type,
        predicate=predicate,
        enabled=enabled,
        cooldown_seconds=cooldown_seconds,
        quiet_hours_policy=quiet_hours_policy,
    )
    session.add(rule)
    session.flush()
    return rule


def get_rule(session: Session, name: str) -> t.ScheduleRule | None:
    return session.execute(
        select(t.ScheduleRule).where(t.ScheduleRule.name == name)
    ).scalar_one_or_none()


def list_rules(session: Session, trigger_type: str | None = None) -> list[t.ScheduleRule]:
    stmt = select(t.ScheduleRule).order_by(t.ScheduleRule.id)
    if trigger_type:
        stmt = stmt.where(t.ScheduleRule.trigger_type == trigger_type)
    return list(session.execute(stmt).scalars())


def toggle_rule(session: Session, name: str, enabled: bool | None = None) -> bool:
    rule = get_rule(session, name)
    if rule is None:
        raise KeyError(f"rule {name!r} not found")
    rule.enabled = (not rule.enabled) if enabled is None else enabled
    session.flush()
    return bool(rule.enabled)


def job_spec(rule: t.ScheduleRule) -> tuple[str, dict[str, Any], int]:
    """Map a rule to ``(job_kind, payload, priority)``."""
    payload = dict(rule.payload_json or {})
    payload.setdefault("rule", rule.name)
    if rule.action == "skill":
        return "skill.run", payload, 4
    if rule.action == "agent":
        return "agent.run", payload, 4
    if rule.action == "notify":
        return "notify.send", payload, 4
    kind = payload.pop("job_kind", "schedule.evaluate")
    return kind, payload, int(payload.pop("priority", 4))


def cooling_down(rule: t.ScheduleRule, now: datetime) -> bool:
    if not rule.cooldown_seconds or rule.last_run_at is None:
        return False
    return (now - rule.last_run_at).total_seconds() < rule.cooldown_seconds
