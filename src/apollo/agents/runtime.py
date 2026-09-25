"""Agent runtime: build contexts/agents, run them, persist RunLogs, apply outputs.

This module is the bridge between the job queue (sync) and Pydantic AI (async). It
is deliberately the only place agents are constructed, so tier routing, tool
attachment and MCP toolsets stay in one place.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from pydantic_ai import Agent

from apollo.agents.coach import CoachResult, build_coach
from apollo.agents.context import Context
from apollo.agents.models import model_name_for
from apollo.agents.planner import build_planner
from apollo.agents.researcher import build_researcher
from apollo.agents.supervisor import RouteDecision, build_supervisor
from apollo.agents.triage import build_triage
from apollo.db.repositories import infra
from apollo.domain.commands import CaptureResult, CommandBatch, PlanResult
from apollo.observability import get_logger
from apollo.skills.registry import SkillRegistry
from apollo.tools.clock import Clock, SystemClock

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime
    from apollo.queue.worker import JobContext

log = get_logger("apollo.agents.runtime")

AGENT_TIERS = {
    "supervisor": "light",
    "triage": "triage",
    "planner": "plan",
    "coach": "coach",
    "researcher": "research",
    "research": "research",
}


class StreamSink(Protocol):
    async def push(self, text: str) -> None: ...

    async def finish(self, text: str) -> None: ...

    async def cancel(self) -> None: ...


@dataclass(slots=True)
class AgentRunResult:
    agent: str
    tier: str
    model: str
    output: Any
    output_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None
    cancelled: bool = False


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
def build_context(
    runtime: Runtime,
    *,
    run_id: str | None = None,
    clock: Clock | None = None,
    topic: str | None = None,
    telegram_user_id: int | None = None,
    conversation_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Context:
    from apollo.mcp.registry import MCPRegistry
    from apollo.memory.facade import LazyMemory

    settings = runtime.settings
    skills = SkillRegistry(settings.root / "skills")
    skills.load()
    return Context(
        runtime=runtime,
        clock=clock or SystemClock(settings.app.timezone),
        memory=LazyMemory(runtime),
        skills=skills,
        mcp=MCPRegistry(settings),
        run_id=run_id or uuid.uuid4().hex[:12],
        topic=topic,
        telegram_user_id=telegram_user_id,
        conversation_id=conversation_id,
        extra=extra or {},
    )


def build_agent(context: Context, name: str) -> Agent[Context, Any]:
    settings = context.settings
    overrides: dict[str, Any] = context.extra.get("model_overrides", {})
    model = overrides.get(name) or overrides.get("*")
    if name == "supervisor":
        return build_supervisor(settings, model)
    if name == "triage":
        return build_triage(settings, model)
    if name == "planner":
        return build_planner(settings, model)
    if name == "coach":
        return build_coach(settings, model)
    if name in ("researcher", "research"):
        toolsets = context.extra.get("mcp_toolsets")
        return build_researcher(settings, toolsets if toolsets is not None else context.mcp.toolsets(), model)
    raise KeyError(f"unknown agent {name!r}")


def _tier_for(name: str, context: Context, override: str | None = None) -> str:
    if override:
        return override
    return AGENT_TIERS.get(name, "triage")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
CAPTURE_PREFIXES = (
    "remind me to",
    "remind me",
    "add ",
    "log ",
    "note that",
    "note:",
    "capture ",
    "remember to",
    "i need to",
    "i must ",
    "don't forget",
    "dont forget",
    "todo:",
    "to-do:",
)


def looks_like_capture(text: str) -> bool:
    """Skip the supervisor for unambiguous capture phrasing (saves a model call)."""
    low = text.strip().lower()
    if not low or len(low) > 200 or "?" in low:
        return False
    return low.startswith(CAPTURE_PREFIXES)


async def route_message(context: Context, text: str) -> RouteDecision:
    agent = build_supervisor(context.settings, context.extra.get("model_overrides", {}).get("supervisor"))
    result = await agent.run(text, deps=context, conversation_id=context.conversation_id)
    return result.output


async def run_agent(
    context: Context,
    name: str,
    prompt: str,
    *,
    tier_override: str | None = None,
    conversation_id: str | None = None,
    stream: StreamSink | None = None,
) -> AgentRunResult:
    agent = build_agent(context, name)
    tier = _tier_for(name, context, tier_override)
    model_name = model_name_for(context.settings, tier)  # type: ignore[arg-type]
    timeout = float(getattr(context.settings.provider, "run_timeout_seconds", 120) or 0) or None
    started = time.perf_counter()
    try:
        if stream is not None:
            output, usage, tool_calls = await asyncio.wait_for(
                _run_streaming(agent, context, prompt, conversation_id, stream), timeout
            )
        else:
            result = await asyncio.wait_for(
                agent.run(prompt, deps=context, conversation_id=conversation_id), timeout
            )
            output = result.output
            usage = _usage_of(result)
            tool_calls = _tool_call_names(result)
    except Exception as exc:
        duration = int((time.perf_counter() - started) * 1000)
        cancelled = exc.__class__.__name__ == "RunCancelled"
        timed_out = isinstance(exc, TimeoutError)
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.cancel()
        if timed_out:
            message = f"run timed out after {int(timeout or 0)}s"
        else:
            message = f"{type(exc).__name__}: {exc}"
        log.warning(
            "agent.run_cancelled" if cancelled else "agent.run_failed",
            agent=name,
            error=message,
        )
        return AgentRunResult(
            agent=name,
            tier=tier,
            model=model_name,
            output=None,
            output_text="",
            duration_ms=duration,
            error=None if cancelled else message,
            cancelled=cancelled,
        )
    duration = int((time.perf_counter() - started) * 1000)
    return AgentRunResult(
        agent=name,
        tier=tier,
        model=model_name,
        output=output,
        output_text=_text_of(output),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        tool_calls=tool_calls,
        duration_ms=duration,
    )


async def _run_streaming(
    agent: Agent[Context, Any],
    context: Context,
    prompt: str,
    conversation_id: str | None,
    stream: StreamSink,
) -> tuple[Any, Any, list[str]]:
    # ``stream_text`` only works for plain-text agents; our specialists return
    # structured output, so they get a keepalive "Thinking…" draft instead.
    if agent.output_type is not str:
        return await _run_structured_streaming(agent, context, prompt, conversation_id, stream)
    try:
        async with agent.run_stream(prompt, deps=context, conversation_id=conversation_id) as result:
            async for delta in result.stream_text(delta=True):
                if delta:
                    await stream.push(delta)
            output = await result.get_output()
            usage = _usage_of(result)
            await stream.finish(_text_of(output))
            return output, usage, _tool_call_names(result)
    except Exception:
        await stream.cancel()
        raise


async def _run_structured_streaming(
    agent: Agent[Context, Any],
    context: Context,
    prompt: str,
    conversation_id: str | None,
    stream: StreamSink,
) -> tuple[Any, Any, list[str]]:
    run_task = asyncio.create_task(
        agent.run(prompt, deps=context, conversation_id=conversation_id)
    )
    keepalive = asyncio.create_task(_keepalive(stream, run_task))
    try:
        result = await run_task
    except asyncio.CancelledError:
        from apollo.telegram.streaming import RunCancelled

        await stream.cancel()
        raise RunCancelled() from None
    except Exception:
        await stream.cancel()
        raise
    finally:
        keepalive.cancel()
        await asyncio.gather(keepalive, return_exceptions=True)
    output = result.output
    usage = _usage_of(result)
    await stream.finish(_text_of(output))
    return output, usage, _tool_call_names(result)


async def _keepalive(stream: StreamSink, task: asyncio.Task[Any], interval: float = 15.0) -> None:
    """Hold the draft open (and honour Stop) while a structured run is in flight."""
    from apollo.telegram.streaming import RunCancelled

    try:
        await stream.push("")
        while not task.done():
            await asyncio.sleep(interval)
            if task.done():
                break
            await stream.push("")
    except RunCancelled:
        task.cancel()
    except Exception:
        return


def _usage_of(result: Any) -> Any:
    """``usage`` is a property on AgentRunResult but a method on streamed results."""
    usage = getattr(result, "usage", None)
    return usage() if callable(usage) else usage


def _tool_call_names(result: Any) -> list[str]:
    try:
        messages = result.all_messages()
    except Exception:
        return []
    names: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            tool_name = getattr(part, "tool_name", None)
            if tool_name:
                names.append(str(tool_name))
    return names


def _text_of(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, CommandBatch):
        return output.reply or "; ".join(c.kind for c in output.commands)
    if isinstance(output, CaptureResult):
        return output.reply or "; ".join(i.kind for i in output.items)
    if isinstance(output, PlanResult):
        return output.reply or "; ".join(g.title for g in output.goals)
    if isinstance(output, CoachResult):
        return output.summary
    for attr in ("summary", "question", "interpretation", "recommendation", "reply"):
        value = getattr(output, attr, None)
        if isinstance(value, str):
            return value
    return str(output)


# ---------------------------------------------------------------------------
# Job entrypoints (called from the worker)
# ---------------------------------------------------------------------------
async def run_agent_job(job: JobContext) -> dict[str, Any]:
    payload = job.payload
    runtime = job.runtime
    run_id = str(payload.get("run_id") or job.payload.get("run_id") or uuid.uuid4().hex[:12])
    context = build_context(
        runtime,
        run_id=run_id,
        topic=payload.get("topic"),
        telegram_user_id=payload.get("telegram_user_id"),
        conversation_id=payload.get("conversation_id"),
        extra=_extras(payload),
    )

    name = payload.get("agent")
    text = payload.get("text") or payload.get("prompt") or ""
    if not name and looks_like_capture(text):
        name = "triage"
        payload["route"] = {"specialist": "triage", "intent": "capture", "rationale": "capture phrasing"}
    if not name:
        decision = await route_message(context, text)
        name = decision.specialist
        payload["route"] = decision.model_dump()

    stream = _build_stream(payload, runtime)
    result = await run_agent(
        context, name, text, conversation_id=payload.get("conversation_id"), stream=stream
    )
    await _persist(runtime, result, input_text=text, run_id=run_id)

    applied = _apply_output(runtime, result.output, actor=f"agent:{name}", run_id=run_id, context=context)
    _notify_result(runtime, name, result, payload, applied)
    return {
        "agent": result.agent,
        "tier": result.tier,
        "model": result.model,
        "output": result.output_text,
        "applied": applied,
        "error": result.error,
    }


def _extras(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-serialisable hooks injected by tests (model overrides, toolsets)."""
    extras: dict[str, Any] = {}
    if "model_overrides" in payload:
        extras["model_overrides"] = payload["model_overrides"]
    if "mcp_toolsets" in payload:
        extras["mcp_toolsets"] = payload["mcp_toolsets"]
    return extras


def _apply_output(
    runtime: Runtime, output: Any, *, actor: str, run_id: str, context: Context
) -> list[str]:
    if isinstance(output, CaptureResult):
        from apollo.domain.apply import apply_capture

        with runtime.db.write() as session:
            return apply_capture(
                session, output, actor=actor, run_id=run_id,
                vault=_vault(runtime),
            )
    if isinstance(output, PlanResult):
        from apollo.domain.apply import apply_plan

        with runtime.db.write() as session:
            return apply_plan(session, output, actor=actor, run_id=run_id)
    if isinstance(output, CommandBatch):
        return _apply_batch(runtime, output, actor=actor, run_id=run_id, context=context)
    return []


def _vault(runtime: Runtime) -> Any:
    from apollo.tools.vault import Vault

    return Vault(runtime.settings.vault_path)


def _apply_batch(runtime: Runtime, batch: CommandBatch, *, actor: str, run_id: str, context: Context) -> list[str]:
    from apollo.domain.apply import apply_batch
    from apollo.tools.vault import Vault

    with runtime.db.write() as session:
        return apply_batch(
            session,
            batch.commands,
            actor=actor,
            run_id=run_id,
            vault=Vault(runtime.settings.vault_path),
        )


def _notify_result(
    runtime: Runtime,
    name: str,
    result: AgentRunResult,
    payload: dict[str, Any],
    applied: list[str],
) -> None:
    if result.cancelled:
        return
    if result.error:
        text = f"⚠️ {name} run failed: {result.error}"
        topic = "system"
    else:
        text = result.output_text
        if applied:
            text = f"{text}\n\nApplied: {'; '.join(applied)}" if text else f"Applied: {'; '.join(applied)}"
        topic = payload.get("topic") or _default_topic(name)
    if not text:
        return
    with runtime.db.write() as session:
        infra.enqueue_notification(
            session,
            kind="agent.result",
            ref_id=payload.get("run_id") or result.agent,
            period=None,
            payload={"text": text[:4000], "topic": topic, "format": "markdown"},
            urgent=bool(result.error),
        )


def _default_topic(name: str) -> str:
    if name in ("triage", "capture"):
        return "inbox"
    if name == "planner":
        return "goals"
    if name == "coach":
        return "reviews"
    return "system"


def _build_stream(payload: dict[str, Any], runtime: Runtime) -> Any:
    spec = payload.get("stream")
    if not spec:
        return None
    try:
        from apollo.telegram.streaming import TelegramDraftSink

        return TelegramDraftSink.from_spec(spec, runtime=runtime)
    except Exception as exc:
        log.warning("agent.stream_unavailable", error=str(exc))
        return None


async def _persist(runtime: Runtime, result: AgentRunResult, *, input_text: str, run_id: str) -> None:
    with runtime.db.write() as session:
        infra.write_run_log(
            session,
            run_id=run_id,
            agent=result.agent,
            tier=result.tier,
            model=result.model,
            input_text=input_text[:4000],
            output_text=result.output_text[:4000],
            tool_calls=result.tool_calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
            status="cancelled" if result.cancelled else ("error" if result.error else "ok"),
            error=result.error,
        )


async def run_skill_job(job: JobContext) -> dict[str, Any]:
    payload = job.payload
    skill_name = payload.get("skill") or payload.get("skill_name")
    if not skill_name:
        return {"skipped": True, "reason": "no skill"}
    runtime = job.runtime
    context = build_context(runtime, run_id=payload.get("run_id"), extra=_extras(payload))
    skill = context.skills.require(skill_name)
    prompt = payload.get("text") or payload.get("prompt") or f"Run the {skill_name} skill for the current period."
    agent_name = "coach" if skill.meta.model_tier in ("coach", "plan") else "triage"
    result = await run_agent(
        context,
        agent_name,
        f"# Skill: {skill.name}\n\n{skill.body}\n\n# Task\n{prompt}",
        tier_override=skill.meta.model_tier,
        stream=_build_stream(payload, runtime),
    )
    await _persist(runtime, result, input_text=f"skill:{skill_name}", run_id=context.run_id)
    applied = _apply_output(
        runtime, result.output, actor=f"skill:{skill_name}", run_id=context.run_id, context=context
    )
    _notify_result(
        runtime,
        agent_name,
        result,
        {**payload, "topic": payload.get("topic") or "reviews"},
        applied,
    )
    return {"skill": skill_name, "output": result.output_text, "applied": applied}


async def resume_after_approval(job: JobContext) -> dict[str, Any]:
    payload = job.payload
    runtime = job.runtime
    action_id = payload.get("action_id")
    run_id = str(payload.get("run_id") or uuid.uuid4().hex[:12])
    context = build_context(runtime, run_id=run_id)
    resume_prompt = (
        payload.get("text")
        or f"Approval #{action_id} was granted. Continue the original plan and apply the approved action."
    )
    result = await run_agent(context, payload.get("agent", "planner"), resume_prompt)
    await _persist(runtime, result, input_text=resume_prompt, run_id=run_id)
    return {"resumed": True, "output": result.output_text}


async def generate_review(job: JobContext) -> dict[str, Any]:
    from apollo.scheduler.routines import ensure_period_reviews

    runtime = job.runtime
    context = build_context(runtime, run_id=job.payload.get("run_id"))
    with runtime.db.write() as session:
        ensure_period_reviews(session, context.clock)
    skill = context.skills.require("weekly-review")
    prompt = (
        f"# Skill: weekly-review\n\n{skill.body}\n\n"
        "# Task\nProduce the weekly review for the most recent completed week."
    )
    result = await run_agent(context, "coach", prompt, tier_override="coach")
    await _persist(runtime, result, input_text="review.generate", run_id=context.run_id)
    _notify_result(runtime, "coach", result, {"topic": "reviews"}, [])
    return {"output": result.output_text}


async def generate_briefing(job: JobContext) -> dict[str, Any]:
    runtime = job.runtime
    context = build_context(runtime, run_id=job.payload.get("run_id"))
    skill = context.skills.require("daily-briefing")
    prompt = f"# Skill: daily-briefing\n\n{skill.body}\n\n# Task\nProduce today's briefing."
    result = await run_agent(context, "coach", prompt, tier_override="coach")
    await _persist(runtime, result, input_text="briefing.generate", run_id=context.run_id)
    _notify_result(runtime, "coach", result, {"topic": "today"}, [])
    return {"output": result.output_text}


async def run_agent_once(runtime: Runtime, agent_name: str, text: str) -> str:
    context = build_context(runtime)
    result = await run_agent(context, agent_name, text)
    await _persist(runtime, result, input_text=text, run_id=context.run_id)
    if result.error:
        return f"error: {result.error}"
    applied = _apply_output(
        runtime, result.output, actor=f"agent:{agent_name}", run_id=context.run_id, context=context
    )
    reply = result.output_text or str(result.output)
    if applied:
        reply = f"{reply}\n\nApplied: {'; '.join(applied)}" if reply else f"Applied: {'; '.join(applied)}"
    return reply
