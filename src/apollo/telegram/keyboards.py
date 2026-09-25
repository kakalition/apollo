"""Keyboards and callback_data encoding.

``callback_data`` is ``<action>:<entity>:<id>`` (compact, ≤64 bytes). Buttons can be
disabled in place after a decision (Bot API 10.3 ``InlineKeyboardButton.disabled``).
"""

from __future__ import annotations

from typing import Any

MAX_CALLBACK_BYTES = 64


def encode(action: str, entity: str = "-", ident: str | int = "-") -> str:
    data = f"{action}:{entity}:{ident}"
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data too long: {data!r}")
    return data


def decode(data: str) -> tuple[str, str, str]:
    parts = data.split(":", 2)
    while len(parts) < 3:
        parts.append("-")
    return parts[0], parts[1], parts[2]


def button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    copy_text: str | None = None,
    disabled: bool = False,
    style: str | None = None,
    icon_custom_emoji_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": text}
    if callback_data is not None:
        payload["callback_data"] = callback_data
    if url is not None:
        payload["url"] = url
    if copy_text is not None:
        payload["copy_text"] = {"text": copy_text}
    if disabled:
        payload["disabled"] = True
    if style is not None:
        payload["style"] = style
    if icon_custom_emoji_id is not None:
        payload["icon_custom_emoji_id"] = icon_custom_emoji_id
    return payload


def inline_keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}


def approval_keyboard(
    action_id: int,
    *,
    decided: str | None = None,
    force_reply: bool = False,
) -> dict[str, Any]:
    approve = button(
        "✅ Approve",
        callback_data=encode("approve", "action", action_id),
        disabled=decided is not None,
    )
    edit = button(
        "✏️ Edit",
        callback_data=encode("edit", "action", action_id),
        disabled=decided is not None,
    )
    deny = button(
        "❌ Deny",
        callback_data=encode("deny", "action", action_id),
        disabled=decided is not None,
    )
    markup = inline_keyboard([[approve, edit, deny]])
    if force_reply:
        markup["force_reply"] = True
    return markup


def task_keyboard(task_id: int) -> dict[str, Any]:
    return inline_keyboard(
        [
            [
                button("Done", callback_data=encode("done", "task", task_id)),
                button("Snooze 1h", callback_data=encode("snooze", "task", f"{task_id}:1h")),
                button("Snooze 1d", callback_data=encode("snooze", "task", f"{task_id}:1d")),
            ],
            [
                button("Reschedule", callback_data=encode("resched", "task", task_id)),
                button("Block 30m", callback_data=encode("block", "task", f"{task_id}:30")),
                button("Not today", callback_data=encode("skip", "task", task_id)),
            ],
            [button("📋 Copy", copy_text=f"task #{task_id}")],
        ]
    )


def habit_keyboard(habit_id: int) -> dict[str, Any]:
    return inline_keyboard(
        [
            [
                button("✅ Done", callback_data=encode("done", "habit", habit_id)),
                button("⏭ Skip", callback_data=encode("skip", "habit", habit_id)),
            ]
        ]
    )


def remove_reply_keyboard() -> dict[str, Any]:
    return {"remove_keyboard": True}


def inline_result_article(
    result_id: str,
    title: str,
    description: str,
    message_text: str,
    *,
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    return {
        "type": "article",
        "id": result_id,
        "title": title,
        "description": description,
        "input_message_content": {"message_text": message_text, "parse_mode": parse_mode},
    }
