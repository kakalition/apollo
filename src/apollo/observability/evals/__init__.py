"""Eval tasks and (offline) dataset smoke checks are wired here."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apollo.observability.evals.suites import (
    all_datasets,
    approval_routing_dataset,
    review_synthesis_dataset,
    skill_selection_dataset,
    triage_dataset,
)

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

__all__ = [
    "all_datasets",
    "approval_routing_dataset",
    "review_synthesis_dataset",
    "skill_selection_dataset",
    "triage_dataset",
]


async def triage_intent_task(runtime: Runtime, text: str) -> str:
    """Live task: route through the triage agent and return the first command kind."""
    from apollo.agents.runtime import build_context, run_agent

    context = build_context(runtime)
    result = await run_agent(context, "triage", text)
    output = result.output
    items = getattr(output, "items", []) or []
    if not items:
        return "none"
    if len(items) > 1:
        kinds = {i.kind for i in items}
        return next(iter(kinds)) + "s" if len(kinds) == 1 else "mixed"
    return items[0].kind


async def skill_selection_task(runtime: Runtime, text: str) -> str:
    """Live task: supervisor → chosen skill by trigger match, falling back to name."""
    from apollo.agents.runtime import build_context, route_message

    context = build_context(runtime)
    decision = await route_message(context, text)
    matches = context.skills.match_trigger(f"user:{decision.intent}")
    return matches[0].name if matches else decision.specialist


def make_offline_task(mapping: dict[str, str]) -> Any:
    """A deterministic stand-in used to smoke-test dataset wiring without a model."""

    def task(text: str) -> str:
        return mapping.get(text, "none")

    return task
