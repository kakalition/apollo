"""Deterministic agent run end-to-end: agent → commands → DB → RunLog → notification."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from apollo.agents.runtime import build_context, run_agent_job
from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.queue.worker import JobContext


def _triage_model():
    from pydantic_ai.models.test import TestModel

    return TestModel(
        call_tools=[],
        custom_output_args={
            "commands": [
                {
                    "kind": "capture_tasks",
                    "tasks": [
                        {"kind": "capture_task", "title": "Buy milk", "priority": 2},
                        {"kind": "capture_task", "title": "Email Sam"},
                    ],
                },
                {
                    "kind": "create_goal",
                    "title": "Cook at home more",
                    "success_criteria": "4 home dinners/week",
                },
            ],
            "reply": "Captured 2 tasks and a goal.",
        }
    )


def test_agent_job_applies_commands_and_logs(runtime) -> None:
    ctx = JobContext(
        runtime=runtime,
        job_id=1,
        kind="agent.run",
        payload={
            "run_id": "run-test",
            "agent": "triage",
            "text": "buy milk and email sam, also want to cook at home more",
            "topic": "inbox",
            "model_overrides": {"triage": _triage_model()},
        },
    )
    result = asyncio.run(run_agent_job(ctx))

    assert result["agent"] == "triage"
    assert len(result["applied"]) == 2

    with runtime.db.session() as session:
        tasks = repo.list_tasks(session)
        goals = repo.list_goals(session)
        run_logs = list(session.execute(select(t.RunLog)).scalars())
        notifications = list(session.execute(select(t.Notification)).scalars())

    titles = {task.title for task in tasks}
    assert titles == {"Buy milk", "Email Sam"}
    assert [goal.title for goal in goals] == ["Cook at home more"]
    assert any(log.run_id == "run-test" and log.agent == "triage" for log in run_logs)
    assert notifications and "Captured" in notifications[0].payload_json["text"]


def test_context_exposes_skills_and_clock(runtime) -> None:
    context = build_context(runtime, run_id="x")
    skills = {s.name for s in context.skills.all()}
    assert "capture" in skills
    assert context.clock.now() is not None


class _FakeSink:
    def __init__(self) -> None:
        self.pushes: list[str] = []
        self.finished = False
        self.cancelled = False

    async def push(self, text: str) -> None:
        self.pushes.append(text)

    async def finish(self, text: str) -> None:
        self.finished = True

    async def cancel(self) -> None:
        self.cancelled = True


def test_structured_agents_stream_with_a_keepalive_not_stream_text(runtime) -> None:
    """Regression: stream_text() only works for str output; structured agents must
    fall back to a keepalive draft instead of failing the whole run."""
    from apollo.agents.runtime import build_context, run_agent

    sink = _FakeSink()
    context = build_context(runtime, extra={"model_overrides": {"triage": _triage_model()}})
    result = asyncio.run(run_agent(context, "triage", "buy milk", stream=sink))

    assert result.error is None
    assert sink.finished is True and sink.cancelled is False
    assert sink.pushes, "expected a keepalive draft update"
