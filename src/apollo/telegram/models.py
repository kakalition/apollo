"""Pydantic models for the Telegram Bot API (10.3) objects Apollo uses.

Deliberately permissive (``extra="allow"``) so new/changed fields never crash the
bot; strictness belongs in the renderer, not the transport.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TGBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class User(TGBase):
    id: int
    is_bot: bool = False
    first_name: str | None = None
    username: str | None = None
    # These live on the *bot* User returned by getMe, not on Chat/ChatFullInfo.
    has_topics_enabled: bool | None = None
    allows_users_to_create_topics: bool | None = None
    can_join_groups: bool | None = None
    can_read_all_group_messages: bool | None = None
    supports_inline_queries: bool | None = None


class Chat(TGBase):
    id: int
    type: str
    title: str | None = None
    username: str | None = None
    is_forum: bool | None = None


class Voice(TGBase):
    file_id: str
    duration: int = 0
    mime_type: str | None = None
    file_size: int | None = None


class PollOption(TGBase):
    text: str
    voter_count: int = 0


class Poll(TGBase):
    id: str
    question: str
    options: list[PollOption] = Field(default_factory=list)
    is_anonymous: bool = True
    type: str = "regular"
    allows_multiple_answers: bool = False


class Message(TGBase):
    message_id: int
    chat: Chat
    from_user: User | None = Field(default=None, alias="from")
    date: int | None = None
    text: str | None = None
    caption: str | None = None
    message_thread_id: int | None = None
    voice: Voice | None = None
    poll: Poll | None = None
    reply_to_message: Message | None = None
    is_topic_message: bool | None = None
    business_connection_id: str | None = None


class CallbackQuery(TGBase):
    id: str
    from_user: User = Field(alias="from")
    chat_instance: str | None = None
    data: str | None = None
    message: Message | None = None


class PollAnswer(TGBase):
    poll_id: str
    voter_chat: Chat | None = None
    user: User | None = None
    option_ids: list[int] = Field(default_factory=list)


class MessageGenerationStopped(TGBase):
    chat: Chat
    message_thread_id: int | None = None
    draft_id: int


class InlineQuery(TGBase):
    id: str
    from_user: User = Field(alias="from")
    query: str = ""
    offset: str = ""


class Update(TGBase):
    update_id: int
    message: Message | None = None
    edited_message: Message | None = None
    callback_query: CallbackQuery | None = None
    poll_answer: PollAnswer | None = None
    inline_query: InlineQuery | None = None
    stopped_message_generation: MessageGenerationStopped | None = None


class File(TGBase):
    file_id: str
    file_unique_id: str | None = None
    file_path: str | None = None
    file_size: int | None = None


class BotCommand(TGBase):
    command: str
    description: str
