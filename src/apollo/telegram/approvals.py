"""Approvals: rendering, callback decisions and in-place message updates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apollo.db.repositories import infra
from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI
from apollo.telegram.keyboards import approval_keyboard, encode

if TYPE_CHECKING:
    from apollo.bootstrap import Runtime

log = get_logger("apollo.telegram.approvals")

DECISION_LABELS = {
    "approved": "✅ Approved",
    "denied": "❌ Denied",
    "expired": "⌛ Expired (auto-denied)",
}


def approval_text(action: Any) -> str:
    payload = action.payload_json or {}
    summary = payload.get("summary") or payload.get("text") or action.kind
    return (
        f"<b>Approval needed</b>\n{summary}\n\n"
        f"<i>kind: {action.kind}"
        + (f" · run: {action.run_id}" if action.run_id else "")
        + "</i>"
    )


def outcome_text(action: Any, decision: str) -> str:
    label = DECISION_LABELS.get(decision, decision)
    summary = (action.payload_json or {}).get("summary", action.kind)
    return f"<b>{label}</b>\n{summary}\n\n<i>kind: {action.kind}</i>"


async def decide(
    api: TelegramAPI,
    runtime: Runtime,
    *,
    action_id: int,
    decision: str,
    decided_by: str,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> dict[str, Any]:
    with runtime.db.write() as session:
        action = infra.decide_action(session, action_id, decision, decided_by=decided_by)
    if chat_id and message_id:
        try:
            await api.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=outcome_text(action, action.status),
                parse_mode="HTML",
                reply_markup=approval_keyboard(action_id, decided=action.status),
            )
        except Exception as exc:
            log.warning("approval.edit_failed", error=str(exc))
    return {"approval_id": action_id, "status": action.status}


def actions_for(action_id: int) -> list[dict[str, Any]]:
    return [{"approval_id": action_id}]


def encode_decision(decision: str, action_id: int) -> str:
    return encode(decision, "action", action_id)
