"""Telegram bot entrypoint: long polling, allowlist, topics, command/menu setup.

The update loop is Apollo's own so that Bot API 10.x update types
(``stopped_message_generation``, ``poll_answer``, ``inline_query``) are handled with
the exact ``allowed_updates`` we need. python-telegram-bot remains the pinned
dependency for application-level helpers and future re-integration, but all wire
calls go through the typed layer in :mod:`apollo.telegram.api`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from apollo.bootstrap import bootstrap
from apollo.observability import configure_from_settings, get_logger
from apollo.telegram.api import TelegramAPI, TelegramError
from apollo.telegram.handlers import dispatch
from apollo.telegram.models import BotCommand
from apollo.telegram.outbox_drain import NotificationDrainer
from apollo.telegram.topics import TopicRouter, provision_topics, topics_disabled_message

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.bot")

ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
    "poll_answer",
    "inline_query",
    "stopped_message_generation",
]

COMMANDS = [
    BotCommand(command="start", description="Start Apollo"),
    BotCommand(command="help", description="How to use Apollo"),
    BotCommand(command="today", description="Today's briefing"),
    BotCommand(command="capture", description="Capture a task or note"),
    BotCommand(command="log", description="Log a check-in"),
    BotCommand(command="goals", description="List goals"),
    BotCommand(command="practices", description="List practices"),
    BotCommand(command="habits", description="List habits"),
    BotCommand(command="review", description="Latest review"),
    BotCommand(command="focus", description="What to do now"),
    BotCommand(command="memory", description="Memory status"),
    BotCommand(command="skills", description="List skills"),
    BotCommand(command="approve", description="Pending approvals"),
    BotCommand(command="pause", description="Pause jobs"),
    BotCommand(command="resume", description="Resume jobs"),
    BotCommand(command="settings", description="Show settings"),
]

DRAIN_INTERVAL_SECONDS = 5.0


class ApolloBot:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        settings = runtime.settings
        if not settings.telegram.bot_token:
            raise SystemExit("APOLLO_TELEGRAM__BOT_TOKEN is unset; see .env.example")
        self.api = TelegramAPI(settings.telegram.bot_token)
        self.allowlist = set(settings.telegram.allowed_user_ids)
        self.router = TopicRouter()
        self.chat_id: int | None = next(iter(self.allowlist), None)
        self._stop = asyncio.Event()

    async def start(self) -> None:
        settings = self.runtime.settings
        me = await self.api.get_me()
        log.info("telegram.connected", username=me.username, id=me.id)

        if settings.telegram.topic_routing and me.has_topics_enabled is False:
            raise SystemExit(topics_disabled_message(me.username))

        if not self.allowlist:
            log.warning("telegram.no_allowlist", detail="set APOLLO_TELEGRAM__ALLOWED_USER_IDS")

        if self.chat_id is not None:
            with self.runtime.db.write() as session:
                self.router = await provision_topics(self.api, self.chat_id, session)
                session.commit()

        await self._configure_profile(me.username or "Apollo")
        await self._configure_commands()

        await asyncio.gather(self._poll_loop(), self._drain_loop())

    async def stop(self) -> None:
        self._stop.set()

    # -- setup -------------------------------------------------------------
    async def _configure_profile(self, username: str) -> None:
        with contextlib.suppress(TelegramError):
            await self.api.set_my_name("Apollo")
        with contextlib.suppress(TelegramError):
            await self.api.set_my_short_description("Local-first personal agent.")
        with contextlib.suppress(TelegramError):
            await self.api.set_my_description(
                "Apollo keeps your goals, practices and reviews in one local system and "
                "messages you when it is time to move."
            )
        with contextlib.suppress(TelegramError):
            await self.api.set_chat_menu_button(menu_button={"type": "commands"})

    async def _configure_commands(self) -> None:
        with contextlib.suppress(TelegramError):
            await self.api.set_my_commands(COMMANDS)

    # -- loops -------------------------------------------------------------
    async def _poll_loop(self) -> None:
        offset: int | None = None
        timeout = self.runtime.settings.telegram.poll_timeout
        while not self._stop.is_set():
            try:
                updates = await self.api.get_updates(
                    offset=offset, timeout=timeout, allowed_updates=ALLOWED_UPDATES
                )
            except TelegramError as exc:
                if exc.is_rate_limited:
                    await asyncio.sleep(float(exc.retry_after or 3))
                    continue
                log.warning("telegram.poll_error", error=str(exc))
                await asyncio.sleep(3)
                continue
            except Exception as exc:
                log.warning("telegram.poll_error", error=str(exc))
                await asyncio.sleep(3)
                continue
            for update in updates:
                offset = update.update_id + 1
                await self._handle(update)

    async def _handle(self, update: object) -> None:
        update_model = update  # already an Update
        user_id = _user_id(update_model)
        if user_id is not None and self.allowlist and user_id not in self.allowlist:
            log.info("telegram.rejected", user_id=user_id)
            return
        try:
            await dispatch(self.runtime, self.api, update_model, self.router)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("telegram.dispatch_failed", error=str(exc))

    async def _drain_loop(self) -> None:
        if self.chat_id is None:
            return
        drainer = NotificationDrainer(self.api, self.runtime, chat_id=self.chat_id)
        while not self._stop.is_set():
            try:
                await drainer.drain()
            except Exception as exc:
                log.warning("telegram.drain_failed", error=str(exc))
            await asyncio.sleep(DRAIN_INTERVAL_SECONDS)


def _user_id(update: object) -> int | None:
    for attr in ("message", "edited_message", "callback_query", "inline_query"):
        obj = getattr(update, attr, None)
        if obj is not None:
            user = getattr(obj, "from_user", None) or getattr(obj, "user", None)
            if user is not None:
                return int(user.id)
    stopped = getattr(update, "stopped_message_generation", None)
    if stopped is not None:
        return None
    return None


async def run_bot() -> None:
    runtime = bootstrap()
    configure_from_settings(runtime.settings)
    bot = ApolloBot(runtime)
    try:
        await bot.start()
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        await bot.stop()
    finally:
        await bot.api.aclose()
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(run_bot())
