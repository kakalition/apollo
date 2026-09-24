"""Coach specialist: reviews, drift detection, reflection and synthesis."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from apollo.agents import tools as toolset
from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import COACH, with_skills
from apollo.config import Settings


class Adjustment(BaseModel):
    entity: str = Field(description="practice | habit | task | metric | goal")
    entity_id: int | None = None
    change: str
    expected_effect: str


class CoachResult(BaseModel):
    summary: str = Field(description="2-4 sentence narrative of the period.")
    insights: str | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)
    next_week: str | None = None
    notifications: list[str] = Field(default_factory=list)


def _instructions(ctx: RunContext[Context]) -> str:
    return with_skills(COACH, ctx.deps.skills.summary_text() or "(none)")


def build_coach(settings: Settings, model: Any | None = None) -> Agent[Context, CoachResult]:
    agent: Agent[Context, CoachResult] = Agent(
        model or build_model(settings, "coach"),
        output_type=CoachResult,
        deps_type=Context,
        name="coach",
        instructions=_instructions,
    )
    toolset.attach(agent, {"db.read", "db.write", "memory.recall", "notify.telegram", "skills.load"})
    return agent
