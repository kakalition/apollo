"""Planner specialist: goal decomposition into practice/projects/tasks.

Tool-free like triage: the model emits one nested ``PlanResult`` and Apollo wires the
parents. A compact reference block (existing goal ids, open tasks) is injected into
the instructions so no read tools are needed — that keeps planning to a single model
call instead of a tool-call loop.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import PLANNER
from apollo.config import Settings
from apollo.domain.commands import PlanResult
from apollo.domain.models import GoalStatus, TaskStatus


def _reference_block(ctx: RunContext[Context]) -> str:
    from apollo.db.repositories import domain as repo

    with ctx.deps.read() as session:
        goals = repo.list_goals(session, status=GoalStatus.ACTIVE)[:20]
        open_tasks = repo.list_tasks(session, status=TaskStatus.TODO)[:10]
    lines = []
    if goals:
        lines.append("existing goals (reuse an id instead of creating a duplicate):")
        lines.extend(f"  #{g.id} {g.title}" for g in goals)
    if open_tasks:
        lines.append("open tasks (do not duplicate):")
        lines.extend(f"  #{task.id} {task.title}" for task in open_tasks)
    if not lines:
        return "No goals or open tasks yet."
    return "\n".join(lines)


def _instructions(ctx: RunContext[Context]) -> str:
    return f"{PLANNER}\n\n{_reference_block(ctx)}"


def build_planner(settings: Settings, model: Any | None = None) -> Agent[Context, PlanResult]:
    return Agent(
        model or build_model(settings, "plan"),
        output_type=PlanResult,
        deps_type=Context,
        name="planner",
        instructions=_instructions,
        retries=2,
    )
