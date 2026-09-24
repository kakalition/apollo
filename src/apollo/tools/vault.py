"""Markdown vault: path-sandboxed reads/writes plus DB + FTS sync.

The vault is the source of truth for journal/notes. ``Vault.sync`` reconciles the
filesystem into ``journal_entries`` and the ``vault_fts`` index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollo.db import tables as t
from apollo.db.fts import delete_vault_fts, upsert_vault_fts
from apollo.db.repositories import logs
from apollo.domain import models as m
from apollo.support.frontmatter import split_frontmatter


class VaultError(RuntimeError):
    pass


@dataclass(slots=True)
class VaultDoc:
    path: str
    body: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    occurred_at: datetime | None = None
    frontmatter: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    removed: int = 0

    @property
    def changed(self) -> int:
        return self.added + self.updated + self.removed


class Vault:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- path safety -------------------------------------------------------
    def safe_path(self, rel: str) -> Path:
        candidate = (self.root / rel.lstrip("/")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise VaultError(f"path escapes vault root: {rel}")
        return candidate

    def _rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))

    # -- io ----------------------------------------------------------------
    def read(self, rel: str) -> str:
        return self.safe_path(rel).read_text(encoding="utf-8")

    def write(self, rel: str, content: str) -> str:
        path = self.safe_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self._rel(path)

    def delete(self, rel: str) -> None:
        path = self.safe_path(rel)
        if path.exists():
            path.unlink()

    def exists(self, rel: str) -> bool:
        return self.safe_path(rel).exists()

    def list_docs(self, pattern: str = "**/*.md") -> list[Path]:
        return sorted(p for p in self.root.glob(pattern) if p.is_file())

    # -- parsing -----------------------------------------------------------
    def parse(self, rel: str) -> VaultDoc:
        path = self.safe_path(rel)
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(raw)
        title = frontmatter.get("title")
        tags = _coerce_list(frontmatter.get("tags"))
        occurred = _coerce_dt(frontmatter.get("date") or frontmatter.get("occurred_at"))
        if occurred is None:
            occurred = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return VaultDoc(
            path=self._rel(path),
            body=body,
            title=str(title) if title else _first_heading(body),
            tags=[str(tag) for tag in tags],
            occurred_at=occurred,
            frontmatter=frontmatter,
        )

    # -- sync --------------------------------------------------------------
    def sync(self, session: Session) -> SyncStats:
        stats = SyncStats()
        seen: set[str] = set()
        for path in self.list_docs():
            rel = self._rel(path)
            seen.add(rel)
            doc = self.parse(rel)
            entry = m.JournalEntry(
                occurred_at=doc.occurred_at or datetime.now(UTC),
                title=doc.title,
                body_path=rel,
                tags=doc.tags,
            )
            _, changed, created = logs.upsert_journal_entry(
                session, entry, body_hash=logs.content_hash(doc.body)
            )
            if changed:
                _reindex(session, doc)
                if created:
                    stats.added += 1
                else:
                    stats.updated += 1
        # Remove entries whose files are gone.
        for row in session.execute(select(t.JournalEntry)).scalars():
            if row.body_path not in seen:
                delete_vault_fts(session.connection(), body_path=row.body_path)
                session.delete(row)
                stats.removed += 1
        return stats


def _reindex(session: Session, doc: VaultDoc) -> None:
    upsert_vault_fts(
        session.connection(),
        body_path=doc.path,
        title=doc.title,
        body=doc.body,
        tags=doc.tags,
    )


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part.strip().strip("'\"") for part in text.split(",") if part.strip()]


def _coerce_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip() or None
    return None
