"""Notifier: the only sanctioned way for agents/jobs to message the user.

It writes to the ``notifications`` outbox; the Telegram process (or another
transport) drains it. This keeps sends idempotent and keeps quiet-hours buffering
in the scheduler/transport layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from apollo.db.repositories import infra

TOPIC_SYSTEM = "system"


class Notifier:
    def __init__(self, session: Session, *, default_topic: str = TOPIC_SYSTEM) -> None:
        self.session = session
        self.default_topic = default_topic

    def send(
        self,
        text: str,
        *,
        topic: str | None = None,
        kind: str = "generic",
        ref_id: str | None = None,
        period: str | None = None,
        urgent: bool = False,
        scheduled_for: datetime | None = None,
        rich: dict[str, Any] | None = None,
        buttons: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "text": text,
            "topic": topic or self.default_topic,
        }
        if rich:
            payload["rich"] = rich
        if buttons:
            payload["buttons"] = buttons
        if actions:
            payload["actions"] = actions
        row = infra.enqueue_notification(
            self.session,
            kind=kind,
            ref_id=ref_id,
            period=period,
            payload=payload,
            urgent=urgent,
            scheduled_for=scheduled_for,
        )
        return int(row.id or 0)
