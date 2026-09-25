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
            "items": [
                {"kind": "task", "title": "Buy milk", "priority": 2},
                {"kind": "task", "title": "Email Sam"},
                {"kind": "note", "body": "look into meal kits", "title": "Cooking"},
            ],
            "reply": "Captured 2 tasks and a note.",
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
    assert len(result["applied"]) == 2  # one batch (2 tasks) + one note

    with runtime.db.session() as session:
        tasks = repo.list_tasks(session)
        run_logs = list(session.execute(select(t.RunLog)).scalars())
        notifications = list(session.execute(select(t.Notification)).scalars())

    assert {task.title for task in tasks} == {"Buy milk", "Email Sam"}
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


def test_capture_phrasing_skips_supervisor() -> None:
    from apollo.agents.runtime import looks_like_capture

    assert looks_like_capture("remind me to water the plants")
    assert looks_like_capture("add buy stamps")
    assert looks_like_capture("log 7 hours of sleep")
    assert not looks_like_capture("what should I focus on today?")
    assert not looks_like_capture("I want to get fit and run a half marathon")


def test_user_reply_notification_is_not_quiet_hours_buffered(runtime) -> None:
    """A reply to an inbound message is urgent; scheduled output is not."""
    from sqlalchemy import select

    from apollo.agents.runtime import AgentRunResult, _notify_result

    result = AgentRunResult(
        agent="triage", tier="triage", model="m", output_text="Done.", output=None
    )
    with runtime.db.write() as session:
        pass
    _notify_result(runtime, "triage", result, {"run_id": "r-reply", "telegram_user_id": 42}, [])
    _notify_result(runtime, "coach", result, {"run_id": "r-scheduled"}, [])

    with runtime.db.session() as session:
        rows = {
            n.ref_id: n.urgent
            for n in session.execute(select(t.Notification)).scalars()
        }
    assert rows["r-reply"] is True
    assert rows["r-scheduled"] is False
