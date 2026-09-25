"""Agent tools, grouped by capability.

A skill's ``allowed-tools`` names map onto these capability groups; agents only
receive the groups they need (context budget + least privilege).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from apollo.agents.context import Context
from apollo.tools import db_tools

if TYPE_CHECKING:
    from pydantic_ai import Agent


# ---------------------------------------------------------------------------
# db.read
# ---------------------------------------------------------------------------
async def get_context(ctx: RunContext[Context]) -> dict[str, Any]:
    """Overview: now, timezone, pause flag, active goals and practices, open task count."""
    with ctx.deps.read() as session:
        return db_tools.get_context(session, ctx.deps.clock)


async def today(ctx: RunContext[Context]) -> dict[str, Any]:
    """Today's tasks, overdue items, habits due and completed-this-week count."""
    with ctx.deps.read() as session:
        return db_tools.today_view(session, ctx.deps.clock)


async def what_should_i_do_now(ctx: RunContext[Context], limit: int = 5) -> list[dict[str, Any]]:
    """Ranked suggestions for what to do right now, each with a reason."""
    with ctx.deps.read() as session:
        return db_tools.what_should_i_do_now(session, ctx.deps.clock, limit=limit)


async def list_goals(ctx: RunContext[Context], status: str | None = None) -> list[dict[str, Any]]:
    """List goals, optionally filtered by status (active/paused/achieved/abandoned)."""
    with ctx.deps.read() as session:
        return db_tools.list_goals(session, status)


async def get_goal(ctx: RunContext[Context], goal_id: int) -> dict[str, Any] | None:
    """Get a goal with its practices, projects and metrics."""
    with ctx.deps.read() as session:
        return db_tools.get_goal(session, goal_id)


async def list_practices(ctx: RunContext[Context], goal_id: int | None = None) -> list[dict[str, Any]]:
    """List practices, optionally for one goal."""
    with ctx.deps.read() as session:
        return db_tools.list_practices(session, goal_id)


async def list_tasks(
    ctx: RunContext[Context],
    status: str | None = None,
    project_id: int | None = None,
    goal_id: int | None = None,
) -> list[dict[str, Any]]:
    """List tasks, optionally filtered by status, project or goal."""
    with ctx.deps.read() as session:
        return db_tools.list_tasks(session, status=status, project_id=project_id, goal_id=goal_id)


async def list_habits(ctx: RunContext[Context]) -> list[dict[str, Any]]:
    """List habits with their streaks."""
    with ctx.deps.read() as session:
        return db_tools.list_habits(session)


async def list_metrics(ctx: RunContext[Context]) -> list[dict[str, Any]]:
    """List metrics with recent values."""
    with ctx.deps.read() as session:
        return db_tools.list_metrics(session)


async def get_review(ctx: RunContext[Context], review_id: int | None = None) -> dict[str, Any] | None:
    """Fetch the latest review, or a specific review by id."""
    with ctx.deps.read() as session:
        return db_tools.get_review(session, review_id)


async def search_vault(ctx: RunContext[Context], query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Lexical full-text search over the markdown vault."""
    with ctx.deps.read() as session:
        return db_tools.search_vault(session, query, limit=limit)


# ---------------------------------------------------------------------------
# db.write
# ---------------------------------------------------------------------------
async def create_goal(
    ctx: RunContext[Context], title: str, outcome: str | None = None, success_criteria: str | None = None
) -> dict[str, Any]:
    """Create a goal (what the user wants)."""
    with ctx.deps.write() as session:
        return db_tools.create_goal(
            session, title=title, outcome=outcome, success_criteria=success_criteria
        )


async def update_goal(
    ctx: RunContext[Context],
    goal_id: int,
    title: str | None = None,
    outcome: str | None = None,
    status: str | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    """Update fields on a goal."""
    with ctx.deps.write() as session:
        return db_tools.update_goal(
            session, goal_id, title=title, outcome=outcome, status=status, priority=priority
        )


async def create_practice(
    ctx: RunContext[Context],
    name: str,
    goal_id: int | None = None,
    description: str | None = None,
    cadence: str | None = None,
) -> dict[str, Any]:
    """Create a practice: the repeatable behaviour that produces a goal."""
    with ctx.deps.write() as session:
        return db_tools.create_practice(
            session, name=name, goal_id=goal_id, description=description, cadence=cadence
        )


async def create_project(
    ctx: RunContext[Context],
    title: str,
    goal_id: int | None = None,
    practice_id: int | None = None,
    done_when: str | None = None,
) -> dict[str, Any]:
    """Create a finite project with a definition of done."""
    with ctx.deps.write() as session:
        return db_tools.create_project(
            session, title=title, goal_id=goal_id, practice_id=practice_id, done_when=done_when
        )


async def create_task(
    ctx: RunContext[Context],
    title: str,
    project_id: int | None = None,
    goal_id: int | None = None,
    practice_id: int | None = None,
    priority: int = 3,
    due_at: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a task. Unparented tasks land in the inbox."""
    from apollo.tools.time import parse_datetime

    with ctx.deps.write() as session:
        return db_tools.create_task(
            session,
            title=title,
            project_id=project_id,
            goal_id=goal_id,
            practice_id=practice_id,
            priority=priority,
            due_at=parse_datetime(due_at),
            notes=notes,
        )


async def complete_task(ctx: RunContext[Context], task_id: int) -> dict[str, Any]:
    """Mark a task as done."""
    with ctx.deps.write() as session:
        return db_tools.complete_task(session, task_id)


async def log_checkin(
    ctx: RunContext[Context],
    kind: str,
    ref_id: int | None = None,
    value_num: float | None = None,
    value_text: str | None = None,
    note: str | None = None,
    mood: int | None = None,
) -> dict[str, Any]:
    """Log a check-in: kind is habit, metric, task or reflection."""
    with ctx.deps.write() as session:
        return db_tools.log_checkin(
            session,
            kind=kind,
            ref_id=ref_id,
            value_num=value_num,
            value_text=value_text,
            note=note,
            mood=mood,
            source="agent",
        )


async def log_metric(
    ctx: RunContext[Context], metric_id: int, value: float, note: str | None = None
) -> dict[str, Any]:
    """Record a metric value for a metric id."""
    with ctx.deps.write() as session:
        return db_tools.log_metric(session, metric_id, value, note=note)


async def complete_review(
    ctx: RunContext[Context],
    review_id: int,
    summary: str | None = None,
    insights: str | None = None,
) -> dict[str, Any]:
    """Complete a review with its narrative summary and insights."""
    with ctx.deps.write() as session:
        return db_tools.complete_review(session, review_id, summary=summary, insights=insights)


async def capture_note(
    ctx: RunContext[Context], body: str, title: str | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    """Write a markdown note into the vault."""
    from apollo.tools.vault import Vault

    with ctx.deps.write() as session:
        return db_tools.capture_note_to_vault(
            Vault(ctx.deps.settings.vault_path), session, body=body, title=title, tags=tags
        )


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------
async def recall_memory(ctx: RunContext[Context], query: str, k: int = 6) -> list[dict[str, Any]]:
    """Recall semantically relevant memories for a query."""
    return db_tools.recall_memory(ctx.deps.memory, query, k=k)


async def remember(ctx: RunContext[Context], text: str) -> dict[str, Any]:
    """Persist a durable memory."""
    memory_id = ctx.deps.memory.remember(text, metadata={"run_id": ctx.deps.run_id})
    return {"remembered": bool(memory_id), "id": memory_id}


# ---------------------------------------------------------------------------
# notify / skills / approvals
# ---------------------------------------------------------------------------
async def notify_user(
    ctx: RunContext[Context], text: str, topic: str | None = None, urgent: bool = False
) -> dict[str, Any]:
    """Send the user a notification (queued; never sent inline)."""
    from apollo.tools.notify import Notifier

    with ctx.deps.write() as session:
        notifier = Notifier(session)
        notification_id = notifier.send(
            text, topic=topic, kind="agent", ref_id=ctx.deps.run_id, urgent=urgent
        )
    return {"queued": True, "notification_id": notification_id}


async def load_skill(ctx: RunContext[Context], name: str) -> str:
    """Load the full instructions of a skill by name (progressive disclosure)."""
    return ctx.deps.skills.body(name)


async def request_approval(
    ctx: RunContext[Context], kind: str, summary: str, payload_json: str | None = None
) -> dict[str, Any]:
    """Queue an irreversible action for the user's approval."""
    import json

    from apollo.db.repositories import infra

    payload: dict[str, Any] = {"summary": summary}
    if payload_json:
        try:
            payload.update(json.loads(payload_json))
        except ValueError:
            payload["raw"] = payload_json
    with ctx.deps.write() as session:
        action = infra.create_pending_action(session, kind=kind, payload=payload, run_id=ctx.deps.run_id)
        action_id = action.id
    return {"status": "pending_approval", "approval_id": action_id}


# ---------------------------------------------------------------------------
# Capability registry
# ---------------------------------------------------------------------------
READ_TOOLS = [
    get_context,
    today,
    what_should_i_do_now,
    list_goals,
    get_goal,
    list_practices,
    list_tasks,
    list_habits,
    list_metrics,
    get_review,
    search_vault,
]

WRITE_TOOLS = [
    create_goal,
    update_goal,
    create_practice,
    create_project,
    create_task,
    complete_task,
    log_checkin,
    log_metric,
    complete_review,
    capture_note,
]

MEMORY_TOOLS = [recall_memory, remember]
NOTIFY_TOOLS = [notify_user]
SKILL_TOOLS = [load_skill]
APPROVAL_TOOLS = [request_approval]

CAPABILITIES: dict[str, list[Any]] = {
    "db.read": READ_TOOLS,
    "db.read.capture": [today, list_tasks, list_habits, list_metrics],
    "db.write": WRITE_TOOLS,
    "memory.recall": [recall_memory],
    "memory.remember": [remember],
    "memory": MEMORY_TOOLS,
    "notify.telegram": NOTIFY_TOOLS,
    "skills.load": SKILL_TOOLS,
    "approval.request": APPROVAL_TOOLS,
}


def attach(agent: Agent[Any, Any], capabilities: set[str]) -> None:
    """Attach the tool groups an agent is allowed to use."""
    seen: set[str] = set()
    for capability in capabilities:
        for tool in CAPABILITIES.get(capability, []):
            if tool.__name__ in seen:
                continue
            seen.add(tool.__name__)
            agent.tool(tool)
