"""Mem0 backend over a local Chroma **server**.

The vector store is Chroma running as a separate process (``chroma run``) because
embedded/local vector stores take an exclusive file lock and are single-process
only — incompatible with Apollo's split-process architecture. Do not substitute an
embedded store.

Embeddings use the OpenAI-compatible ``/embeddings`` endpoint when the primary
provider serves one; otherwise the configured fallback (a second provider, or local
``fastembed``) is used. Selection is config-driven, not code-driven.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apollo.config import Settings
from apollo.memory.facade import MemoryItem
from apollo.observability import get_logger

log = get_logger("apollo.memory.mem0")


def embedder_config(settings: Settings) -> dict[str, Any]:
    """Return a Mem0 embedder config according to the configured fallback chain."""
    if settings.provider.embedding_model_id:
        return {
            "provider": "openai",
            "config": {
                "model": settings.provider.embedding_model_id,
                "api_key": settings.embeddings.api_key or settings.provider.api_key,
                "openai_base_url": settings.embeddings.base_url or settings.provider.base_url,
            },
        }
    if settings.embeddings.base_url or settings.embeddings.fallback == "provider":
        base = settings.embeddings.base_url or settings.provider.base_url
        return {
            "provider": "openai",
            "config": {
                "model": settings.embeddings.model,
                "api_key": settings.embeddings.api_key or settings.provider.api_key,
                "openai_base_url": base,
            },
        }
    # Local fastembed via the HuggingFace embedder path.
    return {
        "provider": "huggingface",
        "config": {"model": settings.embeddings.local_model},
    }


def build_mem0_config(settings: Settings) -> dict[str, Any]:
    host, port = _host_port(settings.memory.chroma_url)
    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": settings.memory.collection,
                "host": host,
                "port": port,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings.provider.model_for("memory"),
                "api_key": settings.provider.api_key,
                "openai_base_url": settings.provider.base_url,
            },
        },
        "embedder": embedder_config(settings),
    }


def _host_port(url: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or 8000


class Mem0Memory:
    def __init__(self, client: Any, *, user_id: str = "apollo", top_k: int = 6) -> None:
        self._client = client
        self.user_id = user_id
        self.top_k = top_k

    @classmethod
    def from_settings(cls, settings: Settings, *, user_id: str = "apollo") -> Mem0Memory:
        from mem0 import Memory as Mem0Client  # type: ignore[import-not-found]

        config = build_mem0_config(settings)
        client = Mem0Client.from_config(config)
        return cls(client, user_id=user_id, top_k=settings.memory.top_k)

    # -- Memory protocol ---------------------------------------------------
    def remember(self, text: str, *, metadata: dict[str, Any] | None = None) -> str | None:
        result = self._client.add(text, user_id=self.user_id, metadata=metadata or {})
        return _extract_id(result)

    def recall(self, query: str, *, k: int | None = None) -> list[MemoryItem]:
        # Mem0 >= 2.x rejects top-level entity params on search; use filters + top_k.
        raw = self._client.search(
            query, filters={"user_id": self.user_id}, top_k=k or self.top_k
        )
        return [_to_item(entry) for entry in _as_list(raw)]

    def forget(self, memory_id: str) -> None:
        self._client.delete(memory_id)

    def reindex(self, session: Session) -> int:
        """Rebuild memories from the durable sources (vault + DB)."""
        from apollo.memory.ingest import iter_ingestable

        count = 0
        for text, metadata in iter_ingestable(session):
            self._client.add(text, user_id=self.user_id, metadata=metadata)
            count += 1
        log.info("memory.reindexed", count=count)
        return count


def _as_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        for key in ("results", "memories"):
            if key in raw:
                return list(raw[key])
        return [raw]
    return list(raw)


def _to_item(entry: Any) -> MemoryItem:
    if isinstance(entry, dict):
        text = entry.get("memory") or entry.get("text") or entry.get("data") or ""
        return MemoryItem(
            id=str(entry.get("id")) if entry.get("id") is not None else None,
            text=str(text),
            score=entry.get("score"),
            metadata={k: v for k, v in entry.items() if k not in {"memory", "text", "data", "score", "id"}},
        )
    return MemoryItem(id=None, text=str(entry))


def _extract_id(result: Any) -> str | None:
    for entry in _as_list(result):
        if isinstance(entry, dict) and entry.get("id") is not None:
            return str(entry["id"])
    return None
