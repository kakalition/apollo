"""Private-chat topics as Apollo's information architecture.

Topics are created once per domain area and every inbound/outbound message is
routed by ``message_thread_id``. ``has_topics_enabled`` is read from ``getMe`` (the
bot ``User``), not from the chat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from apollo.db.repositories import infra
from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI

log = get_logger("apollo.telegram.topics")

TOPICS_KEY = "telegram_topics"


@dataclass(frozen=True, slots=True)
class Topic:
    slug: str
    name: str
    purpose: str


TOPICS: list[Topic] = [
    Topic("inbox", "📥 Inbox", "Capture anything; unfiled tasks land here."),
    Topic("goals", "🎯 Goals", "Goal dashboards and decomposition plans."),
    Topic("practices", "🔁 Practices & Habits", "Cadence, streaks and habit prompts."),
    Topic("today", "✅ Today", "Today's focus and check-ins."),
    Topic("metrics", "📊 Metrics", "Metric trends and targets."),
    Topic("journal", "📝 Journal", "Notes and journal entries."),
    Topic("reviews", "🪞 Reviews", "Daily/weekly/monthly reviews."),
    Topic("memory", "🧠 Memory", "Recall and memory maintenance."),
    Topic("system", "⚙️ System", "Approvals, errors, job status."),
]

TOPIC_BY_SLUG = {t.slug: t for t in TOPICS}


class TopicRouter:
    """Maps topic slug ↔ ``message_thread_id`` using persisted state."""

    def __init__(self, chat_id: int | None = None, threads: dict[str, int] | None = None) -> None:
        self.chat_id = chat_id
        self.threads: dict[str, int] = dict(threads or {})

    @classmethod
    def load(cls, session: Session) -> TopicRouter:
        data = infra.get_setting(session, TOPICS_KEY) or {}
        return cls(chat_id=data.get("chat_id"), threads=data.get("threads") or {})

    def save(self, session: Session) -> None:
        infra.set_setting(session, TOPICS_KEY, {"chat_id": self.chat_id, "threads": self.threads})

    def thread_for(self, slug: str) -> int | None:
        return self.threads.get(slug)

    def slug_for_thread(self, thread_id: int | None) -> str | None:
        if thread_id is None:
            return None
        for slug, value in self.threads.items():
            if value == thread_id:
                return slug
        return None

    @property
    def provisioned(self) -> bool:
        return bool(self.threads)


async def provision_topics(
    api: TelegramAPI, chat_id: int, session: Session, *, force: bool = False
) -> TopicRouter:
    """Create missing topics and persist their thread ids."""
    router = TopicRouter.load(session)
    router.chat_id = chat_id
    if router.threads and not force:
        return router
    for topic in TOPICS:
        if topic.slug in router.threads and not force:
            continue
        result = await api.create_forum_topic(chat_id, topic.name)
        raw_thread_id = result.get("message_thread_id") if isinstance(result, dict) else None
        if raw_thread_id is None:
            log.warning("telegram.topic_missing_thread_id", slug=topic.slug)
            continue
        thread_id = int(raw_thread_id)
        router.threads[topic.slug] = thread_id
        log.info("telegram.topic_created", slug=topic.slug, thread_id=thread_id)
    router.save(session)
    return router


def topics_disabled_message(username: str | None) -> str:
    who = f"@{username}" if username else "your bot"
    return (
        "Topics in private chats are disabled for this bot.\n"
        f"Open @BotFather → /mybots → {who} → Bot Settings → "
        "Topics in Private Chats → Enable, then restart `apollo telegram`.\n"
        "Apollo will not silently fall back to a single chat."
    )


def topic_summary() -> list[dict[str, Any]]:
    return [{"slug": t.slug, "name": t.name, "purpose": t.purpose} for t in TOPICS]
