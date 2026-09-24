"""Programmatic Alembic runner used by ``apollo init-db`` and ``apollo upgrade``."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from apollo.config import Settings
from apollo.db.fts import ensure_fts
from apollo.db.session import build_engine


def alembic_config(settings: Settings) -> Config:
    root = settings.root
    ini = root / "alembic.ini"
    cfg = Config(str(ini) if ini.exists() else None)
    cfg.set_main_option("script_location", str(root / "src/apollo/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_file}")
    cfg.set_main_option("apollo.root", str(root))
    return cfg


def upgrade(settings: Settings, revision: str = "head") -> None:
    command.upgrade(alembic_config(settings), revision)


def downgrade(settings: Settings, revision: str = "-1") -> None:
    command.downgrade(alembic_config(settings), revision)


def current(settings: Settings) -> None:
    command.current(alembic_config(settings))


def ensure_schema(settings: Settings) -> None:
    """Apply migrations and create the FTS5 virtual table."""
    settings.ensure_dirs()
    upgrade(settings, "head")
    engine = build_engine(settings.db_file)
    try:
        ensure_fts(engine)
    finally:
        engine.dispose()


def schema_path(settings: Settings) -> Path:
    return settings.root / "src/apollo/db/migrations"
