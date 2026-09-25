"""Markdown → Telegram HTML conversion (escaping, formatting, safety)."""

from __future__ import annotations

from apollo.telegram.markdown import to_telegram_html


def test_plain_text_escapes_html() -> None:
    assert to_telegram_html("AT&T <script>alert(1)</script>") == (
        "AT&amp;T &lt;script&gt;alert(1)&lt;/script&gt;"
    )


def test_agent_html_cannot_inject_tags() -> None:
    assert to_telegram_html("<b>not bold</b>") == "&lt;b&gt;not bold&lt;/b&gt;"


def test_bold_italic_strike_code() -> None:
    assert to_telegram_html("**bold** and *italic* and ~~gone~~") == (
        "<b>bold</b> and <i>italic</i> and <s>gone</s>"
    )
    assert to_telegram_html("use `code` here") == "use <code>code</code> here"


def test_link_and_autolink() -> None:
    assert to_telegram_html("[docs](https://example.com/a?b=1&c=2)") == (
        '<a href="https://example.com/a?b=1&amp;c=2">docs</a>'
    )
    assert to_telegram_html("<https://example.com>") == (
        '<a href="https://example.com">https://example.com</a>'
    )


def test_snake_case_is_not_italicised() -> None:
    assert to_telegram_html("no_checkin_days(2) and metric_below_target") == (
        "no_checkin_days(2) and metric_below_target"
    )


def test_code_fence_preserves_and_escapes() -> None:
    md = "before\n```python\nx = a < b and c > d\n```\nafter"
    html = to_telegram_html(md)
    assert '<pre><code class="language-python">' in html
    assert "x = a &lt; b and c &gt; d" in html
    assert html.startswith("before\n")
    assert html.endswith("\nafter")


def test_heading_list_and_blockquote() -> None:
    html = to_telegram_html("# Title\n- one\n- two\n> quoted")
    assert "<b>Title</b>" in html
    assert "• one" in html and "• two" in html
    assert "<blockquote>quoted</blockquote>" in html


def test_ordered_list_and_hr() -> None:
    html = to_telegram_html("1. first\n2. second\n---")
    assert "1. first" in html and "2. second" in html
    assert "────────" in html


def test_table_renders_as_monospace_block() -> None:
    md = "| Metric | Value |\n| --- | --- |\n| Sleep | 6.5 |"
    html = to_telegram_html(md)
    assert html.startswith("<pre>")
    assert "Metric" in html and "Sleep" in html and "6.5" in html


def test_empty_input() -> None:
    assert to_telegram_html("") == ""
