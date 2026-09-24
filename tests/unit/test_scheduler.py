"""Scheduler tick: cron firing, cooldown and period review provisioning."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from apollo.db import tables as t
from apollo.scheduler import routines
from apollo.scheduler.rules import add_rule, list_rules
from apollo.scheduler.tick import next_fire, run_tick
from apollo.tools.clock import FrozenClock


def _jobs(db) -> list[t.Job]:
    with db.session() as session:
        return list(session.execute(select(t.Job).order_by(t.Job.id)).scalars())


def test_cron_rule_fires_once_per_window(db, clock) -> None:
    with db.write() as session:
        add_rule(
            session,
            name="briefing",
            trigger_type="time",
            action="job",
            cron="0 7 * * *",
            payload={"job_kind": "briefing.generate"},
            cooldown_seconds=3600,
        )
    noon = clock.now().replace(hour=12)
    with db.write() as session:
        run_tick(session, noon, clock)
    assert [j.kind for j in _jobs(db)] == ["briefing.generate"]

    # Same tick window again: last_run_at has advanced past the previous fire.
    with db.write() as session:
        run_tick(session, noon + timedelta(minutes=1), clock)
    assert len(_jobs(db)) == 1


def test_condition_rule_fires_when_true(db, clock) -> None:
    with db.write() as session:
        add_rule(
            session,
            name="nudge",
            trigger_type="condition",
            action="skill",
            predicate="no_checkin_days(1)",
            payload={"skill": "drift-detect"},
            cooldown_seconds=86400,
        )
    with db.write() as session:
        result = run_tick(session, clock.now(), clock)
    assert result["condition_jobs"] == 1
    assert _jobs(db)[0].kind == "skill.run"


def test_condition_rule_skips_when_false(db, clock) -> None:
    from apollo.db.repositories import logs as logrepo
    from apollo.domain import models as m

    with db.write() as session:
        add_rule(
            session,
            name="nudge",
            trigger_type="condition",
            action="skill",
            predicate="no_checkin_days(1)",
            payload={"skill": "drift-detect"},
        )
        logrepo.log_checkin(session, m.CheckIn(kind=m.CheckInKind.REFLECTION, occurred_at=clock.now()))
    with db.write() as session:
        result = run_tick(session, clock.now(), clock)
    assert result["condition_jobs"] == 0


def test_seed_defaults_is_idempotent(db) -> None:
    with db.write() as session:
        first = routines.seed_defaults(session)
    with db.write() as session:
        second = routines.seed_defaults(session)
    assert first > 0 and second == 0
    with db.session() as session:
        names = {r.name for r in list_rules(session)}
    assert {"morning_briefing", "weekly_review", "vault_sync"} <= names


def test_ensure_period_reviews_creates_daily_weekly_monthly(db, clock) -> None:
    with db.write() as session:
        created = routines.ensure_period_reviews(session, clock)
    assert created == 3
    with db.write() as session:
        assert routines.ensure_period_reviews(session, clock) == 0


def test_cron_next_fire_respects_timezone() -> None:
    from datetime import UTC

    tz_clock = FrozenClock("2026-03-01T07:30:00+00:00", tz="America/New_York")
    nxt = next_fire("briefing_local", tz_clock.now(), tz_clock, "0 7 * * *")
    # 07:00 America/New_York == 12:00 UTC (EST, before DST on 2026-03-08).
    assert nxt is not None
    assert nxt.astimezone(tz_clock.tz).hour == 7
    assert nxt.astimezone(UTC).hour == 12


def test_cron_catches_up_after_missed_fire(db) -> None:
    tz_clock = FrozenClock("2026-03-01T07:30:00+00:00", tz="America/New_York")
    with db.write() as session:
        add_rule(
            session,
            name="briefing_local",
            trigger_type="time",
            action="job",
            cron="0 7 * * *",
            payload={"job_kind": "briefing.generate"},
        )
    with db.write() as session:
        run_tick(session, tz_clock.now(), tz_clock)
    # The most recent 07:00 local fire (yesterday) is caught up on first tick.
    assert [j.kind for j in _jobs(db)] == ["briefing.generate"]
