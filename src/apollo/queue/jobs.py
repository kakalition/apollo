"""Job queue operations: enqueue, claim/lease, heartbeat, retry, dead-letter.

The claim is a single ``UPDATE ... RETURNING`` guarded by a subquery so two workers
can never claim the same job. Leases are extended by the worker's heartbeat and
reclaimed by the dispatcher when they expire.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.repositories.base import emit, utcnow
from apollo.domain.events import EventType

DEFAULT_LEASE_SECONDS = 120
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600


def enqueue_job(
    session: Session,
    *,
    kind: str,
    payload: dict | None = None,
    priority: int = 5,
    run_after: datetime | None = None,
    max_attempts: int = 5,
) -> t.Job:
    job = t.Job(
        kind=kind,
        payload_json=payload or {},
        priority=priority,
        run_after=run_after or utcnow(),
        max_attempts=max_attempts,
        status="pending",
    )
    session.add(job)
    session.flush()
    return job


def claim_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> t.Job | None:
    now = now or utcnow()
    lease_until = now + timedelta(seconds=lease_seconds)
    row = session.execute(
        text(
            """
            UPDATE jobs
               SET status = 'running',
                   lease_until = :lease,
                   worker_id = :worker,
                   attempts = attempts + 1,
                   updated_at = :now
             WHERE id = (
                   SELECT id FROM jobs
                    WHERE status = 'pending' AND run_after <= :now
                    ORDER BY priority, id
                    LIMIT 1
             )
            RETURNING id
            """
        ),
        {"lease": lease_until.isoformat(), "worker": worker_id, "now": now.isoformat()},
    ).fetchone()
    if row is None:
        return None
    session.flush()
    job = session.get(t.Job, row[0])
    return job


def heartbeat(session: Session, job_id: int, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
    job = session.get(t.Job, job_id)
    if job is None or job.status != "running":
        return
    job.lease_until = utcnow() + timedelta(seconds=lease_seconds)
    session.flush()


def complete_job(session: Session, job_id: int, result: dict | None = None) -> None:
    job = session.get(t.Job, job_id)
    if job is None:
        return
    job.status = "done"
    job.result_json = result or {}
    job.error = None
    job.lease_until = None
    job.updated_at = utcnow()
    session.flush()


def fail_job(
    session: Session,
    job_id: int,
    error: str,
    *,
    retryable: bool = True,
    now: datetime | None = None,
) -> str:
    """Mark a job failed. Returns the resulting status (``pending`` or ``dead``)."""
    job = session.get(t.Job, job_id)
    if job is None:
        return "missing"
    now = now or utcnow()
    job.error = error[:4000]
    job.lease_until = None
    job.worker_id = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "pending"
        job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts))
    else:
        job.status = "dead"
    job.updated_at = utcnow()
    session.flush()
    emit(session, EventType.JOB_FAILED, {"id": job_id, "kind": job.kind, "status": job.status})
    return job.status


def backoff_seconds(attempts: int) -> int:
    return min(BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_SECONDS)


def requeue_expired(session: Session, now: datetime | None = None) -> list[int]:
    now = now or utcnow()
    stmt = select(t.Job).where(
        t.Job.status == "running",
        t.Job.lease_until.is_not(None),
        t.Job.lease_until < now,
    )
    ids: list[int] = []
    for job in session.execute(stmt).scalars():
        ids.append(job.id)
    for job_id in ids:
        job = session.get(t.Job, job_id)
        assert job is not None
        if job.attempts >= job.max_attempts:
            job.status = "dead"
        else:
            job.status = "pending"
            job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts))
        job.lease_until = None
        job.worker_id = None
        job.updated_at = utcnow()
    session.flush()
    return ids


def retry_job(session: Session, job_id: int) -> None:
    job = session.get(t.Job, job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    job.status = "pending"
    job.run_after = utcnow()
    job.error = None
    job.attempts = 0
    job.lease_until = None
    job.worker_id = None
    session.flush()


def clone_job(session: Session, job_id: int) -> int:
    job = session.get(t.Job, job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    new = enqueue_job(
        session,
        kind=job.kind,
        payload=job.payload_json,
        priority=job.priority,
        max_attempts=job.max_attempts,
    )
    return new.id


def queue_depth(session: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = session.execute(
        select(t.Job.status, func.count()).group_by(t.Job.status)
    ).all()
    counts: dict[str, int] = {}
    for status, count in rows:
        counts[str(status)] = int(count)
    return counts
