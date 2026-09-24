"""Approval flow: request → audit/event → decision → resume job; plus MCP gating."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from apollo.db import tables as t
from apollo.db.repositories import infra
from apollo.queue.outbox import drain_events
from apollo.telegram import approvals as approvals_mod
from tests.fakes import fake_api


def test_request_then_approve_enqueues_resume(runtime, clock) -> None:
    with runtime.db.write() as session:
        action = infra.create_pending_action(
            session, kind="calendar.delete_event", payload={"summary": "Delete standup"}, run_id="run-1"
        )
        assert action.id is not None
        action_id = action.id

    # The approval.requested event enqueues a notification job.
    with runtime.db.write() as session:
        drain_events(session, now=clock.now())
    with runtime.db.session() as session:
        jobs = list(session.execute(select(t.Job)).scalars())
    assert any(job.kind == "notify.send" for job in jobs)

    # Running the worker turns that job into a queued notification.
    from apollo.queue.worker import Worker

    Worker(runtime, worker_id="test").run(once=True)
    with runtime.db.session() as session:
        notifications = list(session.execute(select(t.Notification)).scalars())
    assert any(n.kind == "approval" for n in notifications)

    api = fake_api(results={"editMessageText": {"message_id": 1, "chat": {"id": 1, "type": "private"}}})
    result = asyncio.run(
        approvals_mod.decide(
            api, runtime, action_id=action_id, decision="approved",
            decided_by="42", chat_id=42, message_id=99,
        )
    )
    assert result["status"] == "approved"

    with runtime.db.write() as session:
        drain_events(session, now=clock.now())
    with runtime.db.session() as session:
        jobs = list(session.execute(select(t.Job)).scalars())
    assert any(job.kind == "approval.resume" for job in jobs)
    with runtime.db.session() as session:
        audits = list(session.execute(select(t.AuditLog)).scalars())
    assert any(a.action == "approval.approved" for a in audits)


def test_deny_does_not_enqueue_resume(runtime, clock) -> None:
    with runtime.db.write() as session:
        action = infra.create_pending_action(
            session, kind="web.send", payload={"summary": "Send email"}, run_id="run-2"
        )
        assert action.id is not None
    api = fake_api(results={"editMessageText": True})
    asyncio.run(
        approvals_mod.decide(
            api, runtime, action_id=action.id, decision="denied", decided_by="42"
        )
    )
    with runtime.db.write() as session:
        drain_events(session, now=clock.now())
    with runtime.db.session() as session:
        jobs = list(session.execute(select(t.Job)).scalars())
    assert not any(job.kind == "approval.resume" for job in jobs)


def test_expired_approval_auto_denies(runtime, clock) -> None:
    from datetime import timedelta

    with runtime.db.write() as session:
        infra.create_pending_action(
            session, kind="vault.delete", payload={}, expires_at=clock.now() - timedelta(minutes=1)
        )
    with runtime.db.write() as session:
        expired = infra.expire_stale_actions(session, clock.now())
    assert len(expired) == 1
    with runtime.db.session() as session:
        action = session.execute(select(t.PendingAction)).scalars().first()
    assert action is not None and action.status == "expired"


def test_irreversible_tier_routes_to_approval(runtime) -> None:
    # Default config lists vault.delete as irreversible.
    assert runtime.settings.autonomy.tier_for("vault.delete") == "irreversible"
    assert runtime.settings.autonomy.tier_for("create_task") == "mutate"
