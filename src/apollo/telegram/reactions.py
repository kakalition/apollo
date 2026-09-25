"""Telegram reaction helpers.

Telegram only accepts a fixed set of emoji for ``setMessageReaction``; anything
else fails with ``400 REACTION_INVALID`` (notably ``✅`` is **not** allowed, which
used to make the capture acknowledgement fail on every message).
"""

from __future__ import annotations

from typing import Any

# The emoji Telegram accepts as message reactions (Bot API 10.x).
EMOJI_REACTIONS: frozenset[str] = frozenset(
    {
        "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱",
        "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡",
        "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌭", "💯", "🤣", "⚡", "🍌",
        "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴",
        "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝",
        "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒",
        "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷", "🤷‍♂",
        "🤷‍♀", "😡",
    }
)

DEFAULT_ACK_EMOJI = "👍"


def is_valid_reaction(emoji: str) -> bool:
    return emoji in EMOJI_REACTIONS


def reaction_payload(emoji: str) -> list[dict[str, Any]]:
    return [{"type": "emoji", "emoji": emoji}]
