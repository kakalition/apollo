"""Repository helpers: domain mutation + transactional event emission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apollo.db import tables as t

ModelT = TypeVar("ModelT", bound=BaseModel)


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_model(model_cls: type[ModelT], row: Any) -> ModelT:
    return model_cls.model_validate(row, from_attributes=True)


def emit(session: Session, event_type: str, payload: dict[str, Any] | None = None) -> t.Event:
    """Append an event row in the caller's transaction (transactional outbox)."""
    event = t.Event(type=str(event_type), payload_json=_clean(payload or {}))
    session.add(event)
    session.flush()
    return event


def audit(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> t.AuditLog:
    entry = t.AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        run_id=run_id,
    )
    session.add(entry)
    session.flush()
    return entry


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def count(session: Session, statement: Any) -> int:
    return int(session.execute(select(func.count()).select_from(statement.subquery())).scalar_one())
