"""Convert LLM Markdown output into Telegram-safe rich HTML.

Agents emit Markdown, which Telegram does not render. Sending it verbatim with
``parse_mode="HTML"`` shows ``**bold**`` literally and — worse — any ``<``, ``>``
or ``&`` in the text makes Telegram reject the message ("can't parse entities").

This module escapes first, then applies a conservative Markdown subset, so agent
output can never inject HTML and always parses. Supported: fenced code blocks,
inline code, bold, italic, strikethrough, links, autolinks, headings (as bold),
blockquotes, bullet/ordered lists, horizontal rules and GFM-style tables (as
monospace blocks).
"""

from __future__ import annotations

import re
from html import escape

_FENCE = re.compile(r"^\s*```(.*)$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}(?:(\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_ULIST = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OLIST = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_CELL = re.compile(r"^:?-{2,}:?$")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_AUTOLINK = re.compile(r"&lt;(https?://[^\s&<>]+)&gt;")
_BOLD_STAR = re.compile(r"\*\*([^*\n]+)\*\*")
_BOLD_UNDER = re.compile(r"__([^_\n]+)__")
_STRIKE = re.compile(r"~~([^~\n]+)~~")
_ITALIC_STAR = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_ITALIC_UNDER = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")

_PLACEHOLDER = "\x00ph{}ph\x00"


def to_telegram_html(text: str) -> str:
    """Render a Markdown string as Telegram HTML with safe escaping."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            language = fence.group(1).strip()
            i += 1
            body: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # consume the closing fence (tolerate a missing one)
            code = escape("\n".join(body))
            if language:
                out.append(f'<pre><code class="language-{escape(language)}">{code}</code></pre>')
            else:
                out.append(f"<pre>{code}</pre>")
            continue

        if _HR.match(line):
            out.append("────────")
            i += 1
            continue

        if _QUOTE.match(line):
            quoted: list[str] = []
            while i < len(lines) and (match := _QUOTE.match(lines[i])):
                quoted.append(_inline(match.group(1)))
                i += 1
            out.append(f"<blockquote>{chr(10).join(quoted)}</blockquote>")
            continue

        if _TABLE_ROW.match(line):
            rows: list[str] = []
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                rows.append(lines[i])
                i += 1
            table = _render_table(rows)
            if table:
                out.append(table)
            continue

        heading = _HEADING.match(line)
        if heading:
            out.append(f"<b>{_inline(heading.group(2))}</b>")
            i += 1
            continue

        bullet = _ULIST.match(line)
        if bullet:
            indent = "  " * (len(bullet.group(1)) // 2)
            out.append(f"{indent}• {_inline(bullet.group(2))}")
            i += 1
            continue

        ordered = _OLIST.match(line)
        if ordered:
            indent = "  " * (len(ordered.group(1)) // 2)
            out.append(f"{indent}{ordered.group(2)}. {_inline(ordered.group(3))}")
            i += 1
            continue

        out.append(_inline(line))
        i += 1
    return "\n".join(out)


def _inline(text: str) -> str:
    code_spans: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        code_spans.append(match.group(1))
        return _PLACEHOLDER.format(len(code_spans) - 1)

    stashed = _INLINE_CODE.sub(_stash, text)
    escaped = escape(stashed)

    escaped = _LINK.sub(
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped
    )
    escaped = _AUTOLINK.sub(
        lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', escaped
    )
    escaped = _BOLD_STAR.sub(r"<b>\1</b>", escaped)
    escaped = _BOLD_UNDER.sub(r"<b>\1</b>", escaped)
    escaped = _STRIKE.sub(r"<s>\1</s>", escaped)
    escaped = _ITALIC_STAR.sub(r"<i>\1</i>", escaped)
    escaped = _ITALIC_UNDER.sub(r"<i>\1</i>", escaped)

    for index, content in enumerate(code_spans):
        escaped = escaped.replace(_PLACEHOLDER.format(index), f"<code>{escape(content)}</code>")
    return escaped


def _render_table(rows: list[str]) -> str:
    parsed: list[list[str]] = []
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if cells and all(not cell or _TABLE_SEP_CELL.match(cell) for cell in cells):
            continue  # header separator row
        parsed.append(cells)
    if not parsed:
        return ""
    width = max(len(row) for row in parsed)
    lines = []
    for row in parsed:
        padded = row + [""] * (width - len(row))
        lines.append("  ".join(padded).rstrip())
    return f"<pre>{escape(chr(10).join(lines))}</pre>"
