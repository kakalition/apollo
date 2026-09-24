"""Memory facade.

``Memory`` is the only interface agents and jobs use; the concrete backend
(Mem0 over Chroma, or an in-memory fake for tests) is selected by config. Writes
happen only inside the worker (``memory.add`` jobs) to bound cost and latency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session


@dataclass(slots=True)
class MemoryItem:
    id: str | None
    text: str
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Memory(Protocol):
    def remember(self, text: str, *, metadata: dict[str, Any] | None = None) -> str | None: ...

    def recall(self, query: str, *, k: int = 6) -> list[MemoryItem]: ...

    def forget(self, memory_id: str) -> None: ...

    def reindex(self, session: Session) -> int: ...


class InMemoryMemory:
    """Deterministic lexical memory used by tests and as a graceful fallback."""

    def __init__(self, user_id: str = "apollo") -> None:
        self.user_id = user_id
        self._items: list[MemoryItem] = []

    def remember(self, text: str, *, metadata: dict[str, Any] | None = None) -> str | None:
        memory_id = str(len(self._items) + 1)
        self._items.append(MemoryItem(id=memory_id, text=text, metadata=metadata or {}))
        return memory_id

    def recall(self, query: str, *, k: int = 6) -> list[MemoryItem]:
        terms = {t.lower() for t in query.split() if t.strip()}
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._items:
            words = {w.strip(".,!?;:").lower() for w in item.text.split()}
            overlap = len(terms & words)
            if overlap:
                scored.append((overlap / max(len(terms), 1), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results: list[MemoryItem] = []
        for score, item in scored[:k]:
            results.append(MemoryItem(id=item.id, text=item.text, score=score, metadata=item.metadata))
        return results

    def forget(self, memory_id: str) -> None:
        self._items = [item for item in self._items if item.id != memory_id]

    def reindex(self, session: Session) -> int:  # pragma: no cover - nothing to rebuild
        return 0


def build_memory(runtime: Any) -> Memory:
    """Select the configured backend, degrading to in-memory if unavailable."""
    settings = runtime.settings
    if not settings.memory.enabled:
        return InMemoryMemory()
    try:
        from apollo.memory.mem0_backend import Mem0Memory

        return Mem0Memory.from_settings(settings)
    except Exception as exc:
        from apollo.observability import get_logger

        get_logger("apollo.memory").warning(
            "memory.backend_unavailable",
            error=str(exc),
            detail="falling back to in-memory memory (not durable)",
        )
        return InMemoryMemory()
