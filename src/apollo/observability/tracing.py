"""OpenTelemetry / Logfire tracing (opt-in).

Pydantic AI emits spans through OTel automatically once instrumentation is active.
Apollo keeps this optional: with ``otel_enabled`` off (the default) nothing is
installed and no network calls are made.
"""

from __future__ import annotations

from typing import Any

from apollo.observability import get_logger

log = get_logger("apollo.tracing")

_configured = False


def setup_tracing(settings: Any) -> bool:
    """Install tracing if enabled and the relevant packages are present."""
    global _configured
    if _configured:
        return True
    if not getattr(settings.app, "otel_enabled", False):
        return False

    token = getattr(settings.app, "logfire_token", None)
    try:
        import logfire  # type: ignore[import-not-found]

        if token:
            logfire.configure(token=token)
        else:
            logfire.configure(send_to_logfire=False)
        logfire.instrument_pydantic_ai()
        _configured = True
        log.info("tracing.logfire_enabled", send_to_logfire=bool(token))
        return True
    except ImportError:
        pass

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _configured = True
        log.info("tracing.otel_console_enabled")
        return True
    except ImportError:
        log.warning(
            "tracing.unavailable",
            detail="install `logfire` or the opentelemetry-sdk to enable tracing",
        )
        return False
