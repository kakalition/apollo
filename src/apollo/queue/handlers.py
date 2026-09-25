"""Job handlers — the worker's dispatch table.

Each handler receives a :class:`~apollo.queue.worker.JobContext` and opens its own
short transactions through ``ctx.read()`` / ``ctx.write()``. Handlers are the only
place side effects happen.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from apollo.db.repositories import infra
from apollo.observability import get_logger
from apollo.queue.worker import JobContext

log = get_logger("apollo.handlers")


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------
def handle_vault_sync(ctx: JobContext) -> dict[str, Any]:
    from apollo.tools.vault import Vault

    vault = Vault(ctx.runtime.settings.vault_path)
    with ctx.write() as session:
        stats = vault.sync(session)
    return {"added": stats.added, "updated": stats.updated, "removed": stats.removed}


# ---------------------------------------------------------------------------
# Agents & skills (async bridges)
# ---------------------------------------------------------------------------
def handle_agent_run(ctx: JobContext) -> dict[str, Any]:
    from apollo.agents.runtime import run_agent_job

    return asyncio.run(run_agent_job(ctx))


def handle_skill_run(ctx: JobContext) -> dict[str, Any]:
    from apollo.agents.runtime import run_skill_job

    return asyncio.run(run_skill_job(ctx))


def handle_approval_resume(ctx: JobContext) -> dict[str, Any]:
    from apollo.agents.runtime import resume_after_approval

    return asyncio.run(resume_after_approval(ctx))


def handle_review_generate(ctx: JobContext) -> dict[str, Any]:
    from apollo.agents.runtime import generate_review

    return asyncio.run(generate_review(ctx))


def handle_briefing_generate(ctx: JobContext) -> dict[str, Any]:
    from apollo.agents.runtime import generate_briefing

    return asyncio.run(generate_briefing(ctx))


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
def handle_memory_add(ctx: JobContext) -> dict[str, Any]:
    from apollo.memory.facade import build_memory

    text = ctx.payload.get("text") or _memory_text_from_event(ctx.payload)
    if not text:
        return {"skipped": True}
    memory = build_memory(ctx.runtime)
    memory_id = memory.remember(
        text,
        metadata={
            "source": ctx.payload.get("source"),
            "run_id": ctx.payload.get("run_id"),
        },
    )
    return {"remembered": bool(memory_id), "chars": len(text)}


def handle_memory_reindex(ctx: JobContext) -> dict[str, Any]:
    from apollo.memory.facade import build_memory

    memory = build_memory(ctx.runtime)
    with ctx.read() as session:
        count = memory.reindex(session)
    return {"reindexed": count}


def _memory_text_from_event(payload: dict[str, Any]) -> str | None:
    ref = payload.get("ref") or {}
    for key in ("body", "note", "value_text", "summary", "insights", "title", "value_num"):
        value = ref.get(key)
        if value:
            return str(value)
    return None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def handle_notify_send(ctx: JobContext) -> dict[str, Any]:
    payload = ctx.payload
    kind = payload.get("kind") or payload.get("event") or "generic"
    ref_id = str(payload.get("ref_id") or payload.get("event") or "generic")
    body = payload.get("payload")
    if not isinstance(body, dict) or not body:
        # Tolerate rules that put the message fields at the top level.
        body = {
            key: payload[key]
            for key in ("text", "topic", "format", "buttons", "actions", "rich", "urgent")
            if key in payload
        }
    if not body.get("text") and not body.get("rich"):
        return {"skipped": True, "reason": "empty notification"}
    with ctx.write() as session:
        notification = infra.enqueue_notification(
            session,
            kind=kind,
            ref_id=ref_id,
            period=payload.get("period"),
            payload=body,
            urgent=bool(payload.get("urgent") or body.get("urgent", False)),
            scheduled_for=_parse_when(payload.get("scheduled_for")),
        )
        notification_id = notification.id
    return {"notification_id": notification_id}


def _parse_when(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def handle_schedule_evaluate(ctx: JobContext) -> dict[str, Any]:
    from apollo.scheduler.tick import run_tick
    from apollo.tools.clock import SystemClock

    clock = SystemClock(ctx.runtime.settings.app.timezone)
    with ctx.write() as session:
        return run_tick(session, clock.now(), clock)


def handle_overdue_sweep(ctx: JobContext) -> dict[str, Any]:
    """Emit task.overdue events for anything past due (the outbox reacts)."""
    from apollo.db.repositories import domain as repo
    from apollo.tools.clock import SystemClock

    clock = SystemClock(ctx.runtime.settings.app.timezone)
    with ctx.write() as session:
        ids = repo.mark_overdue(session, clock.now())
    return {"overdue": len(ids)}


HANDLERS = {
    "vault.sync": handle_vault_sync,
    "agent.run": handle_agent_run,
    "skill.run": handle_skill_run,
    "approval.resume": handle_approval_resume,
    "review.generate": handle_review_generate,
    "briefing.generate": handle_briefing_generate,
    "memory.add": handle_memory_add,
    "memory.reindex": handle_memory_reindex,
    "notify.send": handle_notify_send,
    "schedule.evaluate": handle_schedule_evaluate,
    "overdue.sweep": handle_overdue_sweep,
}
