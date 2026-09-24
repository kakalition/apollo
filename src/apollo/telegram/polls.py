"""Polls for check-ins and reviews, and ``poll_answer`` → CheckIn/Metric mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apollo.db.repositories import infra
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI
from apollo.telegram.models import PollAnswer
from apollo.tools.clock import Clock

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.polls")

POLL_KEY_PREFIX = "poll:"
RATING_OPTIONS = ["1", "2", "3", "4", "5"]


def record_poll_answer(runtime: Runtime, answer: PollAnswer, clock: Clock) -> str:
    """Map a ``poll_answer`` update to a CheckIn or Metric row."""
    with runtime.db.session() as session:
        meta = infra.get_setting(session, f"{POLL_KEY_PREFIX}{answer.poll_id}") or {}
    kind = meta.get("kind")
    ref_id = meta.get("ref_id")
    option = (answer.option_ids or [0])[0]
    if kind == "metric" and ref_id is not None:
        with runtime.db.write() as session:
            logrepo.record_metric(
                session, int(ref_id), float(option + 1), occurred_at=clock.now(), source="poll"
            )
        return f"metric #{ref_id}"
    if kind == "habit" and ref_id is not None:
        with runtime.db.write() as session:
            logrepo.log_habit(session, int(ref_id), occurred_at=clock.now())
        return f"habit #{ref_id}"
    valid = {k.value for k in m.CheckInKind}
    with runtime.db.write() as session:
        logrepo.log_checkin(
            session,
            m.CheckIn(
                kind=m.CheckInKind(kind if kind in valid else "reflection"),
                ref_id=ref_id,
                value_num=float(option + 1),
                occurred_at=clock.now(),
                source="poll",
            ),
            actor="telegram",
        )
    return f"checkin ({kind or 'reflection'})"


class PollService:
    def __init__(self, api: TelegramAPI, runtime: Runtime) -> None:
        self.api = api
        self.runtime = runtime

    async def send_rating_poll(
        self,
        chat_id: int,
        question: str,
        *,
        checkin_kind: str,
        message_thread_id: int | None = None,
        ref_id: int | None = None,
        open_period: int = 3600,
    ) -> int:
        message = await self.api.send_poll(
            chat_id,
            question,
            RATING_OPTIONS,
            message_thread_id=message_thread_id,
            is_anonymous=False,
            allows_revoting=True,
            open_period=open_period,
        )
        poll_id = message.poll.id if message.poll else ""
        self._register(poll_id, {"kind": checkin_kind, "ref_id": ref_id})
        return message.message_id

    async def send_practice_quiz(
        self,
        chat_id: int,
        question: str,
        options: list[str],
        correct_ids: list[int],
        *,
        explanation: str,
        message_thread_id: int | None = None,
        ref_id: int | None = None,
    ) -> int:
        message = await self.api.send_poll(
            chat_id,
            question,
            options,
            message_thread_id=message_thread_id,
            is_anonymous=False,
            type="quiz",
            correct_option_ids=correct_ids,
            explanation=explanation,
            open_period=3600,
        )
        poll_id = message.poll.id if message.poll else ""
        self._register(poll_id, {"kind": "quiz", "ref_id": ref_id})
        return message.message_id

    def _register(self, poll_id: str, meta: dict[str, Any]) -> None:
        if not poll_id:
            return
        with self.runtime.db.write() as session:
            infra.set_setting(session, f"{POLL_KEY_PREFIX}{poll_id}", meta)

    def resolve(self, poll_id: str) -> dict[str, Any] | None:
        with self.runtime.db.session() as session:
            return infra.get_setting(session, f"{POLL_KEY_PREFIX}{poll_id}")

    def record_answer(self, answer: PollAnswer, clock: Clock) -> str:
        return record_poll_answer(self.runtime, answer, clock)

    async def close(self, chat_id: int, message_id: int) -> None:
        try:
            await self.api.stop_poll(chat_id, message_id)
        except Exception as exc:
            log.warning("poll.close_failed", error=str(exc))
