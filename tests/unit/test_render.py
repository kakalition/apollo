"""Rich rendering, chunking and keyboards."""

from __future__ import annotations

from apollo.telegram.keyboards import (
    approval_keyboard,
    decode,
    encode,
    inline_keyboard,
    task_keyboard,
)
from apollo.telegram.render import (
    MAX_MESSAGE_LENGTH,
    Button,
    RichDocument,
    chunk,
    escape,
    render_briefing,
    render_review,
    spoiler,
    time_tag,
)


def test_escape_limits_named_entities() -> None:
    assert escape("<b>&\"'") == "&lt;b&gt;&amp;&quot;&#x27;"


def test_chunk_respects_limit() -> None:
    text = "\n\n".join(["paragraph " * 50] * 20)
    parts = chunk(text)
    assert all(len(p) <= MAX_MESSAGE_LENGTH for p in parts)
    assert len(parts) > 1
    assert parts[0].startswith("paragraph")
    assert "".join(parts).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_rich_document_renders_blocks_and_html() -> None:
    doc = RichDocument(title="Hi")
    doc.heading("Focus").bullet_list(["a", "b"]).table(["x"], [["1"]])
    blocks = doc.to_blocks()
    assert blocks["blocks"][0] == {"type": "title", "text": "Hi"}
    assert "Focus" in doc.to_html()


def test_briefing_and_review_documents() -> None:
    briefing = render_briefing(
        {
            "focus": ["Ship the draft"],
            "habits": [{"name": "Journal", "current_streak": 4}],
            "metrics": [{"name": "Sleep", "latest": 6.5, "target": 7.5}],
            "watch_out": ["One task overdue"],
            "remember": "You ship best before noon.",
        }
    )
    assert "Ship the draft" in briefing.to_html()
    review = render_review({"cadence": "weekly", "wins": ["Shipped"], "adjustments": ["Reduce cadence"]})
    assert "Weekly review" in review.to_html()


def test_time_tag_and_spoiler() -> None:
    assert time_tag(1_800_000_000, "R").startswith('<tg-time unix="1800000000"')
    assert spoiler("secret").startswith("<tg-spoiler>")


def test_callback_encode_decode_roundtrip() -> None:
    data = encode("done", "task", 42)
    assert decode(data) == ("done", "task", "42")
    assert decode("weird") == ("weird", "-", "-")


def test_approval_keyboard_disabled_after_decision() -> None:
    pending = approval_keyboard(7)
    assert all(not btn.get("disabled") for btn in pending["inline_keyboard"][0])
    decided = approval_keyboard(7, decided="approved")
    assert all(btn.get("disabled") for btn in decided["inline_keyboard"][0])


def test_copy_text_button_and_reply_keyboard() -> None:
    markup = task_keyboard(3)
    flat = [btn for row in markup["inline_keyboard"] for btn in row]
    assert any(btn.get("copy_text", {}).get("text") == "task #3" for btn in flat)
    from apollo.telegram.keyboards import today_reply_keyboard

    reply = today_reply_keyboard()
    assert reply["is_persistent"] is True and reply["one_time_keyboard"] is False


def test_inline_keyboard_shape() -> None:
    markup = inline_keyboard([[{"text": "a", "callback_data": "x:-:-"}]])
    assert markup == {"inline_keyboard": [[{"text": "a", "callback_data": "x:-:-"}]]}


def test_document_buttons_row() -> None:
    doc = RichDocument()
    doc.buttons_row([Button("Yes", callback_data="approve:action:1")])
    assert doc.to_blocks()["blocks"][0]["type"] == "buttons"
