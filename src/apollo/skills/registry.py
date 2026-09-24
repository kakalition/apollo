"""Skill registry: load ``SKILL.md`` files, hot-reload, expose progressive
disclosure and optional Python tools from ``skills/<slug>/tools.py``.
"""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from apollo.observability import get_logger
from apollo.skills.schema import Skill, SkillMeta, SkillSummary, SkillTool, build_summaries
from apollo.support.frontmatter import split_frontmatter

log = get_logger("apollo.skills")


class SkillError(RuntimeError):
    pass


class ToolRegistrar:
    """Passed to a skill's ``register`` function to collect tools."""

    def __init__(self) -> None:
        self.tools: list[SkillTool] = []

    def register(self, name: str, description: str = "", func: Callable[..., Any] | None = None) -> None:
        self.tools.append(SkillTool(name=name, description=description, func=func))

    def add(self, tool: SkillTool) -> None:
        self.tools.append(tool)


class SkillRegistry:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._skills: dict[str, Skill] = {}
        self._tools: dict[str, list[SkillTool]] = {}
        self._lock = threading.RLock()
        self._observer: Any | None = None

    # -- loading -----------------------------------------------------------
    def load(self) -> int:
        skills: dict[str, Skill] = {}
        if self.root.exists():
            for skill_file in sorted(self.root.glob("*/SKILL.md")):
                try:
                    skill = self._parse(skill_file)
                except (SkillError, ValidationError) as exc:
                    log.warning("skills.invalid", path=str(skill_file), error=str(exc))
                    continue
                skills[skill.name] = skill
        with self._lock:
            self._skills = skills
            self._tools = {}
        log.info("skills.loaded", count=len(skills), root=str(self.root))
        return len(skills)

    def _parse(self, path: Path) -> Skill:
        raw = path.read_text(encoding="utf-8")
        front, body = split_frontmatter(raw)
        if not front:
            raise SkillError(f"{path} has no frontmatter")
        meta = SkillMeta.model_validate(front)
        tools_path = path.parent / "tools.py"
        return Skill(meta=meta, body=body.strip(), path=path, tools_path=tools_path if tools_path.exists() else None)

    # -- access ------------------------------------------------------------
    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._skills.get(name)

    def require(self, name: str) -> Skill:
        skill = self.get(name)
        if skill is None:
            raise SkillError(f"unknown skill {name!r}")
        return skill

    def all(self) -> list[Skill]:
        with self._lock:
            return list(self._skills.values())

    def summaries(self) -> list[SkillSummary]:
        return build_summaries(self.all())

    def summary_text(self) -> str:
        """One line per skill, for the supervisor system prompt."""
        lines = []
        for summary in sorted(self.summaries(), key=lambda s: s.name):
            lines.append(f"- {summary.name}: {summary.description}")
        return "\n".join(lines)

    def body(self, name: str) -> str:
        return self.require(name).body

    def match_trigger(self, trigger: str) -> list[Skill]:
        return [s for s in self.all() if trigger in s.meta.triggers]

    # -- python tools ------------------------------------------------------
    def load_tools(self, name: str) -> list[SkillTool]:
        with self._lock:
            if name in self._tools:
                return self._tools[name]
        skill = self.require(name)
        if skill.tools_path is None:
            tools: list[SkillTool] = []
        else:
            tools = self._import_tools(skill)
        with self._lock:
            self._tools[name] = tools
        return tools

    def _import_tools(self, skill: Skill) -> list[SkillTool]:
        module_name = f"apollo_skill_{skill.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, skill.tools_path)
        if spec is None or spec.loader is None:
            raise SkillError(f"cannot load tools for skill {skill.name!r}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registrar = ToolRegistrar()
        register = getattr(module, "register", None)
        if callable(register):
            register(registrar)
        allowed = set(skill.meta.allowed_tools)
        tools = [t for t in registrar.tools if not allowed or t.name in allowed]
        return tools

    # -- hot reload --------------------------------------------------------
    def start_watch(self) -> None:
        """Watch the skills directory and reload on change (best effort)."""
        if self._observer is not None or not self.root.exists():
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            registry = self

            class _Handler(FileSystemEventHandler):
                def on_any_event(self, event: Any) -> None:
                    if str(getattr(event, "src_path", "")).endswith((".md", ".py")):
                        registry.load()

            observer = Observer()
            observer.schedule(_Handler(), str(self.root), recursive=True)
            observer.daemon = True
            observer.start()
            self._observer = observer
            log.info("skills.watching", root=str(self.root))
        except Exception as exc:
            log.warning("skills.watch_failed", error=str(exc))

    def stop_watch(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
