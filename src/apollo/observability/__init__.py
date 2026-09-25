"""Observability: structured logging and (optionally) OTel tracing.

Logging is JSONL to ``data/logs/apollo.jsonl`` plus a human console renderer.
Secrets are never passed to loggers; callers pass ``settings.redacted()`` for dumps.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

_configured = False


def setup_logging(
    *,
    level: str = "INFO",
    json_logs: bool = True,
    log_dir: Path | None = None,
    force: bool = False,
) -> structlog.stdlib.BoundLogger:
    """Configure structlog once and return a bound logger."""
    global _configured
    if _configured and not force:
        return structlog.get_logger("apollo")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "apollo.jsonl")
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=handlers,
        format="%(message)s",
    )
    # Third-party HTTP clients log every request/response at INFO; keep our logs
    # readable by only surfacing their warnings and errors.
    for noisy in ("httpx", "httpcore", "openai", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True
    return structlog.get_logger("apollo")


def configure_from_settings(settings: Any) -> structlog.stdlib.BoundLogger:
    """Configure logging from a :class:`apollo.config.Settings` instance."""
    log_dir = settings.data_path / "logs"
    return setup_logging(
        level=settings.app.log_level,
        json_logs=settings.app.log_json,
        log_dir=log_dir,
    )


def get_logger(name: str = "apollo") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
