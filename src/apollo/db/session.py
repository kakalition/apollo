"""Engine/session management with the SQLite multi-process discipline.

Every write transaction is opened with ``BEGIN IMMEDIATE`` (via the SQLAlchemy
``begin`` event) so two processes never both take a write lock optimistically.
``busy_timeout`` makes contention wait rather than fail.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

BUSY_TIMEOUT_MS = 5000


def build_engine(db_path: Path | str, *, echo: bool = False) -> Engine:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000},
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
        # Let SQLAlchemy drive transactions explicitly so BEGIN IMMEDIATE applies.
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class Database:
    """Owns an engine and hands out sessions bound to it."""

    def __init__(self, db_path: Path | str, *, echo: bool = False) -> None:
        self.path = Path(db_path)
        self.engine = build_engine(self.path, echo=echo)
        self._sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Read session (no forced write lock)."""
        session = self._sessionmaker()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def write(self) -> Iterator[Session]:
        """Write session: one short ``BEGIN IMMEDIATE`` transaction, commit on exit."""
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = maker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def acquire_advisory_lock(
    session: Session, name: str, owner: str | None = None
) -> bool:
    """Take a named advisory lock (single-dispatcher invariant).

    Returns True if this owner holds it. A stale lock whose owner pid is gone is
    reclaimed. Must be called inside a write transaction.
    """
    owner = owner or str(os.getpid())
    row = session.execute(
        text("SELECT value FROM settings WHERE key = :key"), {"key": f"lock:{name}"}
    ).fetchone()
    if row is not None:
        value = row[0]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = {}
        existing = value.get("owner") if isinstance(value, dict) else None
        if existing == owner:
            return True
        if existing is not None and _pid_alive(str(existing)):
            return False  # someone else holds it
    session.execute(
        text(
            "INSERT INTO settings (key, value, updated_at) VALUES (:key, :value, :now) "
            "ON CONFLICT(key) DO UPDATE SET value = :value, updated_at = :now"
        ),
        {
            "key": f"lock:{name}",
            "value": _json({"owner": owner, "acquired_at": _now_iso()}),
            "now": _now_iso(),
        },
    )
    return True


def release_advisory_lock(session: Session, name: str, owner: str | None = None) -> None:
    owner = owner or str(os.getpid())
    session.execute(
        text("DELETE FROM settings WHERE key = :key AND json_extract(value, '$.owner') = :owner"),
        {"key": f"lock:{name}", "owner": owner},
    )


def _pid_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
