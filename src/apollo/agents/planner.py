"""Planner specialist: goal decomposition, practice/project/task creation, replanning."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from apollo.agents import tools as toolset
from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import PLANNER, with_skills
from apollo.config import Settings
from apollo.domain.commands import CommandBatch


def _instructions(ctx: RunContext[Context]) -> str:
    return with_skills(PLANNER, ctx.deps.skills.summary_text() or "(none)")


def build_planner(settings: Settings, model: Any | None = None) -> Agent[Context, CommandBatch]:
    agent: Agent[Context, CommandBatch] = Agent(
        model or build_model(settings, "plan"),
        output_type=CommandBatch,
        deps_type=Context,
        name="planner",
        instructions=_instructions,
    )
    toolset.attach(agent, {"db.read", "db.write", "skills.load", "approval.request"})
    return agent
