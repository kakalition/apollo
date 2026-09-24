"""Researcher/executor: MCP-tool-heavy agent for real work (web, calendar, vault)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from apollo.agents import tools as toolset
from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import RESEARCHER, with_skills
from apollo.config import Settings


class Finding(BaseModel):
    claim: str
    source: str | None = None
    verified: bool = True


class ResearchResult(BaseModel):
    question: str
    findings: list[Finding] = Field(default_factory=list)
    interpretation: str
    recommendation: str
    counter_argument: str | None = None
    citations: list[str] = Field(default_factory=list)


def _instructions(ctx: RunContext[Context]) -> str:
    return with_skills(RESEARCHER, ctx.deps.skills.summary_text() or "(none)")


def build_researcher(
    settings: Settings, mcp_toolsets: list[Any] | None = None, model: Any | None = None
) -> Agent[Context, ResearchResult]:
    agent: Agent[Context, ResearchResult] = Agent(
        model or build_model(settings, "research"),
        output_type=ResearchResult,
        deps_type=Context,
        name="researcher",
        instructions=_instructions,
        toolsets=mcp_toolsets or [],
    )
    toolset.attach(
        agent, {"db.read", "memory.recall", "skills.load", "notify.telegram", "approval.request"}
    )
    return agent
