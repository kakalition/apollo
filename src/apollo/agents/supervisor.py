"""Supervisor: cheap-tier router that classifies intent and picks a specialist."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from apollo.agents.context import Context
from apollo.agents.models import build_model
from apollo.agents.prompts import SUPERVISOR
from apollo.config import Settings

Specialist = Literal["triage", "planner", "coach", "research"]


class RouteDecision(BaseModel):
    specialist: Specialist
    intent: str = Field(description="Short snake_case intent label, e.g. capture_task.")
    rationale: str
    confidence: float = 0.5


def build_supervisor(settings: Settings, model: Any | None = None) -> Agent[Context, RouteDecision]:
    return Agent(
        model or build_model(settings, "triage"),
        output_type=RouteDecision,
        deps_type=Context,
        name="supervisor",
        instructions=SUPERVISOR,
    )


SPECIALIST_AGENTS = {
    "triage": "triage",
    "planner": "planner",
    "coach": "coach",
    "research": "researcher",
}
