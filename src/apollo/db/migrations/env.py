"""Alembic environment — resolves the SQLite path from Apollo settings."""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from apollo.config import load_settings
from apollo.db.tables import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_apollo_root = config.get_main_option("apollo.root", None)
if _apollo_root:
    _root = Path(_apollo_root)
    settings = load_settings(_root / "apollo.toml", _root / ".env")
else:
    settings = load_settings()
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_file}")
settings.data_path.mkdir(parents=True, exist_ok=True)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
