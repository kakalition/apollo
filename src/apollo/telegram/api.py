"""Thin typed raw-method layer over the Telegram Bot API (10.3).

python-telegram-bot does not yet wrap the newest methods (``sendMessageDraft``,
``sendRichMessage``, ``sendChecklist``, ``editEphemeralMessage*``), so Apollo talks
to those over httpx directly with Pydantic-validated responses. PTB is used only for
the update loop and handler dispatch.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from apollo.telegram.models import (
    BotCommand,
    Chat,
    File,
    Message,
    Update,
    User,
)

DEFAULT_BASE_URL = "https://api.telegram.org"


class TelegramError(RuntimeError):
    def __init__(
        self,
        method: str,
        status: int,
        description: str,
        *,
        retry_after: float | None = None,
        error_code: int | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{method} failed ({status}): {description}")
        self.method = method
        self.status = status
        self.description = description
        self.retry_after = retry_after
        self.error_code = error_code
        self.parameters = parameters or {}

    @property
    def is_rate_limited(self) -> bool:
        return self.status == 429 or self.retry_after is not None


class TelegramAPI:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/bot{token}",
            transport=transport,
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> TelegramAPI:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # -- raw call ----------------------------------------------------------
    async def call(self, method: str, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None}
        response = await self._client.post(f"/{method}", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"ok": False, "description": response.text}
        if not body.get("ok"):
            parameters = body.get("parameters") or {}
            raise TelegramError(
                method,
                response.status_code,
                str(body.get("description", "unknown error")),
                retry_after=parameters.get("retry_after"),
                error_code=body.get("error_code"),
                parameters=parameters,
            )
        return body.get("result")

    # -- bot identity & setup ---------------------------------------------
    async def get_me(self) -> User:
        return User.model_validate(await self.call("getMe"))

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> list[Update]:
        result = await self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=allowed_updates,
        )
        return [Update.model_validate(item) for item in result]

    async def set_my_commands(
        self,
        commands: Sequence[BotCommand | dict[str, str]],
        *,
        scope: dict[str, Any] | None = None,
        language_code: str | None = None,
    ) -> bool:
        payload = [_as_dict(c) for c in commands]
        return bool(await self.call("setMyCommands", commands=payload, scope=scope, language_code=language_code))

    async def set_my_name(self, name: str) -> bool:
        return bool(await self.call("setMyName", name=name))

    async def set_my_description(self, description: str) -> bool:
        return bool(await self.call("setMyDescription", description=description))

    async def set_my_short_description(self, short_description: str) -> bool:
        return bool(await self.call("setMyShortDescription", short_description=short_description))

    async def set_chat_menu_button(self, *, chat_id: int | None = None, menu_button: dict[str, Any] | None = None) -> bool:
        return bool(await self.call("setChatMenuButton", chat_id=chat_id, menu_button=menu_button))

    # -- messages ----------------------------------------------------------
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        reply_parameters: dict[str, Any] | None = None,
        link_preview_options: dict[str, Any] | None = None,
        disable_notification: bool | None = None,
    ) -> Message:
        return Message.model_validate(
            await self.call(
                "sendMessage",
                chat_id=chat_id,
                text=text,
                message_thread_id=message_thread_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reply_parameters=reply_parameters,
                link_preview_options=link_preview_options,
                disable_notification=disable_notification,
            )
        )

    async def edit_message_text(
        self,
        *,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Message | bool:
        result = await self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return Message.model_validate(result) if isinstance(result, dict) else bool(result)

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        return bool(await self.call("deleteMessage", chat_id=chat_id, message_id=message_id))

    async def send_chat_action(
        self, chat_id: int, action: str, *, message_thread_id: int | None = None
    ) -> bool:
        return bool(
            await self.call(
                "sendChatAction",
                chat_id=chat_id,
                action=action,
                message_thread_id=message_thread_id,
            )
        )

    # -- Bot API 10.x surfaces PTB does not wrap ---------------------------
    async def send_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        parse_mode: str | None = None,
        entities: list[dict[str, Any]] | None = None,
        can_stop: bool | None = None,
        keep_on_stop: bool | None = None,
    ) -> bool:
        return bool(
            await self.call(
                "sendMessageDraft",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                draft_id=draft_id,
                text=text,
                parse_mode=parse_mode,
                entities=entities,
                can_stop=can_stop,
                keep_on_stop=keep_on_stop,
            )
        )

    async def send_rich_message(
        self,
        chat_id: int,
        rich_message: dict[str, Any],
        *,
        message_thread_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Message:
        return Message.model_validate(
            await self.call(
                "sendRichMessage",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                rich_message=rich_message,
                reply_markup=reply_markup,
            )
        )

    async def send_rich_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        rich_message: dict[str, Any],
        *,
        message_thread_id: int | None = None,
        can_stop: bool | None = None,
    ) -> bool:
        return bool(
            await self.call(
                "sendRichMessageDraft",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                draft_id=draft_id,
                rich_message=rich_message,
                can_stop=can_stop,
            )
        )

    async def send_checklist(
        self,
        chat_id: int,
        checklist: dict[str, Any],
        *,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> Message:
        return Message.model_validate(
            await self.call(
                "sendChecklist",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                business_connection_id=business_connection_id,
                checklist=checklist,
            )
        )

    async def edit_message_checklist(
        self,
        *,
        chat_id: int,
        message_id: int,
        checklist: dict[str, Any],
        business_connection_id: str | None = None,
    ) -> Message:
        return Message.model_validate(
            await self.call(
                "editMessageChecklist",
                chat_id=chat_id,
                message_id=message_id,
                business_connection_id=business_connection_id,
                checklist=checklist,
            )
        )

    # -- keyboards / callbacks --------------------------------------------
    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
        url: str | None = None,
    ) -> bool:
        return bool(
            await self.call(
                "answerCallbackQuery",
                callback_query_id=callback_query_id,
                text=text,
                show_alert=show_alert,
                url=url,
            )
        )

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Message | bool:
        result = await self.call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            reply_markup=reply_markup,
        )
        return Message.model_validate(result) if isinstance(result, dict) else bool(result)

    async def set_message_reaction(
        self,
        chat_id: int,
        message_id: int,
        reaction: list[dict[str, Any]],
        *,
        is_big: bool = False,
    ) -> bool:
        return bool(
            await self.call(
                "setMessageReaction",
                chat_id=chat_id,
                message_id=message_id,
                reaction=reaction,
                is_big=is_big or None,
            )
        )

    # -- polls -------------------------------------------------------------
    async def send_poll(
        self,
        chat_id: int,
        question: str,
        options: list[str],
        *,
        message_thread_id: int | None = None,
        is_anonymous: bool = False,
        type: str = "regular",
        allows_multiple_answers: bool = False,
        allows_revoting: bool = True,
        correct_option_ids: list[int] | None = None,
        explanation: str | None = None,
        open_period: int | None = None,
        is_closed: bool = False,
        question_parse_mode: str | None = None,
    ) -> Message:
        return Message.model_validate(
            await self.call(
                "sendPoll",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                question=question,
                question_parse_mode=question_parse_mode,
                options=[{"text": opt} for opt in options],
                is_anonymous=is_anonymous,
                type=type,
                allows_multiple_answers=allows_multiple_answers,
                allows_revoting=allows_revoting,
                correct_option_ids=correct_option_ids,
                explanation=explanation,
                open_period=open_period,
                is_closed=is_closed,
            )
        )

    async def stop_poll(self, chat_id: int, message_id: int, reply_markup: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.call("stopPoll", chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)

    # -- topics ------------------------------------------------------------
    async def create_forum_topic(
        self, chat_id: int, name: str, *, icon_custom_emoji_id: str | None = None
    ) -> dict[str, Any]:
        return await self.call(
            "createForumTopic",
            chat_id=chat_id,
            name=name,
            icon_custom_emoji_id=icon_custom_emoji_id,
        )

    async def edit_forum_topic(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> bool:
        return bool(
            await self.call(
                "editForumTopic",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                name=name,
                icon_custom_emoji_id=icon_custom_emoji_id,
            )
        )

    async def close_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        return bool(await self.call("closeForumTopic", chat_id=chat_id, message_thread_id=message_thread_id))

    async def reopen_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        return bool(await self.call("reopenForumTopic", chat_id=chat_id, message_thread_id=message_thread_id))

    async def delete_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        return bool(await self.call("deleteForumTopic", chat_id=chat_id, message_thread_id=message_thread_id))

    async def pin_chat_message(
        self, chat_id: int, message_id: int, *, disable_notification: bool = True
    ) -> bool:
        return bool(
            await self.call(
                "pinChatMessage",
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=disable_notification,
            )
        )

    async def unpin_chat_message(
        self, chat_id: int, *, message_id: int | None = None
    ) -> bool:
        return bool(await self.call("unpinChatMessage", chat_id=chat_id, message_id=message_id))

    # -- files & voice -----------------------------------------------------
    async def get_file(self, file_id: str) -> File:
        return File.model_validate(await self.call("getFile", file_id=file_id))

    async def download_file(self, file_path: str) -> bytes:
        response = await self._client.get(f"/file/{file_path}")
        response.raise_for_status()
        return response.content

    async def send_voice(
        self,
        chat_id: int,
        voice: bytes,
        *,
        message_thread_id: int | None = None,
        caption: str | None = None,
        filename: str = "briefing.ogg",
    ) -> Message:
        files = {"voice": (filename, voice, "audio/ogg")}
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if message_thread_id is not None:
            data["message_thread_id"] = str(message_thread_id)
        if caption:
            data["caption"] = caption
        response = await self._client.post("/sendVoice", data=data, files=files)
        body = response.json()
        if not body.get("ok"):
            raise TelegramError("sendVoice", response.status_code, str(body.get("description")))
        return Message.model_validate(body["result"])

    # -- inline mode -------------------------------------------------------
    async def answer_inline_query(
        self, inline_query_id: str, results: list[dict[str, Any]], *, cache_time: int = 0
    ) -> bool:
        return bool(
            await self.call(
                "answerInlineQuery",
                inline_query_id=inline_query_id,
                results=results,
                cache_time=cache_time,
            )
        )

    async def get_chat(self, chat_id: int) -> Chat:
        return Chat.model_validate(await self.call("getChat", chat_id=chat_id))


def _as_dict(command: BotCommand | dict[str, str]) -> dict[str, str]:
    if isinstance(command, BotCommand):
        return {"command": command.command, "description": command.description}
    return command
