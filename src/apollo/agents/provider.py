"""OpenAI-compatible provider construction with response normalisation.

The configured endpoint (``commandcode``) is OpenAI-compatible for chat but returns
``metadata`` values that are not strings (e.g. a list of ``weight_versions``). The
OpenAI SDK types ``metadata`` as ``dict[str, str]`` and rejects those responses, so
Apollo inserts a tiny transport adapter that drops the non-conforming ``metadata``
object from ``/chat/completions`` JSON responses. Streaming responses are passed
through untouched.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic_ai.providers.openai import OpenAIProvider

from apollo.config import Settings


class NormalizingTransport(httpx.AsyncBaseTransport):
    """Delegating transport that strips response fields the SDK types reject."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not _should_normalize(request):
            return await self._inner.handle_async_request(request)

        response = await self._inner.handle_async_request(request)
        await response.aread()
        body = response.content  # already decoded by httpx (content-encoding applied)
        await response.aclose()

        normalized = _normalize_json(body)
        headers = httpx.Headers(response.headers)
        for header in ("content-length", "content-encoding", "transfer-encoding"):
            headers.pop(header, None)
        return httpx.Response(
            status_code=response.status_code,
            headers=headers,
            content=normalized if normalized is not None else body,
            request=request,
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


def _should_normalize(request: httpx.Request) -> bool:
    if request.method != "POST" or "/chat/completions" not in request.url.path:
        return False
    try:
        payload = json.loads(request.content or b"{}")
    except ValueError:
        return False
    return not payload.get("stream", False)


def _normalize_json(body: bytes) -> bytes | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    changed = False
    metadata = data.get("metadata")
    if metadata is not None and not _is_str_map(metadata):
        data.pop("metadata", None)
        changed = True
    for choice in data.get("choices", []) or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if (
            isinstance(message, dict)
            and message.get("metadata") is not None
            and not _is_str_map(message.get("metadata"))
        ):
            message.pop("metadata", None)
            changed = True
    if not changed:
        return None
    return json.dumps(data).encode("utf-8")


def _is_str_map(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    return all(isinstance(v, str) for v in value.values())


def build_provider(settings: Settings) -> OpenAIProvider:
    base_url = settings.provider.base_url
    if not base_url:
        raise RuntimeError("APOLLO_PROVIDER__BASE_URL is unset")
    http_client = httpx.AsyncClient(transport=NormalizingTransport(), timeout=httpx.Timeout(120.0))
    return OpenAIProvider(
        base_url=base_url,
        api_key=settings.provider.api_key or None,
        http_client=http_client,
    )
