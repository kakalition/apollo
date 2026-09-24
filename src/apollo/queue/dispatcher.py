"""Dispatcher process: one scheduler, many responsibilities.

Every tick it (a) expires stale approvals, (b) requeues expired job leases,
(c) evaluates due cron rules, (d) drains unprocessed events into jobs, and
(e) evaluates condition predicates. A named advisory lock enforces the
single-dispatcher invariant.
"""

from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING, Any

from apollo.db.repositories import infra
from apollo.db.session import acquire_advisory_lock, release_advisory_lock
from apollo.observability import get_logger
from apollo.queue import jobs as qjobs
from apollo.queue.outbox import drain_events

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.dispatcher")

LOCK_NAME = "dispatcher"


class Dispatcher:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.interval = max(5, runtime.settings.scheduler.tick_seconds)
        self._stop = threading.Event()
        self._holds_lock = False

    def request_stop(self, *_: object) -> None:
        # Interruptible: the run loop waits on this event, so shutdown is immediate.
        self._stop.set()

    def run(self, *, once: bool = False) -> None:
        if not once:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        if not self._acquire_lock():
            log.error("dispatcher.lock_held", detail="another dispatcher is running")
            raise SystemExit("another dispatcher already holds the lock")
        log.info("dispatcher.start", interval=self.interval)
        try:
            while not self._stop.is_set():
                self.tick()
                if once:
                    break
                self._stop.wait(self.interval)
        finally:
            self._release_lock()
            log.info("dispatcher.stop")

    def _acquire_lock(self) -> bool:
        with self.runtime.db.write() as session:
            self._holds_lock = acquire_advisory_lock(session, LOCK_NAME)
            return self._holds_lock

    def _release_lock(self) -> None:
        if not self._holds_lock:
            return
        with self.runtime.db.write() as session:
            release_advisory_lock(session, LOCK_NAME)

    def tick(self) -> dict[str, Any]:
        from apollo.tools.clock import SystemClock

        clock = SystemClock(self.runtime.settings.app.timezone)
        now = clock.now()
        result: dict[str, Any] = {}
        with self.runtime.db.write() as session:
            paused = infra.is_paused(session)
            result["paused"] = paused
            result["approvals_expired"] = len(infra.expire_stale_actions(session, now))
            result["leases_requeued"] = len(qjobs.requeue_expired(session, now))
            if not paused:
                from apollo.scheduler.tick import run_tick

                result.update(run_tick(session, now, clock))
                result["events_drained"] = drain_events(session, now=now, paused=False)
            else:
                result["events_drained"] = 0
        log.info("dispatcher.tick", **{k: v for k, v in result.items() if isinstance(v, int)})
        return result
