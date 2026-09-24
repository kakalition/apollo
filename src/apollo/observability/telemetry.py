"""Telemetry setup — re-exports logging helpers; OTel wiring lands in M10."""

from __future__ import annotations

from apollo.observability import configure_from_settings, get_logger, setup_logging

__all__ = ["configure_from_settings", "get_logger", "setup_logging"]
