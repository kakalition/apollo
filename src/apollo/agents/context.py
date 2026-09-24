"""Agent dependency context.

Every agent run receives one ``Context``. Handlers/agents open short-lived
sessions through ``ctx.read()`` / ``ctx.write()`` so a slow model call never holds
the SQLite write lock.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from apollo.memory.facade import Memory
from apollo.skills.registry import SkillRegistry
from apollo.tools.clock import Clock

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime
    from apollo.mcp.registry import MCPRegistry


@dataclass(slots=True)
class Context:
    runtime: Runtime
    clock: Clock
    memory: Memory
    skills: SkillRegistry
    mcp: MCPRegistry
    run_id: str
    actor: str = "agent"
    topic: str | None = None
    telegram_user_id: int | None = None
    conversation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self.runtime.db.session() as session:
            yield session

    @contextmanager
    def write(self) -> Iterator[Session]:
        with self.runtime.db.write() as session:
            yield session

    @property
    def settings(self) -> Any:
        return self.runtime.settings
