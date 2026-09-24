"""Streaming agent replies to Telegram with Stop support.

``sendMessageDraft`` previews expire in ~30s, so a stable per-run ``draft_id`` is
refreshed while tokens arrive; the final result is persisted with ``sendMessage`` /
``sendRichMessage``. ``stopped_message_generation`` cancels the in-flight run.

Cancellation is cross-process (the bot receives the update, the worker runs the
agent), so it goes through the DB: the bot writes a flag, the streaming sink polls
it between deltas.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.streaming")

DRAFT_TTL_SECONDS = 25
CANCEL_KEY_PREFIX = "cancel:"


class RunCancelled(Exception):
    """Raised when the user taps Stop on a streaming reply."""


class RunCancellation:
    """In-process cancellation events (used by tests and same-process runs)."""

    _events: ClassVar[dict[int, asyncio.Event]] = {}

    @classmethod
    def register(cls, draft_id: int) -> asyncio.Event:
        event = asyncio.Event()
        cls._events[draft_id] = event
        return event

    @classmethod
    def cancel(cls, draft_id: int) -> bool:
        event = cls._events.get(draft_id)
        if event is None:
            return False
        event.set()
        return True

    @classmethod
    def clear(cls, draft_id: int) -> None:
        cls._events.pop(draft_id, None)


def request_cancel(runtime: Runtime, draft_id: int) -> None:
    """Record a Stop request durably (called by the bot process)."""
    from apollo.db.repositories import infra

    with runtime.db.write() as session:
        infra.set_setting(session, f"{CANCEL_KEY_PREFIX}{draft_id}", {"cancelled": True})


def cancel_requested(runtime: Runtime, draft_id: int) -> bool:
    from apollo.db.repositories import infra

    with runtime.db.session() as session:
        data = infra.get_setting(session, f"{CANCEL_KEY_PREFIX}{draft_id}")
    return bool(data and data.get("cancelled"))


def clear_cancel(runtime: Runtime, draft_id: int) -> None:
    from apollo.db.repositories import infra

    with runtime.db.write() as session:
        infra.delete_setting(session, f"{CANCEL_KEY_PREFIX}{draft_id}")


class TelegramDraftSink:
    def __init__(
        self,
        api: TelegramAPI,
        *,
        chat_id: int,
        draft_id: int,
        message_thread_id: int | None = None,
        can_stop: bool = True,
        refresh_seconds: float = DRAFT_TTL_SECONDS,
        runtime: Runtime | None = None,
    ) -> None:
        self.api = api
        self.chat_id = chat_id
        self.draft_id = draft_id
        self.message_thread_id = message_thread_id
        self.can_stop = can_stop
        self.refresh_seconds = refresh_seconds
        self.runtime = runtime
        self._buffer = ""
        self._last_sent = 0.0
        self._event = RunCancellation.register(draft_id)

    @classmethod
    def from_spec(
        cls,
        spec: dict[str, Any],
        *,
        api: TelegramAPI | None = None,
        runtime: Runtime | None = None,
    ) -> TelegramDraftSink:
        if api is None:
            from apollo.config import load_settings

            settings = runtime.settings if runtime is not None else load_settings()
            token = settings.telegram.bot_token
            if not token:
                raise RuntimeError("telegram token unset; cannot stream")
            api = TelegramAPI(token)
        return cls(
            api,
            chat_id=int(spec["chat_id"]),
            draft_id=int(spec["draft_id"]),
            message_thread_id=spec.get("message_thread_id"),
            can_stop=bool(spec.get("can_stop", True)),
            runtime=runtime,
        )

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (
            self.runtime is not None and cancel_requested(self.runtime, self.draft_id)
        )

    async def push(self, text: str) -> None:
        if self.cancelled:
            raise RunCancelled()
        self._buffer += text
        now = time.monotonic()
        if now - self._last_sent < 2.0 and len(self._buffer) < 200:
            return
        await self._send_draft()
        self._last_sent = now

    async def refresh(self) -> None:
        if self.cancelled:
            raise RunCancelled()
        if time.monotonic() - self._last_sent >= self.refresh_seconds:
            await self._send_draft()

    async def _send_draft(self) -> None:
        try:
            await self.api.send_message_draft(
                self.chat_id,
                self.draft_id,
                self._buffer[-4000:],
                message_thread_id=self.message_thread_id,
                can_stop=self.can_stop,
            )
        except Exception as exc:
            log.warning("streaming.draft_failed", error=str(exc))

    async def finish(self, final_text: str) -> None:
        RunCancellation.clear(self.draft_id)
        if self.runtime is not None:
            clear_cancel(self.runtime, self.draft_id)
        await self.api.aclose()

    async def cancel(self) -> None:
        RunCancellation.clear(self.draft_id)
        if self.runtime is not None:
            clear_cancel(self.runtime, self.draft_id)
        await self.api.aclose()
