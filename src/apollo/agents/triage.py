"""Triage specialist: unstructured text → typed domain commands.

Triage is intentionally tool-free: it needs entity ids only to reference existing
habits/metrics, and those are injected into its instructions instead of being looked
up. That keeps a simple capture to a single model call.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import TRIAGE
from apollo.config import Settings
from apollo.domain.commands import CaptureResult
from apollo.domain.models import CheckInKind


def _reference_block(ctx: RunContext[Context]) -> str:
    """Compact id reference so triage never has to call a read tool."""
    from apollo.db.repositories import domain as repo
    from apollo.db.repositories import logs as logrepo

    with ctx.deps.read() as session:
        habits = repo.list_habits(session)[:20]
        metrics = repo.list_metrics(session)[:20]
        last = logrepo.last_checkin_in(session, CheckInKind.REFLECTION)
    lines: list[str] = [f"current time: {ctx.deps.clock.now().isoformat()}"]
    if habits:
        lines.append("habits: " + ", ".join(f"#{h.id} {h.name}" for h in habits))
    if metrics:
        lines.append("metrics: " + ", ".join(f"#{m.id} {m.name}" for m in metrics))
    if last is not None:
        lines.append(f"last reflection: {last.occurred_at:%Y-%m-%d}")
    if not lines:
        return "No habits or metrics exist yet — omit ref ids unless the user creates one."
    return "Reference ids (use these, never invent):\n" + "\n".join(lines)


def _instructions_with_refs(ctx: RunContext[Context]) -> str:
    # No skill summaries: capture does not need them, and every token costs latency.
    return f"{TRIAGE}\n\n{_reference_block(ctx)}"


def build_triage(settings: Settings, model: Any | None = None) -> Agent[Context, CaptureResult]:
    agent: Agent[Context, CaptureResult] = Agent(
        model or build_model(settings, "triage"),
        output_type=CaptureResult,
        deps_type=Context,
        name="triage",
        instructions=_instructions_with_refs,
        retries=2,
    )
    # No tools: commands only. Reference ids come from the instructions above.
    return agent
