"""Telegram reaction emoji validation."""

from __future__ import annotations

from apollo.telegram.reactions import (
    DEFAULT_ACK_EMOJI,
    EMOJI_REACTIONS,
    is_valid_reaction,
    reaction_payload,
)


def test_valid_emojis_include_common_ones() -> None:
    for emoji in ("👍", "👀", "🔥", "🎉", "🙏"):
        assert is_valid_reaction(emoji), emoji


def test_checkmark_is_not_a_valid_reaction() -> None:
    # ✅ is rejected by Telegram with 400 REACTION_INVALID.
    assert not is_valid_reaction("✅")
    assert "✅" not in EMOJI_REACTIONS


def test_default_ack_is_valid() -> None:
    assert is_valid_reaction(DEFAULT_ACK_EMOJI)


def test_reaction_payload_shape() -> None:
    assert reaction_payload("👍") == [{"type": "emoji", "emoji": "👍"}]
