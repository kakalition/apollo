"""Typed raw-method layer: exact payloads for Bot API 10.x methods and error handling."""

from __future__ import annotations

import asyncio
import json

import httpx

from apollo.telegram.api import TelegramAPI, TelegramError


def _api(captured: list[dict], response: dict | None = None) -> TelegramAPI:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"path": request.url.path, "json": json.loads(request.content or b"{}")})
        if response is not None and "ok" in response:
            return httpx.Response(200, json=response)
        result = response or {"message_id": 1, "chat": {"id": 1, "type": "private"}}
        return httpx.Response(200, json={"ok": True, "result": result})

    return TelegramAPI("token", transport=httpx.MockTransport(handler))


def test_send_message_draft_exact_params() -> None:
    captured: list[dict] = []
    api = _api(captured, {"ok": True, "result": True})

    async def run() -> None:
        await api.send_message_draft(
            5, 99, "Thinking", message_thread_id=7, can_stop=True, keep_on_stop=False
        )
        await api.aclose()

    asyncio.run(run())
    payload = captured[0]["json"]
    assert captured[0]["path"].endswith("sendMessageDraft")
    assert payload == {
        "chat_id": 5,
        "message_thread_id": 7,
        "draft_id": 99,
        "text": "Thinking",
        "can_stop": True,
        "keep_on_stop": False,
    }


def test_send_rich_message_wraps_rich_message() -> None:
    captured: list[dict] = []
    api = _api(captured)

    async def run() -> None:
        await api.send_rich_message(5, {"blocks": [{"type": "paragraph", "text": "hi"}]}, message_thread_id=3)
        await api.aclose()

    asyncio.run(run())
    payload = captured[0]["json"]
    assert captured[0]["path"].endswith("sendRichMessage")
    assert payload["rich_message"] == {"blocks": [{"type": "paragraph", "text": "hi"}]}


def test_send_poll_uses_plural_zero_based_correct_ids() -> None:
    captured: list[dict] = []
    api = _api(captured, {"ok": True, "result": {"message_id": 1, "chat": {"id": 1, "type": "private"}, "poll": {"id": "p", "question": "q", "options": []}}})

    async def run() -> None:
        await api.send_poll(1, "Did you run?", ["Yes", "No"], type="quiz", correct_option_ids=[0])
        await api.aclose()

    asyncio.run(run())
    payload = captured[0]["json"]
    assert payload["correct_option_ids"] == [0]
    assert payload["type"] == "quiz"
    assert payload["is_anonymous"] is False


def test_rate_limit_error_exposes_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}},
        )

    api = TelegramAPI("token", transport=httpx.MockTransport(handler))

    async def run() -> TelegramError:
        try:
            await api.send_message(1, "x")
        except TelegramError as exc:
            return exc
        finally:
            await api.aclose()
        raise AssertionError("expected error")

    error = asyncio.run(run())
    assert error.is_rate_limited and error.retry_after == 7


def test_send_checklist_carries_business_connection() -> None:
    captured: list[dict] = []
    api = _api(captured)

    async def run() -> None:
        await api.send_checklist(1, {"title": "Day"}, business_connection_id="bc1")
        await api.aclose()

    asyncio.run(run())
    payload = captured[0]["json"]
    assert payload["business_connection_id"] == "bc1"


def test_get_me_reads_topics_flags_on_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "id": 1,
                    "is_bot": True,
                    "username": "apollo_bot",
                    "has_topics_enabled": True,
                    "allows_users_to_create_topics": True,
                },
            },
        )

    api = TelegramAPI("token", transport=httpx.MockTransport(handler))

    async def run() -> None:
        me = await api.get_me()
        await api.aclose()
        assert me.has_topics_enabled is True
        assert me.allows_users_to_create_topics is True

    asyncio.run(run())
