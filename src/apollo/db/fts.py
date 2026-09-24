"""FTS5 lexical index over the markdown vault (``data/vault``).

FTS5 is the lexical recall path; Mem0/Chroma is the semantic path. The virtual
table is created outside Alembic because SQLite virtual tables do not autogenerate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, text

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
    body_path UNINDEXED,
    title,
    body,
    tags,
    tokenize='porter unicode61'
);
"""


def ensure_fts(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(FTS_DDL)


def upsert_vault_fts(
    conn: Connection, *, body_path: str, title: str | None, body: str, tags: list[str]
) -> None:
    conn.execute(text("DELETE FROM vault_fts WHERE body_path = :path"), {"path": body_path})
    conn.execute(
        text(
            "INSERT INTO vault_fts (body_path, title, body, tags) "
            "VALUES (:path, :title, :body, :tags)"
        ),
        {"path": body_path, "title": title or "", "body": body, "tags": " ".join(tags)},
    )


def delete_vault_fts(conn: Connection, *, body_path: str) -> None:
    conn.execute(text("DELETE FROM vault_fts WHERE body_path = :path"), {"path": body_path})


def search_vault(conn: Connection, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Return ranked lexical matches with a highlighted snippet."""
    stmt = text(
        """
        SELECT body_path,
               title,
               snippet(vault_fts, 2, '[', ']', ' … ', 12) AS snippet,
               bm25(vault_fts) AS rank
        FROM vault_fts
        WHERE vault_fts MATCH :q
        ORDER BY rank
        LIMIT :limit
        """
    )
    try:
        rows = conn.execute(stmt, {"q": _match_query(query), "limit": limit}).mappings().all()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _match_query(query: str) -> str:
    """Turn free text into a safe FTS5 OR query of quoted terms."""
    terms = [t for t in query.replace('"', " ").split() if t.strip()]
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in terms)
