"""Skill schema validation, registry, hot reload and Python tools."""

from __future__ import annotations

from pathlib import Path

from apollo.skills.registry import SkillRegistry


def test_loads_builtin_skills(settings) -> None:
    registry = SkillRegistry(Path(__file__).resolve().parents[2] / "skills")
    count = registry.load()
    assert count >= 7
    names = {s.name for s in registry.all()}
    assert {"capture", "daily-briefing", "weekly-review", "goal-decompose", "deep-research"} <= names


def test_progressive_disclosure(settings) -> None:
    registry = SkillRegistry(Path(__file__).resolve().parents[2] / "skills")
    registry.load()
    text = registry.summary_text()
    assert "weekly-review" in text
    # Summaries contain only name + description, not the instructions body.
    assert "Scorecard" not in text
    assert "Scorecard" in registry.body("weekly-review")


def test_invalid_skill_is_skipped(tmp_path) -> None:
    root = tmp_path / "skills"
    good = root / "good"
    good.mkdir(parents=True)
    (good / "SKILL.md").write_text("---\nname: good\ndescription: A good skill.\n---\nBody.")
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("no frontmatter here")
    registry = SkillRegistry(root)
    assert registry.load() == 1
    assert registry.get("good") is not None
    assert registry.get("bad") is None


def test_allowed_tools_filter_python_tools(tmp_path) -> None:
    root = tmp_path / "skills"
    skill_dir = root / "with-tools"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: with-tools\ndescription: Has tools.\n"
        "allowed-tools: [allowed_one]\n---\nBody."
    )
    (skill_dir / "tools.py").write_text(
        "def register(registry):\n"
        "    registry.register('allowed_one', 'allowed', lambda: 1)\n"
        "    registry.register('other', 'filtered out', lambda: 2)\n"
    )
    registry = SkillRegistry(root)
    registry.load()
    tools = registry.load_tools("with-tools")
    assert [t.name for t in tools] == ["allowed_one"]


def test_match_trigger() -> None:
    registry = SkillRegistry(Path(__file__).resolve().parents[2] / "skills")
    registry.load()
    matched = registry.match_trigger("event:review.due")
    assert any(s.name == "weekly-review" for s in matched)
