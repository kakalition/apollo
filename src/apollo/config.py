"""Configuration loading: ``apollo.toml`` (non-secret) + ``.env`` (secrets).

Secrets never live in ``apollo.toml``. Environment variables use the ``APOLLO_``
prefix and ``__`` as the nested delimiter, e.g. ``APOLLO_PROVIDER__API_KEY``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_TOML = Path("apollo.toml")
DEFAULT_ENV = Path(".env")

TierName = Literal["triage", "plan", "coach", "research", "memory"]
AutonomyTier = Literal["read", "mutate", "irreversible"]


class AppSettings(BaseModel):
    name: str = "Apollo"
    timezone: str = "UTC"
    data_dir: Path = Path("data")
    vault_dir: Path = Path("data/vault")
    db_path: Path = Path("data/apollo.db")
    log_level: str = "INFO"
    log_json: bool = True
    otel_enabled: bool = False
    logfire_token: str | None = None


class ProviderSettings(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    # Hard ceiling on a single agent run; a stuck model call fails fast instead of
    # occupying the worker forever.
    run_timeout_seconds: int = 120
    # When set, this single model id is used for every tier (simple proxies).
    chat_model_id: str | None = None
    # Embeddings model id served by the same endpoint, if any.
    embedding_model_id: str | None = None
    tiers: dict[str, str] = Field(default_factory=dict)

    def model_for(self, tier: TierName) -> str:
        if self.chat_model_id:
            return self.chat_model_id
        try:
            return self.tiers[tier]
        except KeyError as exc:  # pragma: no cover - config error path
            raise KeyError(f"no model configured for tier {tier!r}") from exc

    @property
    def embedding_model(self) -> str | None:
        return self.embedding_model_id


class EmbeddingsSettings(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str = "text-embedding-3-small"
    fallback: Literal["provider", "local", "none"] = "local"
    local_model: str = "BAAI/bge-small-en-v1.5"


class TelegramSettings(BaseModel):
    bot_token: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
    topic_routing: bool = True
    # Emoji the bot reacts with to acknowledge a capture. Must be a valid Telegram
    # reaction emoji; set to "" to disable the acknowledgement.
    ack_reaction: str = "👍"
    quiet_hours: dict[str, str] = Field(default_factory=lambda: {"start": "22:00", "end": "07:00"})
    rate_limit_per_second: float = 1.0
    poll_timeout: int = 30


class MemorySettings(BaseModel):
    enabled: bool = True
    chroma_url: str = "http://127.0.0.1:8000"
    collection: str = "apollo"
    top_k: int = 6


class AutonomySettings(BaseModel):
    default_tier: AutonomyTier = "mutate"
    irreversible: list[str] = Field(default_factory=list)

    def tier_for(self, action: str) -> AutonomyTier:
        if action in self.irreversible:
            return "irreversible"
        return self.default_tier


class SchedulerSettings(BaseModel):
    tick_seconds: int = 60
    max_attempts: int = 5


class VaultSettings(BaseModel):
    root: Path = Path("data/vault")
    sync_interval_seconds: int = 300


class MCPServerSettings(BaseModel):
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    url: str | None = None
    allowlist: list[str] = Field(default_factory=list)
    namespace: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class MCPSettings(BaseModel):
    servers: dict[str, MCPServerSettings] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APOLLO_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file=str(DEFAULT_TOML),
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    autonomy: AutonomySettings = Field(default_factory=AutonomySettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)

    # Directory the config file was loaded from; used to resolve relative paths.
    root: Path = Field(default=Path("."), exclude=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: explicit init args > real env > .env > apollo.toml > secret files.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # -- path helpers ------------------------------------------------------
    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else (self.root / path).resolve()

    @property
    def data_path(self) -> Path:
        return self.resolve(self.app.data_dir)

    @property
    def db_file(self) -> Path:
        return self.resolve(self.app.db_path)

    @property
    def vault_path(self) -> Path:
        return self.resolve(self.app.vault_dir)

    def ensure_dirs(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.vault_path.mkdir(parents=True, exist_ok=True)

    # -- convenience -------------------------------------------------------
    def model_for(self, tier: TierName) -> str:
        return self.provider.model_for(tier)

    def embedding_model_id(self) -> str:
        """Embeddings model, preferring the provider-level id when configured."""
        return self.provider.embedding_model or self.embeddings.model

    def redacted(self) -> dict[str, Any]:
        """Config safe to log: secrets replaced by presence flags."""
        data = self.model_dump(mode="json", exclude={"root"})
        provider = data.get("provider", {})
        provider["api_key"] = _flag(self.provider.api_key)
        data["provider"] = provider
        telegram = data.get("telegram", {})
        telegram["bot_token"] = _flag(self.telegram.bot_token)
        data["telegram"] = telegram
        return data


def _flag(secret: str | None) -> str:
    return "<set>" if secret else "<unset>"


def load_settings(
    toml_path: Path | str | None = None,
    env_path: Path | str | None = None,
) -> Settings:
    """Load settings from an explicit toml/env pair, falling back to defaults."""
    toml = Path(toml_path) if toml_path is not None else DEFAULT_TOML
    env = Path(env_path) if env_path is not None else DEFAULT_ENV
    root = toml.resolve().parent if toml.exists() else Path.cwd()

    class _Settings(Settings):
        model_config = SettingsConfigDict(
            **{**Settings.model_config, "toml_file": str(toml), "env_file": str(env)}
        )

    return _Settings(root=root)
