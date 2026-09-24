"""Job queue: atomic claim, leases, retry/backoff, dead-letter, advisory lock."""

from __future__ import annotations

from datetime import timedelta

from apollo.db.session import acquire_advisory_lock, release_advisory_lock
from apollo.queue import jobs as qjobs


def test_enqueue_and_claim(db, clock) -> None:
    with db.write() as session:
        job = qjobs.enqueue_job(session, kind="agent.run", payload={"text": "hi"}, run_after=clock.now())
    with db.write() as session:
        claimed = qjobs.claim_job(session, worker_id="w1", now=clock.now())
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert claimed.lease_until is not None


def test_claim_is_exclusive(db, clock) -> None:
    with db.write() as session:
        qjobs.enqueue_job(session, kind="agent.run", run_after=clock.now())
    with db.write() as session:
        assert qjobs.claim_job(session, worker_id="w1", now=clock.now()) is not None
    with db.write() as session:
        assert qjobs.claim_job(session, worker_id="w2", now=clock.now()) is None


def test_priority_ordering(db, clock) -> None:
    with db.write() as session:
        qjobs.enqueue_job(session, kind="low", priority=9, run_after=clock.now())
        high = qjobs.enqueue_job(session, kind="high", priority=1, run_after=clock.now())
    with db.write() as session:
        claimed = qjobs.claim_job(session, worker_id="w1", now=clock.now())
    assert claimed is not None and claimed.id == high.id


def test_run_after_delays_claim(db, clock) -> None:
    with db.write() as session:
        qjobs.enqueue_job(session, kind="later", run_after=clock.now() + timedelta(minutes=10))
    with db.write() as session:
        assert qjobs.claim_job(session, worker_id="w1", now=clock.now()) is None
    with db.write() as session:
        assert qjobs.claim_job(session, worker_id="w1", now=clock.now() + timedelta(minutes=11)) is not None


def test_failure_backoff_then_dead(db, clock) -> None:
    with db.write() as session:
        job = qjobs.enqueue_job(session, kind="agent.run", max_attempts=2, run_after=clock.now())
    with db.write() as session:
        claimed = qjobs.claim_job(session, worker_id="w1", now=clock.now())
        assert claimed is not None
        first_status = qjobs.fail_job(session, claimed.id, "boom", now=clock.now())
    assert first_status == "pending"  # retryable: one attempt remains

    with db.write() as session:
        claimed = qjobs.claim_job(session, worker_id="w1", now=clock.now() + timedelta(days=1))
        assert claimed is not None
        second_status = qjobs.fail_job(session, claimed.id, "boom again", now=clock.now() + timedelta(days=1))
    assert second_status == "dead"
    with db.session() as session:
        stored = session.get(type(job), job.id)
        assert stored is not None and stored.status == "dead"


def test_expired_lease_is_requeued(db, clock) -> None:
    with db.write() as session:
        job = qjobs.enqueue_job(session, kind="agent.run", run_after=clock.now())
    with db.write() as session:
        claimed = qjobs.claim_job(session, worker_id="w1", lease_seconds=1, now=clock.now())
        assert claimed is not None
    with db.write() as session:
        requeued = qjobs.requeue_expired(session, clock.now() + timedelta(seconds=5))
    assert requeued == [job.id]
    with db.session() as session:
        stored = session.get(type(job), job.id)
        assert stored is not None and stored.status == "pending"


def test_retry_and_clone(db, clock) -> None:
    with db.write() as session:
        job = qjobs.enqueue_job(session, kind="agent.run", payload={"a": 1}, run_after=clock.now())
        qjobs.claim_job(session, worker_id="w1", now=clock.now())
        qjobs.fail_job(session, job.id, "x", retryable=False)
    with db.write() as session:
        qjobs.retry_job(session, job.id)
        clone_id = qjobs.clone_job(session, job.id)
    assert clone_id != job.id
    with db.session() as session:
        assert session.get(type(job), job.id).status == "pending"


def test_advisory_lock_exclusive_and_releasable(db) -> None:
    import os

    owner = str(os.getpid())
    with db.write() as session:
        assert acquire_advisory_lock(session, "dispatcher", owner=owner) is True
    with db.write() as session:
        # PID 1 always exists, so a second owner cannot take the live lock.
        assert acquire_advisory_lock(session, "dispatcher", owner="1") is False
    with db.write() as session:
        release_advisory_lock(session, "dispatcher", owner=owner)
    with db.write() as session:
        assert acquire_advisory_lock(session, "dispatcher", owner="1") is True
