"""Model tier resolution for the OpenAI-compatible provider."""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel

from apollo.agents.provider import build_provider
from apollo.config import Settings, TierName


class ModelConfigError(RuntimeError):
    pass


def build_model(settings: Settings, tier: TierName) -> Model:
    base_url = settings.provider.base_url
    api_key = settings.provider.api_key
    if not base_url:
        raise ModelConfigError("APOLLO_PROVIDER__BASE_URL is unset")
    model_name = settings.provider.model_for(tier)
    return _model_cached(base_url, api_key or "", model_name)


def _model_cached(base_url: str, api_key: str, model_name: str) -> Model:
    """Build a fresh model (and AsyncClient) per call.

    The underlying ``httpx.AsyncClient`` is bound to the running event loop, so it
    must not be cached across ``asyncio.run`` invocations (workers run one loop per
    job).
    """
    from apollo.config import ProviderSettings
    from apollo.config import Settings as _Settings

    provider = build_provider(
        _Settings(provider=ProviderSettings(base_url=base_url, api_key=api_key))
    )
    return OpenAIChatModel(model_name, provider=provider)


def model_name_for(settings: Settings, tier: TierName) -> str:
    return settings.provider.model_for(tier)
