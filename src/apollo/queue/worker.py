"""Worker process: claim jobs and execute them.

Deliberately **not** one long transaction: a job is claimed in a short write
transaction, executed with its own sessions (so a slow LLM call never holds the
SQLite write lock), then finalized in another short write transaction.
"""

from __future__ import annotations

import signal
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from apollo.db.repositories import infra
from apollo.observability import get_logger
from apollo.queue import jobs as qjobs

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.worker")

Handler = Callable[["JobContext"], dict[str, Any] | None]

POLL_INTERVAL_SECONDS = 1.0
LEASE_SECONDS = 300


@dataclass(slots=True)
class JobContext:
    runtime: Runtime
    job_id: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    worker_id: str = "worker"

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self.runtime.db.session() as session:
            yield session

    @contextmanager
    def write(self) -> Iterator[Session]:
        with self.runtime.db.write() as session:
            yield session


class Worker:
    def __init__(self, runtime: Runtime, worker_id: str | None = None) -> None:
        self.runtime = runtime
        self.worker_id = worker_id or f"{socket.gethostname()}:{id(self) & 0xFFFF:x}"
        self._stop = False
        self._handlers = _load_handlers()

    def request_stop(self, *_: object) -> None:
        self._stop = True

    def run(self, *, once: bool = False) -> None:
        if not once:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        log.info("worker.start", worker=self.worker_id, once=once)
        while not self._stop:
            handled = self._process_one()
            if once and not handled:
                break
            if not handled:
                time.sleep(POLL_INTERVAL_SECONDS)
        log.info("worker.stop", worker=self.worker_id)

    def _process_one(self) -> bool:
        job = self._claim()
        if job is None:
            return False
        job_id, kind, payload = job
        ctx = JobContext(
            runtime=self.runtime,
            job_id=job_id,
            kind=kind,
            payload=payload,
            worker_id=self.worker_id,
        )
        handler = self._handlers.get(kind)
        if handler is None:
            self._finalize(job_id, error=f"no handler for kind {kind!r}", retryable=False)
            log.error("worker.no_handler", kind=kind, job_id=job_id)
            return True
        try:
            result = handler(ctx) or {}
        except Exception as exc:
            self._finalize(job_id, error=f"{type(exc).__name__}: {exc}", retryable=True)
            log.warning("worker.job_failed", job_id=job_id, kind=kind, error=str(exc))
            return True
        self._finalize(job_id, result=result)
        log.info("worker.job_done", job_id=job_id, kind=kind)
        return True

    def _claim(self) -> tuple[int, str, dict[str, Any]] | None:
        with self.runtime.db.write() as session:
            if infra.is_paused(session):
                return None
            job = qjobs.claim_job(session, worker_id=self.worker_id, lease_seconds=LEASE_SECONDS)
            if job is None:
                return None
            return job.id, job.kind, dict(job.payload_json or {})

    def _finalize(
        self, job_id: int, *, result: dict[str, Any] | None = None, error: str | None = None,
        retryable: bool = True,
    ) -> None:
        with self.runtime.db.write() as session:
            if error is None:
                qjobs.complete_job(session, job_id, result)
            else:
                qjobs.fail_job(session, job_id, error, retryable=retryable)


def _load_handlers() -> dict[str, Handler]:
    from apollo.queue.handlers import HANDLERS

    return dict(HANDLERS)
