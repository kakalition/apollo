"""Inbound update handling: commands, free text, callbacks, polls, inline mode."""

from __future__ import annotations

import base64
import random
from typing import TYPE_CHECKING, Any

from apollo.db.repositories import domain as repo
from apollo.db.repositories import infra
from apollo.db.repositories import logs as logrepo
from apollo.domain import models as m
from apollo.observability import get_logger
from apollo.queue.jobs import enqueue_job
from apollo.telegram import approvals as approvals_mod
from apollo.telegram.api import TelegramAPI, TelegramError
from apollo.telegram.keyboards import (
    decode,
    inline_result_article,
    remove_reply_keyboard,
)
from apollo.telegram.models import CallbackQuery, InlineQuery, Message, PollAnswer, Update
from apollo.telegram.render import RichDocument, chunk, escape
from apollo.telegram.streaming import request_cancel
from apollo.telegram.topics import TopicRouter
from apollo.tools import db_tools
from apollo.tools.clock import SystemClock

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.handlers")

HELP_TEXT = (
    "<b>Apollo</b>\n"
    "Just talk to me — capture, log, ask. Or use a command:\n\n"
    "<b>Daily</b>\n"
    "/today — briefing · /focus — what to do now · /review — latest review\n"
    "/capture &lt;text&gt; · /log &lt;text&gt; — explicit capture\n\n"
    "<b>Look things up</b>\n"
    "/goals · /practices · /habits · /memory · /skills\n\n"
    "<b>Control</b>\n"
    "/approve — pending approvals · /pause · /resume · /settings · /help"
)

QUICK_COMMANDS = {
    "/today",
    "/goals",
    "/practices",
    "/habits",
    "/review",
    "/focus",
    "/memory",
    "/skills",
    "/approve",
    "/settings",
    "/help",
    "/start",
    "/pause",
    "/resume",
}


# ---------------------------------------------------------------------------
# Enqueueing agent work
# ---------------------------------------------------------------------------
def enqueue_agent_run(
    runtime: Runtime,
    *,
    text: str,
    topic: str | None,
    message_thread_id: int | None,
    telegram_user_id: int,
    agent: str | None = None,
    stream: bool = True,
) -> int:
    run_id = f"tg{random.randint(0, 2**31 - 1):x}"
    payload: dict[str, Any] = {
        "run_id": run_id,
        "text": text,
        "topic": topic,
        "telegram_user_id": telegram_user_id,
        "conversation_id": f"tg:{telegram_user_id}:{topic or 'main'}",
    }
    if agent:
        payload["agent"] = agent
    if stream and runtime.settings.telegram.bot_token:
        payload["stream"] = {
            "chat_id": telegram_user_id,
            "message_thread_id": message_thread_id,
            "draft_id": random.randint(1, 2**31 - 1),
            "can_stop": True,
        }
    with runtime.db.write() as session:
        job = enqueue_job(session, kind="agent.run", payload=payload, priority=3)
        return int(job.id)


def enqueue_skill_run(
    runtime: Runtime,
    *,
    skill: str,
    text: str,
    topic: str | None,
    message_thread_id: int | None,
    telegram_user_id: int,
) -> int:
    payload: dict[str, Any] = {
        "skill": skill,
        "text": text,
        "topic": topic,
        "telegram_user_id": telegram_user_id,
    }
    if runtime.settings.telegram.bot_token:
        payload["stream"] = {
            "chat_id": telegram_user_id,
            "message_thread_id": message_thread_id,
            "draft_id": random.randint(1, 2**31 - 1),
            "can_stop": True,
        }
    with runtime.db.write() as session:
        job = enqueue_job(session, kind="skill.run", payload=payload, priority=3)
        return int(job.id)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
async def dispatch(
    runtime: Runtime, api: TelegramAPI, update: Update, router: TopicRouter
) -> None:
    if update.message is not None:
        await handle_message(runtime, api, update.message, router)
    elif update.callback_query is not None:
        await handle_callback(runtime, api, update.callback_query, router)
    elif update.poll_answer is not None:
        handle_poll_answer(runtime, update.poll_answer)
    elif update.inline_query is not None:
        await handle_inline(runtime, api, update.inline_query, router)
    elif update.stopped_message_generation is not None:
        draft_id = update.stopped_message_generation.draft_id
        request_cancel(runtime, draft_id)
        log.info("telegram.generation_stopped", draft_id=draft_id)


async def handle_message(
    runtime: Runtime, api: TelegramAPI, message: Message, router: TopicRouter
) -> None:
    text = (message.text or "").strip()
    routing = runtime.settings.telegram.topic_routing
    if not routing and message.message_thread_id is not None:
        # Single-chat mode: answer in the main thread even if a topic id arrives.
        message = message.model_copy(update={"message_thread_id": None})
    topic = (router.slug_for_thread(message.message_thread_id) or "inbox") if routing else None
    user_id = message.from_user.id if message.from_user else message.chat.id

    if message.voice is not None:
        await _handle_voice(runtime, api, message, topic)
        return

    if text.startswith("/"):
        await _handle_command(runtime, api, message, text, topic or "inbox")
        return

    if _is_quick_tap(text):
        text = _map_quick_tap(text)
        if text is None:
            return

    if not text:
        return

    enqueue_agent_run(
        runtime,
        text=text,
        topic=topic,
        message_thread_id=message.message_thread_id,
        telegram_user_id=user_id,
        agent=_forced_agent(runtime, topic),
    )
    await _ack(api, message)


async def _handle_command(
    runtime: Runtime, api: TelegramAPI, message: Message, text: str, topic: str
) -> None:
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()
    user_id = message.from_user.id if message.from_user else message.chat.id
    thread = message.message_thread_id

    if command in ("/start", "/help"):
        deep = _decode_start(argument)
        if deep:
            enqueue_agent_run(
                runtime, text=deep, topic="inbox", message_thread_id=thread,
                telegram_user_id=user_id, agent="triage", stream=False,
            )
            await _reply(api, message, "Captured from deep link.")
            return
        # No keyboard on start: clear any persistent one left over from earlier.
        await _reply(
            api, message, HELP_TEXT, parse_mode="HTML", reply_markup=remove_reply_keyboard()
        )
        return

    if command in ("/capture", "/log"):
        if argument.strip():
            enqueue_agent_run(
                runtime, text=argument.strip(), topic="inbox", message_thread_id=thread,
                telegram_user_id=user_id, agent="triage", stream=False,
            )
            await _reply(api, message, "Logged.")
        else:
            await _reply(api, message, "Send the text after the command, or just type it.")
        return

    if command == "/today":
        enqueue_skill_run(
            runtime, skill="daily-briefing", text="Produce today's briefing.",
            topic="today", message_thread_id=thread, telegram_user_id=user_id,
        )
        await _reply(api, message, "Putting your day together…")
        return

    if command == "/pause":
        with runtime.db.write() as session:
            infra.set_paused(session, True)
        await _reply(api, message, "⏸ Paused. The bot still receives messages; jobs are held.")
        return

    if command == "/resume":
        with runtime.db.write() as session:
            infra.set_paused(session, False)
        await _reply(api, message, "▶️ Resumed.")
        return

    if command == "/approve":
        await _list_approvals(runtime, api, message)
        return

    if command == "/settings":
        await _show_settings(runtime, api, message)
        return

    # Read-only quick views, rendered directly from SQLite (no model call).
    clock = SystemClock(runtime.settings.app.timezone)
    with runtime.db.session() as session:
        if command == "/goals":
            goals = repo.list_goals(session, status=m.GoalStatus.ACTIVE)
            doc = RichDocument(title="Goals")
            doc.bullet_list([f"{g.title} (#{g.id})" for g in goals] or ["No active goals."])
        elif command == "/practices":
            items = [
                f"{p.name} — {p.cadence or 'no cadence'} (#{p.id})"
                for p in repo.list_practices(session, status=m.PracticeStatus.ACTIVE)
            ]
            doc = RichDocument(title="Practices")
            doc.bullet_list(items or ["No active practices."])
        elif command == "/habits":
            items = [
                f"{h.name} — streak {h.current_streak} (best {h.best_streak})"
                for h in repo.list_habits(session)
            ]
            doc = RichDocument(title="Habits")
            doc.bullet_list(items or ["No habits yet."])
        elif command == "/focus":
            items = db_tools.what_should_i_do_now(session, clock, limit=5)
            doc = RichDocument(title="Focus now")
            doc.bullet_list([f"{i['reason']}: {i.get('title') or i.get('name')}" for i in items] or ["Nothing pressing."])
        elif command == "/review":
            latest = db_tools.get_review(session, None)
            doc = RichDocument(title="Latest review")
            summary = (latest or {}).get("summary") or "No review yet."
            doc.paragraph(str(summary))
        elif command == "/memory":
            memory_all = session.execute(
                __import__("sqlalchemy").select(__import__("apollo.db.tables", fromlist=["JournalEntry"]).JournalEntry)
            ).scalars().all()
            doc = RichDocument(title="Memory")
            doc.paragraph(f"{len(memory_all)} journal entries indexed. Use recall from MCP.")
        elif command == "/skills":
            from apollo.skills.registry import SkillRegistry

            registry = SkillRegistry(runtime.settings.root / "skills")
            registry.load()
            doc = RichDocument(title="Skills")
            doc.bullet_list([f"{s.name}: {s.description}" for s in registry.all()] or ["No skills found."])
        else:
            await _reply(api, message, "Unknown command. Try /help.")
            return
    await _reply(api, message, doc.to_html(), parse_mode="HTML")


async def handle_callback(
    runtime: Runtime, api: TelegramAPI, query: CallbackQuery, router: TopicRouter
) -> None:
    if not query.data:
        await api.answer_callback_query(query.id)
        return
    action, entity, ident = decode(query.data)
    chat_id = query.message.chat.id if query.message else None
    message_id = query.message.message_id if query.message else None

    if entity == "action":
        decision = {"approve": "approved", "deny": "denied", "edit": "pending"}.get(action, "denied")
        if action == "edit":
            await api.answer_callback_query(query.id, text="Send the corrected version as a message.")
            return
        await approvals_mod.decide(
            api, runtime, action_id=int(ident), decision=decision,
            decided_by=str(query.from_user.id), chat_id=chat_id, message_id=message_id,
        )
        await api.answer_callback_query(query.id, text=f"{decision.title()} ✓")
        return

    if entity in ("task", "habit"):
        await _handle_entity_action(runtime, api, query, action, entity, ident)
        return

    if entity == "focus" or entity == "today":
        await api.answer_callback_query(query.id, text="Noted.")
        return

    if action == "goal" and entity == "view":
        with runtime.db.session() as session:
            goal = db_tools.get_goal(session, int(ident))
        text = f"Goal #{ident}" if goal is None else escape(goal.get("title", "goal"))
        await api.answer_callback_query(query.id, text=text[:200])
        return

    await api.answer_callback_query(query.id)


async def _handle_entity_action(
    runtime: Runtime, api: TelegramAPI, query: CallbackQuery, action: str, entity: str, ident: str
) -> None:
    parts = ident.split(":")
    entity_id = int(parts[0])
    arg = parts[1] if len(parts) > 1 else None
    with runtime.db.write() as session:
        if action == "done" and entity == "task":
            repo.complete_task(session, entity_id, actor="telegram")
            toast = "Done ✓"
        elif action == "done" and entity == "habit":
            logrepo.log_habit(session, entity_id, source="telegram")
            toast = "Logged ✓"
        elif action == "skip":
            toast = "Skipped"
        elif action == "snooze" and entity == "task":
            task = repo.get_task(session, entity_id)
            if task and task.due_at and arg == "1d":
                from datetime import timedelta

                repo.update_task(session, entity_id, due_at=task.due_at + timedelta(days=1))
            elif task and task.due_at:
                from datetime import timedelta

                repo.update_task(session, entity_id, due_at=task.due_at + timedelta(hours=1))
            toast = "Snoozed"
        elif action == "resched":
            toast = "Send the new time as a message."
        elif action == "block":
            toast = "Time-blocking needs the calendar MCP server."
        else:
            toast = "Noted"
    await api.answer_callback_query(query.id, text=toast)


def handle_poll_answer(runtime: Runtime, answer: PollAnswer) -> None:
    from apollo.telegram.polls import record_poll_answer

    clock = SystemClock(runtime.settings.app.timezone)
    try:
        record_poll_answer(runtime, answer, clock)
    except Exception as exc:
        log.warning("polls.answer_failed", error=str(exc))


async def handle_inline(
    runtime: Runtime, api: TelegramAPI, inline: InlineQuery, router: TopicRouter
) -> None:
    clock = SystemClock(runtime.settings.app.timezone)
    with runtime.db.session() as session:
        view = db_tools.today_view(session, clock)
    lines = [f"• {t['title']}" for t in view["tasks_due"]] or ["Nothing due today."]
    text = "<b>Today</b>\n" + "\n".join(escape(line) for line in lines)
    results = [inline_result_article("today", "Today's plan", "Tasks due today", text)]
    await api.answer_inline_query(inline.id, results)


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------
async def _handle_voice(
    runtime: Runtime, api: TelegramAPI, message: Message, topic: str | None
) -> None:
    from apollo.telegram.voice import stt_available, transcribe_voice

    if message.voice is None:
        return
    if not stt_available():
        await _reply(api, message, "Voice capture is not enabled. Install the `voice` extra.")
        return
    await api.send_chat_action(message.chat.id, "record_voice", message_thread_id=message.message_thread_id)
    transcript = await transcribe_voice(api, message.voice.file_id)
    if not transcript:
        await _reply(api, message, "Could not transcribe that voice note.")
        return
    user_id = message.from_user.id if message.from_user else message.chat.id
    enqueue_agent_run(
        runtime, text=transcript, topic=topic, message_thread_id=message.message_thread_id,
        telegram_user_id=user_id, agent=_forced_agent(runtime, topic), stream=False,
    )
    await _reply(api, message, f"Transcribed: {escape(transcript[:200])}", parse_mode="HTML")


def _forced_agent(runtime: Runtime, topic: str | None) -> str | None:
    """With topic routing on, an Inbox message is a capture; otherwise the
    supervisor decides the specialist from natural language."""
    if runtime.settings.telegram.topic_routing and topic == "inbox":
        return "triage"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _list_approvals(runtime: Runtime, api: TelegramAPI, message: Message) -> None:
    with runtime.db.session() as session:
        actions = infra.list_pending_actions(session)
    lines = []
    for action in actions:
        summary = (action.payload_json or {}).get("summary", action.kind)
        lines.append(f"#{action.id} {summary}")
    body = "\n".join(escape(line) for line in lines) if lines else "None."
    await _reply(api, message, "<b>Pending approvals</b>\n" + body, parse_mode="HTML")


async def _show_settings(runtime: Runtime, api: TelegramAPI, message: Message) -> None:
    with runtime.db.session() as session:
        paused = infra.is_paused(session)
        router = TopicRouter.load(session)
    briefing = "text"
    lines = [
        f"paused: {paused}",
        f"timezone: {runtime.settings.app.timezone}",
        f"topic routing: {runtime.settings.telegram.topic_routing}",
        f"topics provisioned: {router.provisioned}",
        f"briefing: {briefing}",
        f"quiet hours: {runtime.settings.telegram.quiet_hours.get('start')} to {runtime.settings.telegram.quiet_hours.get('end')}",
    ]
    await _reply(
        api, message,
        "<b>Settings</b>\n" + "\n".join(escape(line) for line in lines),
        parse_mode="HTML",
        reply_markup=remove_reply_keyboard(),
    )


async def _reply(api: TelegramAPI, message: Message, text: str, *, parse_mode: str | None = None, reply_markup: dict[str, Any] | None = None) -> None:
    parts = chunk(text)
    for index, part in enumerate(parts):
        try:
            await api.send_message(
                message.chat.id, part,
                message_thread_id=message.message_thread_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup if index == len(parts) - 1 else None,
            )
        except TelegramError as exc:
            log.warning("telegram.reply_failed", error=str(exc))
            break


async def _ack(api: TelegramAPI, message: Message) -> None:
    """Acknowledge a capture with a reaction (no extra message)."""
    try:
        await api.set_message_reaction(message.chat.id, message.message_id, [{"type": "emoji", "emoji": "✅"}])
    except Exception as exc:
        log.debug("telegram.reaction_failed", error=str(exc))


def _is_quick_tap(text: str) -> bool:
    return text in {"✅ Done", "⏭ Skip", "🕐 Later", "📝 Note", "🎤 Voice"}


def _map_quick_tap(text: str) -> str | None:
    mapping = {
        "✅ Done": "Done",
        "⏭ Skip": "Skip",
        "🕐 Later": "Later",
    }
    if text == "📝 Note":
        return None
    if text == "🎤 Voice":
        return None
    return mapping.get(text, text)


def _decode_start(argument: str) -> str | None:
    """Decode ``start=capture_<base64url>`` (≤64 chars, A-Za-z0-9_-)."""
    if not argument:
        return None
    payload = argument
    if payload.startswith("capture"):
        payload = payload[len("capture") :].lstrip("_")
        if not payload:
            return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8")
    except Exception:
        return None
