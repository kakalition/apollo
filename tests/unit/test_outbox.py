"""Transactional outbox: built-in reactions, event rules, cooldown, pause."""

from __future__ import annotations

from sqlalchemy import select

from apollo.db import tables as t
from apollo.db.repositories import domain as repo
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.queue.outbox import drain_events
from apollo.scheduler.rules import add_rule


def _jobs(db) -> list[t.Job]:
    with db.session() as session:
        return list(session.execute(select(t.Job).order_by(t.Job.id)).scalars())


def test_checkin_event_enqueues_memory_add(db, clock) -> None:
    with db.write() as session:
        logrepo.log_checkin(
            session, m.CheckIn(kind=m.CheckInKind.REFLECTION, note="felt good", occurred_at=clock.now())
        )
    with db.write() as session:
        enqueued = drain_events(session, now=clock.now())
    assert enqueued == 1
    jobs = _jobs(db)
    assert jobs[0].kind == "memory.add"


def test_event_rule_matches_and_cooldown(db, clock) -> None:
    with db.write() as session:
        add_rule(
            session,
            name="on_goal_created",
            trigger_type="event",
            action="skill",
            event_type="goal.created",
            payload={"skill": "goal-decompose"},
            cooldown_seconds=3600,
        )
        repo.create_goal(session, m.Goal(title="Learn guitar"))
    with db.write() as session:
        drain_events(session, now=clock.now())
    skills = [j for j in _jobs(db) if j.kind == "skill.run"]
    assert len(skills) == 1

    # A second event inside the cooldown window must not enqueue again.
    with db.write() as session:
        repo.create_goal(session, m.Goal(title="Learn piano"))
    with db.write() as session:
        drain_events(session, now=clock.now())
    assert len([j for j in _jobs(db) if j.kind == "skill.run"]) == 1

    # Past the cooldown it fires again.
    from datetime import timedelta

    with db.write() as session:
        repo.create_goal(session, m.Goal(title="Learn drums"))
    with db.write() as session:
        drain_events(session, now=clock.now() + timedelta(hours=2))
    assert len([j for j in _jobs(db) if j.kind == "skill.run"]) == 2


def test_paused_marks_events_processed_without_jobs(db, clock) -> None:
    with db.write() as session:
        repo.create_goal(session, m.Goal(title="Paused goal"))
    with db.write() as session:
        drain_events(session, now=clock.now(), paused=True)
    assert _jobs(db) == []
    with db.session() as session:
        unprocessed = session.execute(select(t.Event).where(t.Event.processed_at.is_(None))).scalars().all()
    assert unprocessed == []


def test_approval_requested_notifies(db, clock) -> None:
    from apollo.db.repositories import infra

    with db.write() as session:
        infra.create_pending_action(session, kind="vault.delete", payload={"summary": "Delete note"})
    with db.write() as session:
        drain_events(session, now=clock.now())
    jobs = [j for j in _jobs(db) if j.kind == "notify.send"]
    assert len(jobs) == 1
