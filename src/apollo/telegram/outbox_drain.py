"""Drain the notifications outbox to Telegram.

Handles per-chat rate limiting, HTTP 429 ``retry_after`` backoff, quiet-hours
buffering, idempotency (enforced at enqueue time by ``(kind, ref_id, period)``) and
topic routing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from apollo.db.repositories import infra
from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI, TelegramError
from apollo.telegram.keyboards import approval_keyboard, inline_keyboard
from apollo.telegram.markdown import to_telegram_html
from apollo.telegram.render import chunk
from apollo.telegram.topics import TopicRouter
from apollo.tools.clock import Clock

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.outbox")

RATE_LIMIT_SECONDS = 1.0


class NotificationDrainer:
    def __init__(self, api: TelegramAPI, runtime: Runtime, *, chat_id: int) -> None:
        self.api = api
        self.runtime = runtime
        self.chat_id = chat_id
        self._last_send = 0.0

    async def drain(self, *, limit: int = 20, clock: Clock | None = None) -> int:
        clock = clock or _system_clock(self.runtime)
        sent = 0
        while True:
            with self.runtime.db.write() as session:
                rows = infra.claim_notifications(session, clock.now(), limit=limit)
            if not rows:
                break
            for row in rows:
                if await self._deliver(row, clock):
                    sent += 1
        return sent

    async def _deliver(self, row: Any, clock: Clock) -> bool:
        payload: dict[str, Any] = row.payload_json or {}
        now = clock.now()
        if not row.urgent and self._in_quiet_hours(now, clock):
            self._reschedule(row.id, self._quiet_end(now, clock))
            return False

        text = str(payload.get("text") or "")
        fmt = str(payload.get("format") or "markdown")
        markup = None
        if payload.get("actions"):
            markup = approval_keyboard(int(payload["actions"][0].get("approval_id", 0)))
        elif payload.get("buttons"):
            markup = inline_keyboard(
                [
                    [
                        {k: v for k, v in b.items() if v is not None}
                        for b in row_buttons
                    ]
                    for row_buttons in payload["buttons"]
                ]
            )

        await self._throttle()
        topic_slug = payload.get("topic")
        thread_id: int | None = None
        if self.runtime.settings.telegram.topic_routing and topic_slug:
            with self.runtime.db.session() as session:
                thread_id = TopicRouter.load(session).thread_for(str(topic_slug))

        # Markdown from agents is converted to safe HTML; hand-built HTML passes
        # through; anything else is sent as plain text.
        parts = chunk(text)
        try:
            for index, part in enumerate(parts):
                outgoing = to_telegram_html(part) if fmt == "markdown" else part
                await self.api.send_message(
                    self.chat_id,
                    outgoing,
                    message_thread_id=thread_id,
                    parse_mode="HTML" if fmt in ("markdown", "html") else None,
                    reply_markup=markup if index == len(parts) - 1 else None,
                )
        except TelegramError as exc:
            if exc.is_rate_limited:
                delay = float(exc.retry_after or 5)
                log.warning("outbox.rate_limited", delay=delay)
                await asyncio.sleep(delay)
                self._mark(row.id, sent=False, error=str(exc))
                return False
            self._mark(row.id, sent=False, error=str(exc))
            log.warning("outbox.send_failed", error=str(exc))
            return False
        self._mark(row.id, sent=True)
        return True

    def _mark(self, notification_id: int, *, sent: bool, error: str | None = None) -> None:
        with self.runtime.db.write() as session:
            if sent:
                infra.mark_sent(session, notification_id)
            else:
                infra.mark_failed(session, notification_id, error or "unknown", retry=True)

    def _reschedule(self, notification_id: int, when: datetime) -> None:
        with self.runtime.db.write() as session:
            from apollo.db import tables as t

            row = session.get(t.Notification, notification_id)
            if row is not None:
                row.status = "pending"
                row.scheduled_for = when
                session.flush()

    async def _throttle(self) -> None:
        loop = asyncio.get_event_loop()
        now = loop.time()
        wait = RATE_LIMIT_SECONDS - (now - self._last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_send = loop.time()

    def _in_quiet_hours(self, now: datetime, clock: Clock) -> bool:
        local = clock.local(now).time()
        start, end = _quiet_bounds(self.runtime.settings.telegram.quiet_hours)
        if start <= end:
            return start <= local < end
        return local >= start or local < end

    def _quiet_end(self, now: datetime, clock: Clock) -> datetime:
        _, end = _quiet_bounds(self.runtime.settings.telegram.quiet_hours)
        local = clock.local(now)
        candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate


def _quiet_bounds(spec: dict[str, str]) -> tuple[time, time]:
    return _parse_time(spec.get("start", "22:00")), _parse_time(spec.get("end", "07:00"))


def _parse_time(value: str) -> time:
    hours, _, minutes = value.partition(":")
    return time(int(hours), int(minutes or 0))


def _system_clock(runtime: Runtime) -> Clock:
    from apollo.tools.clock import SystemClock

    return SystemClock(runtime.settings.app.timezone)
