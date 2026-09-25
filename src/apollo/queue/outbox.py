"""Transactional outbox drainer.

Reads unprocessed ``events`` rows and enqueues jobs for (a) built-in reactions and
(b) matching event subscriptions in ``schedule_rules``. Events are marked processed
in the same transaction that creates the jobs, so a crash never loses or duplicates
a side effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories.base import utcnow
from apollo.domain.events import EventType
from apollo.queue.jobs import enqueue_job


@dataclass(frozen=True, slots=True)
class JobSpec:
    kind: str
    payload: dict = field(default_factory=dict)
    priority: int = 5


def default_reactions(event_type: str, payload: dict) -> list[JobSpec]:
    """Built-in event → job reactions that do not need a schedule rule."""
    match event_type:
        case EventType.CHECKIN_LOGGED | EventType.JOURNAL_CAPTURED | EventType.REVIEW_COMPLETED:
            return [
                JobSpec(
                    "memory.add",
                    {
                        "source": event_type,
                        "ref": payload,
                    },
                    priority=8,
                )
            ]
        case EventType.APPROVAL_GRANTED:
            if payload.get("run_id"):
                return [
                    JobSpec(
                        "approval.resume",
                        {"action_id": payload.get("id"), "run_id": payload["run_id"]},
                        priority=3,
                    )
                ]
            return []
        case EventType.APPROVAL_REQUESTED:
            summary = payload.get("summary") or payload.get("kind", "action")
            return [
                JobSpec(
                    "notify.send",
                    {
                        "kind": "approval",
                        "ref_id": str(payload.get("id")),
                        "payload": {
                            "text": (
                                f"<b>Approval needed</b>\n{summary}\n\n"
                                f"<i>kind: {payload.get('kind')}</i>"
                            ),
                            "topic": "system",
                            "format": "html",
                            "actions": [{"approval_id": payload.get("id")}],
                        },
                        "urgent": True,
                    },
                    priority=3,
                )
            ]
        case EventType.HABIT_MISSED_STREAK | EventType.METRIC_BELOW_TARGET | EventType.TASK_OVERDUE:
            text, topic = _alert_text(event_type, payload)
            return [
                JobSpec(
                    "notify.send",
                    {
                        "kind": event_type,
                        "ref_id": str(payload.get("id") or ""),
                        "payload": {"text": text, "topic": topic, "format": "markdown"},
                    },
                    priority=4,
                )
            ]
        case _:
            return []


def _alert_text(event_type: str, payload: dict) -> tuple[str, str]:
    """Human, Markdown-rendered text for the built-in alert reactions."""
    if event_type == EventType.HABIT_MISSED_STREAK:
        name = payload.get("name") or "habit"
        return f"**Habit streak broken:** {name}", "practices"
    if event_type == EventType.METRIC_BELOW_TARGET:
        name = payload.get("name") or "metric"
        value = payload.get("value")
        target = payload.get("target")
        detail = f" — {value} vs target {target}" if value is not None and target is not None else ""
        return f"**Metric below target:** {name}{detail}", "metrics"
    title = payload.get("title") or "task"
    due = payload.get("due_at")
    detail = f" (was due {due})" if due else ""
    return f"**Overdue:** {title}{detail}", "today"


def drain_events(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 200,
    paused: bool = False,
) -> int:
    now = now or utcnow()
    events = list(
        session.execute(
            select(t.Event)
            .where(t.Event.processed_at.is_(None))
            .order_by(t.Event.id)
            .limit(limit)
        ).scalars()
    )
    if not events:
        return 0

    rules = list(
        session.execute(
            select(t.ScheduleRule).where(
                t.ScheduleRule.enabled.is_(True),
                t.ScheduleRule.trigger_type == "event",
            )
        ).scalars()
    )

    enqueued = 0
    for event in events:
        event.attempts += 1
        if not paused:
            for spec in default_reactions(event.type, event.payload_json):
                enqueue_job(
                    session,
                    kind=spec.kind,
                    payload=spec.payload,
                    priority=spec.priority,
                )
                enqueued += 1
            for rule in rules:
                if rule.event_type != event.type:
                    continue
                if _cooling_down(rule, now):
                    continue
                spec = _rule_to_spec(rule, event.payload_json)
                enqueue_job(session, kind=spec.kind, payload=spec.payload, priority=spec.priority)
                rule.last_run_at = now
                enqueued += 1
        event.processed_at = now
    session.flush()
    return enqueued


def _cooling_down(rule: t.ScheduleRule, now: datetime) -> bool:
    if not rule.cooldown_seconds or rule.last_run_at is None:
        return False
    elapsed = (now - rule.last_run_at).total_seconds()
    return elapsed < rule.cooldown_seconds


def _rule_to_spec(rule: t.ScheduleRule, event_payload: dict) -> JobSpec:
    payload = dict(rule.payload_json or {})
    payload.setdefault("rule", rule.name)
    payload.setdefault("event", event_payload)
    if rule.action == "skill":
        return JobSpec("skill.run", payload, priority=4)
    if rule.action == "notify":
        return JobSpec("notify.send", payload, priority=4)
    return JobSpec("agent.run", payload, priority=4)
