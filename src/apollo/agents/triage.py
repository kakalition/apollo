"""Triage specialist: unstructured text → typed domain commands."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from apollo.agents import tools as toolset
from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import TRIAGE, with_skills
from apollo.config import Settings
from apollo.domain.commands import CommandBatch


def _instructions(ctx: RunContext[Context]) -> str:
    return with_skills(TRIAGE, ctx.deps.skills.summary_text() or "(none)")


def build_triage(settings: Settings, model: Any | None = None) -> Agent[Context, CommandBatch]:
    agent: Agent[Context, CommandBatch] = Agent(
        model or build_model(settings, "triage"),
        output_type=CommandBatch,
        deps_type=Context,
        name="triage",
        instructions=_instructions,
    )
    toolset.attach(agent, {"db.read", "db.write", "skills.load"})
    return agent
