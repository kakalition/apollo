"""Apollo CLI (Typer). Admin, migrations, inspection, one-off runs and processes."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from apollo import __version__
from apollo.bootstrap import Runtime, bootstrap

app = typer.Typer(
    name="apollo",
    help="Apollo — single-user, local-first personal agent platform.",
    no_args_is_help=True,
    add_completion=False,
)

queue_app = typer.Typer(help="Inspect and manage the job queue.", no_args_is_help=True)
schedule_app = typer.Typer(help="Inspect and manage schedule rules.", no_args_is_help=True)
mcp_app = typer.Typer(help="MCP client registry and server.", no_args_is_help=True)
vault_app = typer.Typer(help="Vault sync and search.", no_args_is_help=True)
memory_app = typer.Typer(help="Memory recall and reindex.", no_args_is_help=True)
topics_app = typer.Typer(help="Private-chat topic provisioning state.", no_args_is_help=True)
app.add_typer(queue_app, name="queue")
app.add_typer(schedule_app, name="schedule")
app.add_typer(mcp_app, name="mcp-servers")
app.add_typer(vault_app, name="vault")
app.add_typer(memory_app, name="memory")
app.add_typer(topics_app, name="topics")


def _runtime(require_db: bool = True) -> Runtime:
    return bootstrap(require_db=require_db)


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
@app.command()
def version() -> None:
    """Print the Apollo version."""
    typer.echo(f"apollo {__version__}")


@app.command()
def doctor() -> None:
    """Run preflight checks (DB, vault, provider, embeddings, Chroma, Telegram)."""
    from apollo.config import load_settings
    from apollo.doctor import all_ok, run_checks

    settings = load_settings()
    results = run_checks(settings)
    for r in results:
        mark = "ok  " if r.ok else ("FAIL" if r.fatal else "warn")
        line = f"[{mark}] {r.name}: {r.detail}"
        if r.fallback and not r.ok:
            line += f"\n        → {r.fallback}"
        typer.echo(line)
    if not all_ok(results):
        raise typer.Exit(code=1)


@app.command("init-db")
def init_db(
    seed: Annotated[bool, typer.Option(help="Seed default areas and schedule routines.")] = True,
) -> None:
    """Create the database schema and FTS index."""
    from apollo.db.migrate import ensure_schema

    rt = _runtime(require_db=False)
    try:
        ensure_schema(rt.settings)
        typer.echo(f"schema ready at {rt.settings.db_file}")
        if seed:
            from apollo.scheduler.routines import seed_defaults

            with rt.db.write() as session:
                created = seed_defaults(session)
            typer.echo(f"seeded {created} defaults")
    finally:
        rt.close()


@app.command()
def upgrade(revision: str = "head") -> None:
    """Apply migrations up to REVISION."""
    from apollo.db.migrate import upgrade as _upgrade

    rt = _runtime(require_db=False)
    try:
        _upgrade(rt.settings, revision)
        typer.echo(f"upgraded to {revision}")
    finally:
        rt.close()


@app.command()
def schema() -> None:
    """Show the current migration revision."""
    from apollo.db.migrate import current

    rt = _runtime(require_db=False)
    try:
        current(rt.settings)
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Kill switch & status
# ---------------------------------------------------------------------------
@app.command()
def pause() -> None:
    """Halt job claiming and scheduled runs (does not stop the Telegram bot)."""
    from apollo.db.repositories import infra

    rt = _runtime()
    try:
        with rt.db.write() as session:
            infra.set_paused(session, True)
        typer.echo("apollo paused")
    finally:
        rt.close()


@app.command()
def resume() -> None:
    """Resume job claiming and scheduled runs."""
    from apollo.db.repositories import infra

    rt = _runtime()
    try:
        with rt.db.write() as session:
            infra.set_paused(session, False)
        typer.echo("apollo resumed")
    finally:
        rt.close()


@app.command()
def status() -> None:
    """Show pause flag, queue depth and pending approvals."""
    from sqlalchemy import func, select

    from apollo.db import tables as t
    from apollo.db.repositories import infra

    rt = _runtime()
    try:
        with rt.db.session() as session:
            paused = infra.is_paused(session)
            counts = {
                status: session.execute(
                    select(func.count()).select_from(t.Job).where(t.Job.status == status)
                ).scalar_one()
                for status in ("pending", "running", "failed", "dead", "done")
            }
            approvals = session.execute(
                select(func.count())
                .select_from(t.PendingAction)
                .where(t.PendingAction.status == "pending")
            ).scalar_one()
        typer.echo(f"paused={paused}")
        typer.echo("jobs: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        typer.echo(f"pending approvals={approvals}")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
@app.command()
def worker(
    once: Annotated[bool, typer.Option(help="Drain available jobs once, then exit.")] = False,
) -> None:
    """Run the worker: claim jobs, run agents/skills, own Mem0 writes."""
    from apollo.queue.worker import Worker

    rt = _runtime()
    try:
        Worker(rt).run(once=once)
    finally:
        rt.close()


@app.command()
def dispatcher(
    once: Annotated[bool, typer.Option(help="Evaluate a single tick, then exit.")] = False,
) -> None:
    """Run the dispatcher: scheduler tick, event drain, retries."""
    from apollo.queue.dispatcher import Dispatcher

    rt = _runtime()
    try:
        Dispatcher(rt).run(once=once)
    finally:
        rt.close()


@app.command()
def telegram() -> None:
    """Run the Telegram bot (long polling)."""
    from apollo.telegram.bot import run_bot

    asyncio.run(run_bot())


@app.command("mcp")
def mcp_serve() -> None:
    """Run the Apollo MCP server over stdio."""
    from apollo.mcp.server import main as mcp_main

    mcp_main()


@app.command()
def run(
    agent: Annotated[str, typer.Option(help="Agent to run: triage, planner, coach, research.")] = "triage",
    text: Annotated[str, typer.Argument(help="Input text.")] = "",
) -> None:
    """One-off agent run (writes a RunLog)."""
    from apollo.agents.runtime import run_agent_once

    rt = _runtime()
    try:
        output = asyncio.run(run_agent_once(rt, agent, text))
        typer.echo(output)
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
@queue_app.command("list")
def queue_list(
    status: Annotated[str | None, typer.Option(help="Filter by status.")] = None,
    limit: int = 20,
) -> None:
    from sqlalchemy import select

    from apollo.db import tables as t

    rt = _runtime()
    try:
        with rt.db.session() as session:
            stmt = select(t.Job).order_by(t.Job.id.desc()).limit(limit)
            if status:
                stmt = stmt.where(t.Job.status == status)
            for job in session.execute(stmt).scalars():
                typer.echo(
                    f"#{job.id} {job.kind} status={job.status} attempts={job.attempts} "
                    f"run_after={job.run_after} error={job.error or ''}"
                )
    finally:
        rt.close()


@queue_app.command("retry")
def queue_retry(job_id: int) -> None:
    from apollo.queue.jobs import retry_job

    rt = _runtime()
    try:
        with rt.db.write() as session:
            retry_job(session, job_id)
        typer.echo(f"job {job_id} requeued")
    finally:
        rt.close()


@queue_app.command("replay")
def queue_replay(job_id: int) -> None:
    from apollo.queue.jobs import clone_job

    rt = _runtime()
    try:
        with rt.db.write() as session:
            new_id = clone_job(session, job_id)
        typer.echo(f"job {job_id} replayed as {new_id}")
    finally:
        rt.close()


@queue_app.command("purge")
def queue_purge(
    status: Annotated[str, typer.Option(help="Status to purge.")] = "dead",
) -> None:
    from sqlalchemy import delete

    from apollo.db import tables as t

    rt = _runtime()
    try:
        with rt.db.write() as session:
            result = session.execute(delete(t.Job).where(t.Job.status == status))
            purged = getattr(result, "rowcount", 0) or 0
        typer.echo(f"purged {purged} {status} jobs")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
@schedule_app.command("list")
def schedule_list() -> None:
    from sqlalchemy import select

    from apollo.db import tables as t

    rt = _runtime()
    try:
        with rt.db.session() as session:
            for rule in session.execute(select(t.ScheduleRule).order_by(t.ScheduleRule.id)).scalars():
                trigger = rule.cron or rule.event_type or rule.predicate
                typer.echo(
                    f"#{rule.id} {rule.name} [{rule.trigger_type}:{trigger}] "
                    f"action={rule.action} enabled={rule.enabled}"
                )
    finally:
        rt.close()


@schedule_app.command("toggle")
def schedule_toggle(name: str) -> None:
    from apollo.scheduler.rules import toggle_rule

    rt = _runtime()
    try:
        with rt.db.write() as session:
            enabled = toggle_rule(session, name)
        typer.echo(f"{name} enabled={enabled}")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------
@vault_app.command("sync")
def vault_sync() -> None:
    from apollo.tools.vault import Vault

    rt = _runtime()
    try:
        with rt.db.write() as session:
            stats = Vault(rt.settings.vault_path).sync(session)
        typer.echo(f"vault sync: +{stats.added} ~{stats.updated} -{stats.removed}")
    finally:
        rt.close()


@vault_app.command("search")
def vault_search(query: str, limit: int = 10) -> None:
    from apollo.db.fts import search_vault

    rt = _runtime()
    try:
        with rt.db.session() as session:
            for hit in search_vault(session.connection(), query, limit=limit):
                typer.echo(f"{hit['body_path']}  {hit['snippet']}")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
@memory_app.command("recall")
def memory_recall(query: str, k: int = 6) -> None:
    from apollo.memory.facade import build_memory

    rt = _runtime()
    try:
        memory = build_memory(rt)
        for mem in memory.recall(query, k=k):
            typer.echo(f"- {mem.text}")
    finally:
        rt.close()


@memory_app.command("reindex")
def memory_reindex() -> None:
    from apollo.queue.jobs import enqueue_job

    rt = _runtime()
    try:
        with rt.db.write() as session:
            enqueue_job(session, kind="memory.reindex", payload={}, priority=8)
        typer.echo("memory.reindex enqueued")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
@topics_app.command("list")
def topics_list() -> None:
    """Show the provisioned private-chat topics and whether routing is enabled."""
    from apollo.telegram.topics import TopicRouter

    rt = _runtime()
    try:
        with rt.db.session() as session:
            router = TopicRouter.load(session)
        typer.echo(f"topic_routing={rt.settings.telegram.topic_routing} chat_id={router.chat_id}")
        for slug, thread_id in sorted(router.threads.items()):
            typer.echo(f"  {slug}: {thread_id}")
        if not router.threads:
            typer.echo("  (none provisioned)")
    finally:
        rt.close()


@topics_app.command("reset")
def topics_reset() -> None:
    """Forget provisioned topics (does not delete them in Telegram)."""
    from apollo.db.repositories import infra
    from apollo.telegram.topics import TOPICS_KEY

    rt = _runtime()
    try:
        with rt.db.write() as session:
            infra.delete_setting(session, TOPICS_KEY)
        typer.echo("topic mapping cleared; delete the topics in Telegram if they remain visible")
    finally:
        rt.close()


# ---------------------------------------------------------------------------
# MCP client registry
# ---------------------------------------------------------------------------
@mcp_app.command("list")
def mcp_servers_list() -> None:
    rt = _runtime(require_db=False)
    try:
        for name, server in rt.settings.mcp.servers.items():
            typer.echo(
                f"{name}: transport={server.transport} namespace={server.namespace or name} "
                f"allowlist={server.allowlist}"
            )
    finally:
        rt.close()


@mcp_app.command("check")
def mcp_servers_check() -> None:
    from apollo.mcp.client import check_registry

    rt = _runtime(require_db=False)
    try:
        for name, ok, detail in asyncio.run(check_registry(rt.settings)):
            typer.echo(f"[{'ok' if ok else 'FAIL'}] {name}: {detail}")
    finally:
        rt.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
