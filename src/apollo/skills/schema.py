"""Skill schema: ``SKILL.md`` frontmatter validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

TierName = Literal["triage", "plan", "coach", "research", "memory"]


class SkillMeta(BaseModel):
    """Validated YAML frontmatter of a ``SKILL.md`` file."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("allowed-tools", "allowed_tools"),
    )
    model_tier: TierName = Field(
        default="coach",
        validation_alias=AliasChoices("model-tier", "model_tier"),
    )
    version: str = "0.1.0"


class Skill(BaseModel):
    meta: SkillMeta
    body: str
    path: Path
    tools_path: Path | None = None

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def description(self) -> str:
        return self.meta.description


class SkillSummary(BaseModel):
    """Progressive disclosure: only what the supervisor system prompt needs."""

    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    model_tier: TierName = "coach"


class SkillTool(BaseModel):
    """A Python tool contributed by ``skills/<slug>/tools.py``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""
    func: Any = None


def build_summaries(skills: list[Skill]) -> list[SkillSummary]:
    return [
        SkillSummary(
            name=s.name,
            description=s.description,
            triggers=s.meta.triggers,
            model_tier=s.meta.model_tier,
        )
        for s in skills
    ]
