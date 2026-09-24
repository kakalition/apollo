"""Pytest fixtures: a temp SQLite database, settings, runtime and a frozen clock."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from apollo.bootstrap import Runtime
from apollo.config import (
    AppSettings,
    AutonomySettings,
    EmbeddingsSettings,
    MemorySettings,
    ProviderSettings,
    SchedulerSettings,
    Settings,
    TelegramSettings,
    VaultSettings,
)
from apollo.db.fts import ensure_fts
from apollo.db.session import Database
from apollo.db.tables import Base
from apollo.tools.clock import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_SKILLS = REPO_ROOT / "skills"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Make the built-in skills visible under the temp root so build_context finds
    # them exactly as it would in a real install (settings.root / "skills").
    if BUILTIN_SKILLS.exists() and not (tmp_path / "skills").exists():
        shutil.copytree(BUILTIN_SKILLS, tmp_path / "skills")
    return Settings(
        root=tmp_path,
        app=AppSettings(
            data_dir=tmp_path / "data",
            vault_dir=tmp_path / "data" / "vault",
            db_path=tmp_path / "data" / "apollo.db",
            timezone="UTC",
            log_json=False,
        ),
        provider=ProviderSettings(
            base_url="http://provider.test/v1",
            api_key="test-key",
            tiers={
                "triage": "test-triage",
                "plan": "test-plan",
                "coach": "test-coach",
                "research": "test-research",
                "memory": "test-memory",
            },
        ),
        embeddings=EmbeddingsSettings(model="test-embed", fallback="none"),
        telegram=TelegramSettings(bot_token=None, allowed_user_ids=[]),
        memory=MemorySettings(enabled=False),
        autonomy=AutonomySettings(
            default_tier="mutate",
            irreversible=["calendar.delete_event", "web.send", "vault.delete", "telegram.send_payment"],
        ),
        scheduler=SchedulerSettings(tick_seconds=5, max_attempts=3),
        vault=VaultSettings(root=tmp_path / "data" / "vault"),
    )


@pytest.fixture
def db(settings: Settings) -> Database:
    settings.ensure_dirs()
    database = Database(settings.db_file)
    Base.metadata.create_all(database.engine)
    ensure_fts(database.engine)
    return database


@pytest.fixture
def runtime(settings: Settings, db: Database) -> Runtime:
    return Runtime(settings=settings, db=db)


@pytest.fixture
def clock() -> FrozenClock:
    # Monday 2026-03-02 09:00 UTC
    return FrozenClock("2026-03-02T09:00:00Z")
