"""Shared markdown frontmatter parsing (used by skills and the vault)."""

from __future__ import annotations

from typing import Any


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` fenced YAML frontmatter from a markdown body."""
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    if len(lines) < 2:
        return {}, raw
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, raw
    front = parse_simple_yaml("\n".join(lines[1:end]))
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return front, body


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML subset: scalar ``k: v``, inline ``[a, b]``, and ``- item`` lists."""
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if stripped.startswith("- ") and current_key is not None:
            existing = data.get(current_key)
            if not isinstance(existing, list):
                existing = []
                data[current_key] = existing
            existing.append(_scalar(stripped[2:].strip()))
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "":
                data.setdefault(key, [])
            else:
                data[key] = _scalar(value)
    return data


def _scalar(value: str) -> Any:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1]
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    return _strip_quotes(text)


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text
