"""Worker loop and the full outbox → job → run → notification path."""

from __future__ import annotations

from sqlalchemy import select

from apollo.db import tables as t
from apollo.queue.jobs import enqueue_job
from apollo.queue.worker import Worker
from apollo.telegram.outbox_drain import NotificationDrainer
from tests.fakes import fake_api


def test_worker_processes_vault_sync(runtime, settings) -> None:
    (settings.vault_path / "notes").mkdir(parents=True, exist_ok=True)
    (settings.vault_path / "notes" / "a.md").write_text("# Note\n\nSomething memorable.")
    with runtime.db.write() as session:
        enqueue_job(session, kind="vault.sync")

    Worker(runtime, worker_id="test-worker").run(once=True)

    with runtime.db.session() as session:
        jobs = list(session.execute(select(t.Job)).scalars())
        entries = list(session.execute(select(t.JournalEntry)).scalars())
    assert jobs[0].status == "done"
    assert len(entries) == 1


def test_worker_marks_unknown_kind_dead(runtime) -> None:
    with runtime.db.write() as session:
        job = enqueue_job(session, kind="not.a.kind")
    Worker(runtime, worker_id="w").run(once=True)
    with runtime.db.session() as session:
        stored = session.get(t.Job, job.id)
        assert stored is not None and stored.status == "dead"


def test_notification_drain_sends_and_marks(runtime, settings, clock) -> None:
    from apollo.db.repositories import infra

    with runtime.db.write() as session:
        infra.enqueue_notification(
            session,
            kind="generic",
            ref_id="1",
            payload={"text": "Hello", "topic": "system"},
            scheduled_for=clock.now(),
        )
    api = fake_api()
    drainer = NotificationDrainer(api, runtime, chat_id=42)

    import asyncio

    sent = asyncio.run(drainer.drain(limit=10, clock=clock))
    assert sent == 1
    with runtime.db.session() as session:
        rows = list(session.execute(select(t.Notification)).scalars())
    assert rows[0].status == "sent"


def test_notification_idempotency_key(runtime) -> None:
    from apollo.db.repositories import infra

    with runtime.db.write() as session:
        first = infra.enqueue_notification(session, kind="briefing", ref_id="2026-03-02", payload={"text": "a"})
    with runtime.db.write() as session:
        second = infra.enqueue_notification(session, kind="briefing", ref_id="2026-03-02", payload={"text": "b"})
    assert first.id == second.id
    with runtime.db.session() as session:
        assert len(list(session.execute(select(t.Notification)).scalars())) == 1


class _CapturingAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append({"chat_id": chat_id, "text": text, **kwargs})
        return None


def _deliver_one(runtime, clock, topic: str = "system") -> dict:
    import asyncio

    from apollo.db.repositories import infra
    from apollo.telegram.outbox_drain import NotificationDrainer

    with runtime.db.write() as session:
        infra.enqueue_notification(
            session,
            kind="routing-test",
            ref_id=topic,
            payload={"text": "hello", "topic": topic},
            scheduled_for=clock.now(),
        )
    api = _CapturingAPI()
    asyncio.run(
        NotificationDrainer(api, runtime, chat_id=42).drain(  # pyright: ignore[reportArgumentType]
            limit=5, clock=clock
        )
    )
    return api.calls[-1]


def test_notifications_use_main_chat_when_topics_disabled(runtime, clock) -> None:
    from apollo.db.repositories import infra
    from apollo.telegram.topics import TOPICS_KEY

    runtime.settings.telegram.topic_routing = False
    with runtime.db.write() as session:
        infra.set_setting(session, TOPICS_KEY, {"chat_id": 42, "threads": {"system": 999}})
    call = _deliver_one(runtime, clock)
    assert call["message_thread_id"] is None


def test_notifications_use_topic_when_routing_enabled(runtime, clock) -> None:
    from apollo.db.repositories import infra
    from apollo.telegram.topics import TOPICS_KEY

    runtime.settings.telegram.topic_routing = True
    with runtime.db.write() as session:
        infra.set_setting(session, TOPICS_KEY, {"chat_id": 42, "threads": {"system": 999}})
    call = _deliver_one(runtime, clock, topic="system")
    assert call["message_thread_id"] == 999


def test_markdown_notification_is_converted_and_safe(runtime, clock) -> None:
    import asyncio

    from apollo.db.repositories import infra
    from apollo.telegram.outbox_drain import NotificationDrainer

    markdown = "**Bold** & <tag>\n\n- item one\n- item two\n\nuse `code`"
    with runtime.db.write() as session:
        infra.enqueue_notification(
            session,
            kind="md",
            ref_id="1",
            payload={"text": markdown, "topic": "system", "format": "markdown"},
            scheduled_for=clock.now(),
        )
    api = _CapturingAPI()
    asyncio.run(
        NotificationDrainer(api, runtime, chat_id=42).drain(  # pyright: ignore[reportArgumentType]
            limit=5, clock=clock
        )
    )
    call = api.calls[0]
    assert call["parse_mode"] == "HTML"
    assert "<b>Bold</b>" in call["text"]
    assert "&amp;" in call["text"] and "&lt;tag&gt;" in call["text"]
    assert "**" not in call["text"]
    assert "<code>code</code>" in call["text"]
    assert "• item one" in call["text"]


def test_html_notification_is_not_re_escaped(runtime, clock) -> None:
    import asyncio

    from apollo.db.repositories import infra
    from apollo.telegram.outbox_drain import NotificationDrainer

    with runtime.db.write() as session:
        infra.enqueue_notification(
            session,
            kind="approval",
            ref_id="9",
            payload={"text": "<b>Approval needed</b>\nDo X?", "topic": "system", "format": "html"},
            scheduled_for=clock.now(),
        )
    api = _CapturingAPI()
    asyncio.run(
        NotificationDrainer(api, runtime, chat_id=42).drain(  # pyright: ignore[reportArgumentType]
            limit=5, clock=clock
        )
    )
    call = api.calls[0]
    assert call["parse_mode"] == "HTML"
    assert call["text"] == "<b>Approval needed</b>\nDo X?"


def test_reminder_fire_enqueues_urgent_notification(runtime) -> None:
    from apollo.queue.handlers import handle_reminder_fire
    from apollo.queue.worker import JobContext

    ctx = JobContext(runtime=runtime, job_id=7, kind="reminder.fire", payload={"text": "drink water"})
    out = handle_reminder_fire(ctx)
    with runtime.db.session() as session:
        notification = session.get(t.Notification, out["notification_id"])
    assert notification is not None
    assert notification.urgent is True
    assert "drink water" in notification.payload_json["text"]
