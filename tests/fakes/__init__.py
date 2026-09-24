"""Shared test fakes: Telegram transport, deterministic models, memory."""

from __future__ import annotations

from typing import Any

import httpx

from apollo.memory.facade import InMemoryMemory


class FakeTelegram:
    """Records method calls and returns canned successful results."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}
        self.closed = False

    async def call(self, method: str, **params: Any) -> Any:
        self.calls.append((method, params))
        if method in self.results:
            return self.results[method]
        if method == "getMe":
            return {"id": 1, "is_bot": True, "username": "apollo_bot", "has_topics_enabled": True}
        if method == "sendMessage":
            return {"message_id": len(self.calls), "chat": {"id": params.get("chat_id", 1), "type": "private"}}
        if method == "sendPoll":
            return {
                "message_id": len(self.calls),
                "chat": {"id": params.get("chat_id", 1), "type": "private"},
                "poll": {"id": "p1", "question": params.get("question", ""), "options": [], "is_anonymous": False},
            }
        if method == "createForumTopic":
            return {"message_thread_id": 100 + len(self.calls)}
        return True

    def method_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def calls_of(self, method: str) -> list[dict[str, Any]]:
        return [params for name, params in self.calls if name == method]


def fake_api(handler: Any | None = None, results: dict[str, Any] | None = None) -> Any:
    """Build a TelegramAPI whose HTTP transport is mocked.

    ``handler(request) -> httpx.Response`` overrides the default ok response.
    """
    from apollo.telegram.api import TelegramAPI

    def default(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        message = {"message_id": 1, "chat": {"id": 1, "type": "private"}}
        defaults: dict[str, Any] = {
            "getMe": {
                "id": 1,
                "is_bot": True,
                "username": "apollo_bot",
                "has_topics_enabled": True,
            },
            "sendMessage": message,
            "sendRichMessage": message,
            "sendVoice": message,
            "sendChecklist": message,
            "sendPoll": {**message, "poll": {"id": "p1", "question": "q", "options": []}},
        }
        result = (results or {}).get(method, defaults.get(method, True))
        return httpx.Response(200, json={"ok": True, "result": result})

    transport = httpx.MockTransport(handler or default)
    return TelegramAPI("test-token", transport=transport)


__all__ = ["FakeTelegram", "InMemoryMemory", "fake_api"]
