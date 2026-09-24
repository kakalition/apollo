# pyright: reportCallIssue=false
"""Config model resolution and the OpenAI response normalisation adapter."""

from __future__ import annotations

import json

import httpx

from apollo.agents.models import build_model, model_name_for
from apollo.agents.provider import _is_str_map, _normalize_json, _should_normalize
from apollo.config import EmbeddingsSettings, ProviderSettings, Settings


def test_chat_model_id_overrides_all_tiers() -> None:
    provider = ProviderSettings(chat_model_id="deepseek/deepseek-v4-flash-0731", tiers={"plan": "old"})
    assert provider.model_for("triage") == "deepseek/deepseek-v4-flash-0731"
    assert provider.model_for("plan") == "deepseek/deepseek-v4-flash-0731"


def test_tiers_used_when_no_chat_model_id() -> None:
    provider = ProviderSettings(tiers={"triage": "cheap", "plan": "strong"})
    assert provider.model_for("triage") == "cheap"
    assert provider.model_for("plan") == "strong"


def test_embedding_model_prefers_provider_id() -> None:
    settings = Settings(
        _env_file=None,
        provider=ProviderSettings(embedding_model_id="prov-embed"),
        embeddings=EmbeddingsSettings(model="fallback-embed"),
    )
    assert settings.embedding_model_id() == "prov-embed"
    settings2 = Settings(_env_file=None, embeddings=EmbeddingsSettings(model="fallback-embed"))
    assert settings2.embedding_model_id() == "fallback-embed"


def test_build_model_uses_resolved_id() -> None:
    settings = Settings(
        _env_file=None,
        provider=ProviderSettings(base_url="http://x/v1", api_key="k", chat_model_id="m1"),
    )
    assert model_name_for(settings, "coach") == "m1"
    model = build_model(settings, "coach")
    assert model.model_name == "m1"


def test_normalize_drops_non_string_metadata() -> None:
    body = json.dumps(
        {
            "id": "x",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "metadata": {"weight_versions": [{"version": "default", "start": 0, "end": 5}]},
        }
    ).encode()
    normalized = _normalize_json(body)
    assert normalized is not None
    assert "metadata" not in json.loads(normalized)


def test_normalize_keeps_string_metadata_and_noops() -> None:
    ok = json.dumps({"metadata": {"a": "b"}, "choices": []}).encode()
    assert _normalize_json(ok) is None
    assert _normalize_json(b"not json") is None


def test_is_str_map() -> None:
    assert _is_str_map({"a": "b"})
    assert _is_str_map(None)
    assert not _is_str_map({"a": [1]})
    assert not _is_str_map([1, 2])


def test_should_normalize_only_non_streaming_chat() -> None:
    chat = httpx.Request("POST", "http://x/v1/chat/completions", json={"stream": False})
    stream = httpx.Request("POST", "http://x/v1/chat/completions", json={"stream": True})
    other = httpx.Request("POST", "http://x/v1/embeddings", json={})
    assert _should_normalize(chat) is True
    assert _should_normalize(stream) is False
    assert _should_normalize(other) is False
