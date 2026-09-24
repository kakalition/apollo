"""Repositories for infrastructure tables: settings/flags, approvals,
notifications, run logs and conversations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories.base import audit, emit, utcnow
from apollo.domain import models as m
from apollo.domain.events import EventType

PAUSE_KEY = "paused"


# ---------------------------------------------------------------------------
# Settings / flags
# ---------------------------------------------------------------------------
def set_setting(session: Session, key: str, value: dict[str, Any]) -> None:
    row = session.get(t.Setting, key)
    if row is None:
        session.add(t.Setting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    session.flush()


def get_setting(session: Session, key: str, default: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = session.get(t.Setting, key)
    return row.value if row is not None else default


def delete_setting(session: Session, key: str) -> None:
    row = session.get(t.Setting, key)
    if row is not None:
        session.delete(row)
        session.flush()


def is_paused(session: Session) -> bool:
    return bool((get_setting(session, PAUSE_KEY) or {}).get("value"))


def set_paused(session: Session, paused: bool, *, actor: str = "cli") -> None:
    set_setting(session, PAUSE_KEY, {"value": paused, "at": utcnow().isoformat()})
    audit(session, actor=actor, action="pause" if paused else "resume", entity_type="settings")


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
def create_pending_action(
    session: Session,
    *,
    kind: str,
    payload: dict[str, Any],
    run_id: str | None = None,
    expires_at: datetime | None = None,
) -> m.PendingAction:
    row = t.PendingAction(
        run_id=run_id, kind=kind, payload_json=payload, status="pending", expires_at=expires_at
    )
    session.add(row)
    session.flush()
    emit(
        session,
        EventType.APPROVAL_REQUESTED,
        {"id": row.id, "kind": kind, "run_id": run_id, "summary": payload.get("summary")},
    )
    return _action_to_model(row)


def get_pending_action(session: Session, action_id: int) -> m.PendingAction | None:
    row = session.get(t.PendingAction, action_id)
    return _action_to_model(row) if row else None


def list_pending_actions(session: Session, status: str | None = "pending") -> list[m.PendingAction]:
    stmt = select(t.PendingAction)
    if status is not None:
        stmt = stmt.where(t.PendingAction.status == status)
    return [_action_to_model(row) for row in session.execute(stmt.order_by(t.PendingAction.id)).scalars()]


def decide_action(
    session: Session,
    action_id: int,
    decision: str,
    *,
    decided_by: str = "telegram",
) -> m.PendingAction:
    """decision is one of ``approved`` / ``denied`` (or ``expired``)."""
    row = session.get(t.PendingAction, action_id)
    if row is None:
        raise KeyError(f"pending action {action_id} not found")
    if row.status != "pending":
        return _action_to_model(row)
    row.status = decision
    row.decided_at = utcnow()
    row.decided_by = decided_by
    session.flush()
    event = EventType.APPROVAL_GRANTED if decision == "approved" else EventType.APPROVAL_DENIED
    audit(
        session,
        actor=decided_by,
        action=f"approval.{decision}",
        entity_type="pending_actions",
        entity_id=action_id,
        after={"status": decision},
        run_id=row.run_id,
    )
    emit(session, event, {"id": action_id, "kind": row.kind, "run_id": row.run_id})
    return _action_to_model(row)


def expire_stale_actions(session: Session, now: datetime) -> list[int]:
    stmt = select(t.PendingAction).where(
        t.PendingAction.status == "pending",
        t.PendingAction.expires_at.is_not(None),
        t.PendingAction.expires_at < now,
    )
    ids: list[int] = []
    for row in session.execute(stmt).scalars():
        ids.append(row.id)
    for action_id in ids:
        decide_action(session, action_id, "expired", decided_by="system")
    return ids


def _action_to_model(row: t.PendingAction) -> m.PendingAction:
    return m.PendingAction.model_validate(row, from_attributes=True)


# ---------------------------------------------------------------------------
# Notifications outbox
# ---------------------------------------------------------------------------
def enqueue_notification(
    session: Session,
    *,
    kind: str,
    ref_id: str | None = None,
    period: str | None = None,
    payload: dict[str, Any] | None = None,
    urgent: bool = False,
    scheduled_for: datetime | None = None,
) -> t.Notification:
    """Idempotent on ``(kind, ref_id, period)`` so a retry never double-posts."""
    existing = session.execute(
        select(t.Notification).where(
            t.Notification.kind == kind,
            t.Notification.ref_id == ref_id,
            t.Notification.period == period,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = t.Notification(
        kind=kind,
        ref_id=ref_id,
        period=period,
        payload_json=payload or {},
        urgent=urgent,
        scheduled_for=scheduled_for or utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def claim_notifications(session: Session, now: datetime, *, limit: int = 20) -> list[t.Notification]:
    stmt = (
        select(t.Notification)
        .where(t.Notification.status == "pending", t.Notification.scheduled_for <= now)
        .order_by(t.Notification.urgent.desc(), t.Notification.id)
        .limit(limit)
    )
    rows = list(session.execute(stmt).scalars())
    for row in rows:
        row.status = "sending"
    session.flush()
    return rows


def mark_sent(session: Session, notification_id: int) -> None:
    row = session.get(t.Notification, notification_id)
    if row is not None:
        row.status = "sent"
        row.sent_at = utcnow()
        session.flush()


def mark_failed(session: Session, notification_id: int, error: str, *, retry: bool = True) -> None:
    row = session.get(t.Notification, notification_id)
    if row is None:
        return
    row.attempts = (row.attempts or 0) + 1
    row.error = error
    row.status = "pending" if retry else "failed"
    session.flush()


# ---------------------------------------------------------------------------
# Run logs & conversations
# ---------------------------------------------------------------------------
def write_run_log(
    session: Session,
    *,
    run_id: str,
    agent: str,
    tier: str | None = None,
    model: str | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    tool_calls: list[str] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    duration_ms: int | None = None,
    status: str = "ok",
    error: str | None = None,
) -> None:
    session.add(
        t.RunLog(
            run_id=run_id,
            agent=agent,
            tier=tier,
            model=model,
            input_text=input_text,
            output_text=output_text,
            tool_calls=tool_calls or [],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            status=status,
            error=error,
        )
    )
    session.flush()


def get_or_create_conversation(
    session: Session,
    conversation_id: str,
    *,
    channel: str = "telegram",
    telegram_user_id: int | None = None,
    topic_id: int | None = None,
) -> t.Conversation:
    row = session.execute(
        select(t.Conversation).where(t.Conversation.conversation_id == conversation_id)
    ).scalar_one_or_none()
    if row is None:
        row = t.Conversation(
            conversation_id=conversation_id,
            channel=channel,
            telegram_user_id=telegram_user_id,
            topic_id=topic_id,
        )
        session.add(row)
        session.flush()
    else:
        if telegram_user_id is not None:
            row.telegram_user_id = telegram_user_id
        if topic_id is not None:
            row.topic_id = topic_id
        row.updated_at = utcnow()
        session.flush()
    return row
