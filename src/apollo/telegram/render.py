"""Rich-message rendering with an always-available rich-HTML fallback.

Bot API 10.x has two structured paths: ``InputRichMessage`` blocks and rich HTML
with ``parse_mode``. Apollo renders both from one semantic document so it degrades
cleanly if rich blocks are unavailable (``apollo doctor`` probes this).

Formatting notes (verified against the Bot API docs):
- No ``tg-date`` tag exists; dates use ``<tg-time unix format>`` (entity ``date_time``).
- Supported tags: b/strong, i/em, u/ins, s/strike/del, tg-spoiler, a, tg-emoji,
  tg-time, code, pre, pre-code, blockquote, blockquote expandable.
- Named entities are limited to &lt; &gt; &amp; &quot;.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape as _html_escape
from typing import Any

MAX_MESSAGE_LENGTH = 4096


def escape(text: str) -> str:
    return _html_escape(text, quote=True)


def bold(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def italic(text: str) -> str:
    return f"<i>{escape(text)}</i>"


def code(text: str) -> str:
    return f"<code>{escape(text)}</code>"


def pre(text: str, language: str | None = None) -> str:
    if language:
        return f'<pre><code class="language-{escape(language)}">{escape(text)}</code></pre>'
    return f"<pre>{escape(text)}</pre>"


def spoiler(text: str) -> str:
    return f"<tg-spoiler>{escape(text)}</tg-spoiler>"


def blockquote(text: str, *, expandable: bool = True) -> str:
    tag = "blockquote expandable" if expandable else "blockquote"
    return f"<{tag}>{escape(text)}</{tag}>"


def emoji(emoji_char: str, custom_emoji_id: str) -> str:
    return f'<tg-emoji emoji-id="{escape(custom_emoji_id)}">{escape(emoji_char)}</tg-emoji>'


def time_tag(unix: int, fmt: str = "R") -> str:
    return f'<tg-time unix="{int(unix)}" format="{escape(fmt)}"></tg-time>'


@dataclass(slots=True)
class Button:
    text: str
    callback_data: str | None = None
    url: str | None = None
    copy_text: str | None = None
    disabled: bool = False


@dataclass(slots=True)
class RichDocument:
    """A semantic document rendered to rich blocks or rich HTML."""

    title: str | None = None
    _html: list[str] = field(default_factory=list)
    _blocks: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[list[Button]] = field(default_factory=list)

    def heading(self, text: str) -> RichDocument:
        self._html.append(bold(text))
        self._blocks.append({"type": "section_heading", "text": text})
        return self

    def paragraph(self, text: str) -> RichDocument:
        self._html.append(escape(text))
        self._blocks.append({"type": "paragraph", "text": text})
        return self

    def bullet_list(self, items: list[str]) -> RichDocument:
        if not items:
            return self
        self._html.extend(f"• {escape(item)}" for item in items)
        self._blocks.append({"type": "list", "items": list(items)})
        return self

    def table(self, headers: list[str], rows: list[list[str]]) -> RichDocument:
        self._blocks.append({"type": "table", "headers": headers, "rows": rows})
        lines = [" | ".join(escape(h) for h in headers)]
        lines.extend(" | ".join(escape(str(c)) for c in row) for row in rows)
        self._html.append(pre("\n".join(lines)))
        return self

    def details(self, summary: str, body: str) -> RichDocument:
        self._blocks.append({"type": "details", "summary": summary, "text": body})
        self._html.append(bold(summary))
        self._html.append(blockquote(body))
        return self

    def quote(self, text: str) -> RichDocument:
        self._html.append(blockquote(text))
        self._blocks.append({"type": "expandable_block_quotation", "text": text})
        return self

    def buttons_row(self, buttons: list[Button]) -> RichDocument:
        self.buttons.append(buttons)
        self._blocks.append(
            {
                "type": "buttons",
                "buttons": [
                    {"text": b.text, "callback_data": b.callback_data, "url": b.url}
                    for b in buttons
                ],
            }
        )
        return self

    def footer(self, text: str) -> RichDocument:
        self._html.append(f"<i>{escape(text)}</i>")
        self._blocks.append({"type": "footer", "text": text})
        return self

    # -- renderers ---------------------------------------------------------
    def to_html(self) -> str:
        body = "\n\n".join(part for part in self._html if part)
        if self.title:
            body = f"{bold(self.title)}\n\n{body}"
        return body

    def to_blocks(self) -> dict[str, Any]:
        blocks = list(self._blocks)
        if self.title:
            blocks.insert(0, {"type": "title", "text": self.title})
        return {"blocks": blocks}


# ---------------------------------------------------------------------------
# Domain-specific documents
# ---------------------------------------------------------------------------
def render_briefing(data: dict[str, Any]) -> RichDocument:
    doc = RichDocument(title="Good morning")
    focus = data.get("focus") or []
    doc.heading("Focus")
    doc.bullet_list([str(item) for item in focus] or ["Nothing scheduled — pick one thing."])
    habits = data.get("habits") or []
    if habits:
        doc.heading("Practices & habits")
        doc.bullet_list(
            [f"{h.get('name')} — streak {h.get('current_streak', 0)}" for h in habits]
        )
    metrics = data.get("metrics") or []
    if metrics:
        doc.heading("Metrics")
        doc.table(
            ["Metric", "Latest", "Target"],
            [[str(m.get("name")), str(m.get("latest")), str(m.get("target"))] for m in metrics],
        )
    watch = data.get("watch_out") or []
    if watch:
        doc.heading("Watch out")
        doc.bullet_list([str(item) for item in watch])
    if data.get("remember"):
        doc.details("Why this matters", str(data["remember"]))
    doc.buttons_row(
        [
            Button("✅ Done", callback_data="done:focus:0"),
            Button("🕐 Snooze 1h", callback_data="snooze:focus:1h"),
            Button("⏭ Not today", callback_data="skip:focus:today"),
        ]
    )
    return doc


def render_review(data: dict[str, Any]) -> RichDocument:
    doc = RichDocument(title=f"{str(data.get('cadence', 'Weekly')).title()} review")
    if data.get("scorecard"):
        doc.heading("Scorecard")
        doc.table(
            ["Practice", "Planned", "Actual", "Trend"],
            [[str(c) for c in row] for row in data["scorecard"]],
        )
    if data.get("metrics"):
        doc.heading("Metrics")
        doc.table(
            ["Metric", "Target", "Average"],
            [[str(c) for c in row] for row in data["metrics"]],
        )
    if data.get("wins"):
        doc.heading("Wins")
        doc.bullet_list([str(w) for w in data["wins"]])
    if data.get("drift"):
        doc.heading("Drift")
        doc.quote(str(data["drift"]))
    if data.get("adjustments"):
        doc.heading("Adjustments")
        doc.bullet_list([str(a) for a in data["adjustments"]])
    if data.get("next_week"):
        doc.footer(str(data["next_week"]))
    return doc


def render_goal_plan(data: dict[str, Any]) -> RichDocument:
    doc = RichDocument(title=f"Plan: {data.get('title', 'goal')}")
    if data.get("outcome"):
        doc.paragraph(str(data["outcome"]))
    if data.get("practice"):
        doc.heading("Practice")
        doc.bullet_list([str(data["practice"])])
    if data.get("milestones"):
        doc.heading("Milestones")
        doc.table(["Milestone", "Done when"], [[str(m[0]), str(m[1])] for m in data["milestones"]])
    if data.get("first_tasks"):
        doc.heading("First tasks")
        doc.bullet_list([str(t) for t in data["first_tasks"]])
    doc.buttons_row(
        [
            Button("📋 Copy plan", copy_text=data.get("title", "plan")),
            Button("🎯 Open goal", callback_data=f"goal:view:{data.get('goal_id', 0)}"),
        ]
    )
    return doc


def render_metrics_table(metrics: list[dict[str, Any]]) -> RichDocument:
    doc = RichDocument(title="Metrics")
    doc.table(
        ["Metric", "Latest", "Target", "Direction"],
        [
            [
                str(m.get("name")),
                str(m.get("latest", "—")),
                str(m.get("target", "—")),
                str(m.get("direction", "")),
            ]
            for m in metrics
        ],
    )
    return doc


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into Telegram-sized chunks, preferring paragraph boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
