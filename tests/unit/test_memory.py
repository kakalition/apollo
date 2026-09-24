# pyright: reportCallIssue=false
"""Memory facade and Mem0 result/adaptor mapping (no network)."""

from __future__ import annotations

from apollo.config import EmbeddingsSettings, ProviderSettings, Settings
from apollo.memory.facade import InMemoryMemory
from apollo.memory.mem0_backend import _as_list, _to_item, build_mem0_config, embedder_config


def test_in_memory_recall_ranks_overlap() -> None:
    memory = InMemoryMemory()
    memory.remember("I run before breakfast")
    memory.remember("Sam's birthday is in May")
    hits = memory.recall("breakfast run", k=2)
    assert hits and hits[0].text == "I run before breakfast"
    assert hits[0].score is not None


def test_in_memory_forget() -> None:
    memory = InMemoryMemory()
    memory_id = memory.remember("ephemeral")
    assert memory_id is not None
    memory.forget(memory_id)
    assert memory.recall("ephemeral") == []


def test_as_list_and_to_item_handle_mem0_shapes() -> None:
    assert _as_list(None) == []
    assert _as_list({"results": [{"memory": "hi", "id": 1, "score": 0.5}]})[0]["memory"] == "hi"
    item = _to_item({"memory": "hello", "id": "abc", "score": 0.7, "source": "x"})
    assert item.id == "abc" and item.text == "hello" and item.score == 0.7
    assert item.metadata == {"source": "x"}


def test_embedder_prefers_provider_embedding_id() -> None:
    settings = Settings(
        _env_file=None,
        provider=ProviderSettings(
            base_url="https://openrouter.ai/api/v1",
            api_key="k",
            embedding_model_id="openai/text-embedding-3-small",
        ),
    )
    cfg = embedder_config(settings)
    assert cfg["provider"] == "openai"
    assert cfg["config"]["model"] == "openai/text-embedding-3-small"


def test_embedder_falls_back_to_local() -> None:
    settings = Settings(
        _env_file=None,
        provider=ProviderSettings(base_url="http://x/v1", api_key="k"),
        embeddings=EmbeddingsSettings(fallback="local", local_model="BAAI/bge-small-en-v1.5"),
    )
    cfg = embedder_config(settings)
    assert cfg["provider"] == "huggingface"
    assert cfg["config"]["model"] == "BAAI/bge-small-en-v1.5"


def test_mem0_config_targets_chroma_and_chat_model() -> None:
    settings = Settings(
        _env_file=None,
        provider=ProviderSettings(
            base_url="http://x/v1", api_key="k", chat_model_id="m1", embedding_model_id="e1"
        ),
    )
    config = build_mem0_config(settings)
    assert config["vector_store"]["provider"] == "chroma"
    assert config["vector_store"]["config"]["host"] == "localhost"
    assert config["llm"]["config"]["model"] == "m1"
    assert config["embedder"]["config"]["model"] == "e1"
