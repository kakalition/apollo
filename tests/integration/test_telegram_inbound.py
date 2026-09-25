"""Inbound Telegram routing without a network: commands, capture, callbacks."""

from __future__ import annotations

import asyncio
import base64

import httpx
from sqlalchemy import select

from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.domain import models as m
from apollo.telegram.api import TelegramAPI
from apollo.telegram.handlers import _decode_start, dispatch, enqueue_agent_run
from apollo.telegram.models import CallbackQuery, Message, Update
from apollo.telegram.topics import TopicRouter, provision_topics
from tests.fakes import fake_api


def test_decode_start_roundtrip() -> None:
    payload = base64.urlsafe_b64encode(b"water the plants").decode().rstrip("=")
    assert _decode_start(f"capture_{payload}") == "water the plants"
    assert _decode_start("capture") is None
    assert _decode_start("") is None


def test_enqueue_agent_run_attaches_topic_and_stream(runtime) -> None:
    runtime.settings.telegram.bot_token = "token"
    enqueue_agent_run(
        runtime, text="hello", topic="inbox", message_thread_id=12,
        telegram_user_id=42, agent="triage",
    )
    with runtime.db.session() as session:
        job = session.execute(select(t.Job)).scalars().first()
    assert job is not None and job.kind == "agent.run"
    assert job.payload_json["topic"] == "inbox"
    assert job.payload_json["stream"]["chat_id"] == 42


def test_free_text_message_enqueues_supervisor_run(runtime, clock) -> None:
    api = fake_api()
    router = TopicRouter(chat_id=42, threads={"inbox": 5})
    message = Message.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "K"},
            "message_thread_id": 5,
            "text": "buy dog food tomorrow",
        }
    )
    asyncio.run(dispatch(runtime, api, Update(update_id=1, message=message), router))
    with runtime.db.session() as session:
        job = session.execute(select(t.Job)).scalars().first()
    assert job is not None and job.payload_json["text"] == "buy dog food tomorrow"


def test_single_chat_mode_lets_supervisor_route(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    api = fake_api()
    message = Message.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "K"},
            "text": "what should I focus on today?",
        }
    )
    asyncio.run(dispatch(runtime, api, Update(update_id=1, message=message), TopicRouter()))
    with runtime.db.session() as session:
        job = session.execute(select(t.Job)).scalars().first()
    assert job is not None
    # No forced specialist and no topic: the supervisor decides.
    assert "agent" not in job.payload_json
    assert job.payload_json.get("topic") is None


def test_callback_done_completes_task(runtime) -> None:
    with runtime.db.write() as session:
        task = repo.create_task(session, m.Task(title="Pay rent"))
        assert task.id is not None
    api = fake_api()
    query = CallbackQuery.model_validate(
        {
            "id": "cb1",
            "from": {"id": 42, "first_name": "K"},
            "data": f"done:task:{task.id}",
            "message": {"message_id": 9, "chat": {"id": 42, "type": "private"}, "message_thread_id": 5},
        }
    )
    asyncio.run(dispatch(runtime, api, Update(update_id=2, callback_query=query), TopicRouter()))
    with runtime.db.session() as session:
        updated = repo.get_task(session, task.id)
    assert updated is not None and updated.status == m.TaskStatus.DONE


def test_provision_topics_persists_thread_ids(runtime) -> None:
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "createForumTopic":
            return httpx.Response(200, json={"ok": True, "result": {"message_thread_id": 100 + counter["n"]}})
        return httpx.Response(200, json={"ok": True, "result": True})

    api = TelegramAPI("token", transport=httpx.MockTransport(handler))

    async def run() -> TopicRouter:
        with runtime.db.write() as session:
            router = await provision_topics(api, 42, session)
            session.commit()
        await api.aclose()
        return router

    router = asyncio.run(run())
    assert len(router.threads) == 9
    assert router.thread_for("today") is not None
    with runtime.db.session() as session:
        reloaded = TopicRouter.load(session)
    assert reloaded.slug_for_thread(reloaded.thread_for("inbox")) == "inbox"


class _CapturingAPI:
    """Records outbound send_message payloads for command tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append({"chat_id": chat_id, "text": text, **kwargs})
        return None

    async def set_message_reaction(self, chat_id, message_id, reaction, **kwargs):
        self.calls.append({"reaction": reaction, "chat_id": chat_id, "message_id": message_id})
        return True


def _message(text: str) -> Message:
    return Message.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "K"},
            "text": text,
        }
    )


def test_start_help_renders_html_and_clears_keyboard(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    api = _CapturingAPI()
    asyncio.run(
        dispatch(runtime, api, Update(update_id=1, message=_message("/start")), TopicRouter())  # pyright: ignore[reportArgumentType]
    )
    assert api.calls, "expected a help reply"
    call = api.calls[0]
    assert call["parse_mode"] == "HTML"
    assert call["reply_markup"] == {"remove_keyboard": True}
    assert "<b>Apollo</b>" in call["text"]
    assert "topic" not in call["text"].lower()


def test_today_never_installs_a_reply_keyboard(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    api = _CapturingAPI()
    asyncio.run(
        dispatch(runtime, api, Update(update_id=1, message=_message("/today")), TopicRouter())  # pyright: ignore[reportArgumentType]
    )
    assert api.calls, "expected an acknowledgement"
    assert api.calls[0]["reply_markup"] is None
    with runtime.db.session() as session:
        jobs = list(session.execute(select(t.Job)).scalars())
    assert any(job.kind == "skill.run" for job in jobs)


def test_settings_clears_any_persistent_keyboard(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    api = _CapturingAPI()
    asyncio.run(
        dispatch(runtime, api, Update(update_id=1, message=_message("/settings")), TopicRouter())  # pyright: ignore[reportArgumentType]
    )
    assert api.calls, "expected a settings reply"
    assert api.calls[-1]["reply_markup"] == {"remove_keyboard": True}


def test_capture_ack_uses_a_valid_reaction_emoji(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    api = _CapturingAPI()
    asyncio.run(
        dispatch(runtime, api, Update(update_id=1, message=_message("buy milk")), TopicRouter())  # pyright: ignore[reportArgumentType]
    )
    reactions = [c for c in api.calls if "reaction" in c]
    assert reactions == [
        {"reaction": [{"type": "emoji", "emoji": "👍"}], "chat_id": 42, "message_id": 1}
    ]


def test_invalid_configured_ack_emoji_is_skipped(runtime) -> None:
    runtime.settings.telegram.topic_routing = False
    runtime.settings.telegram.ack_reaction = "✅"  # not a permitted reaction
    api = _CapturingAPI()
    asyncio.run(
        dispatch(runtime, api, Update(update_id=1, message=_message("buy milk")), TopicRouter())  # pyright: ignore[reportArgumentType]
    )
    assert not [c for c in api.calls if "reaction" in c]
