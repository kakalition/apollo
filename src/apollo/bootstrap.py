"""Bootstrap helper: one call to get settings, logging and a Database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apollo.config import Settings, load_settings
from apollo.db.session import Database
from apollo.observability import configure_from_settings


@dataclass(slots=True)
class Runtime:
    settings: Settings
    db: Database

    def close(self) -> None:
        self.db.dispose()


def bootstrap(
    *,
    toml_path: Path | str | None = None,
    env_path: Path | str | None = None,
    require_db: bool = True,
    echo: bool = False,
) -> Runtime:
    settings = load_settings(toml_path, env_path)
    configure_from_settings(settings)
    from apollo.observability.tracing import setup_tracing

    setup_tracing(settings)
    settings.ensure_dirs()
    db = Database(settings.db_file, echo=echo)
    if require_db and not settings.db_file.exists():  # pragma: no cover - guarded by CLI
        raise RuntimeError("database not initialised — run `apollo init-db`")
    return Runtime(settings=settings, db=db)
