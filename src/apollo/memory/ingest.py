"""Ingestion sources for memory reindex/backfill."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from apollo.db.repositories import logs


def iter_ingestable(session: Session) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(text, metadata)`` from journal entries, check-ins and reviews."""
    for entry in logs.list_journal(session, limit=500):
        if entry.body_path:
            yield (
                f"Journal: {entry.title or entry.body_path}",
                {"source": "journal", "ref": entry.body_path, "occurred_at": _iso(entry.occurred_at)},
            )
    for checkin in logs.list_checkins(session, limit=500):
        text = checkin.note or checkin.value_text
        if text:
            yield (
                text,
                {"source": "checkin", "kind": checkin.kind, "ref": checkin.ref_id},
            )
    for review in logs.list_reviews(session):
        if review.summary or review.insights:
            yield (
                f"Review {review.cadence}: {review.summary or ''} {review.insights or ''}".strip(),
                {"source": "review", "ref": review.id},
            )


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
