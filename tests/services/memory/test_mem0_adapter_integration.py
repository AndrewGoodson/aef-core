"""Runs `Mem0Adapter` against a REAL `mem0.Memory()` — fastembed embedder +
faiss vector store, both fully local. No network call to any LLM (mem0
still requires an LLM client to be *constructible* even though `infer=False`
means it's never actually invoked — a real gotcha, documented in the
adapter's module docstring and docs/adr/0004; a dummy, never-used API key
value satisfies that construction requirement).

Self-skips when `fastembed`/`faiss` aren't installed — this is what
`pip install -e ".[mem0,mem0-integration]"` is for; not part of the
default dev install or CI. This test caught two real bugs the fake-client
unit tests (test_mem0_adapter.py) could not: mem0 requires an identity
(user_id/agent_id/run_id) on every add()/search() call, and mem0 rejects
empty-string search queries outright — both are exercised for real here,
not just asserted against a fake that might not mirror mem0's actual
behavior.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastembed")
pytest.importorskip("faiss")

from aef.services.memory.adapters.mem0_adapter import Mem0Adapter, Mem0IdentityRequiredError
from aef.services.memory.base import MemoryRecord


@pytest.fixture
def real_mem0_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Mem0Adapter]:
    # mem0.Memory() eagerly constructs an LLM client (default provider
    # "openai") even though write() always calls add(..., infer=False),
    # which never actually invokes it. No real API key is required to be
    # valid — just present — and no network call to OpenAI happens here.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy-never-called")

    from mem0 import Memory
    from mem0.configs.base import MemoryConfig
    from mem0.embeddings.configs import EmbedderConfig
    from mem0.vector_stores.configs import VectorStoreConfig

    store_path = tmp_path / "faiss_store"
    config = MemoryConfig(
        embedder=EmbedderConfig(provider="fastembed", config={"model": "BAAI/bge-small-en-v1.5"}),
        vector_store=VectorStoreConfig(
            provider="faiss",
            config={
                "collection_name": "aef_integration_test",
                "path": str(store_path),
                "embedding_model_dims": 384,
            },
        ),
    )
    memory = Memory(config)
    yield Mem0Adapter(memory)
    shutil.rmtree(store_path, ignore_errors=True)


def test_real_semantic_recall_with_meaningful_tags(real_mem0_adapter: Mem0Adapter) -> None:
    adapter = real_mem0_adapter
    adapter.write(
        MemoryRecord(
            kind="semantic",
            content={"text": "The storage account 'proddata' has public blob access enabled."},
            agent_id="azure_sec",
            tags=("azure", "storage"),
        )
    )
    adapter.write(
        MemoryRecord(
            kind="semantic",
            content={"text": "The user's favorite programming language is Python."},
            agent_id="azure_sec",
            tags=("preference",),
        )
    )
    adapter.write(
        MemoryRecord(
            kind="semantic",
            content={"text": "RAPTOR's risk-per-trade constraint is capped at 3 percent."},
            agent_id="azure_sec",
            tags=("trading", "risk"),
        )
    )

    results = adapter.query("semantic", agent_id="azure_sec", tags=("azure", "storage"))

    assert len(results) == 1
    assert "proddata" in results[0].content["text"]


def test_real_get_round_trips_via_native_mem0_id(real_mem0_adapter: Mem0Adapter) -> None:
    adapter = real_mem0_adapter
    record = MemoryRecord(
        kind="procedural",
        content={"text": "retry-with-backoff plan template"},
        agent_id="azure_sec",
        tags=("retry",),
    )
    adapter.write(record)

    fetched = adapter.get(record.id)

    assert fetched is not None
    assert fetched.content["text"] == "retry-with-backoff plan template"
    assert fetched.tags == ("retry",)


def test_real_get_on_unwritten_id_returns_none(real_mem0_adapter: Mem0Adapter) -> None:
    assert real_mem0_adapter.get("never-written") is None


def test_real_write_without_identity_raises_before_calling_mem0(
    real_mem0_adapter: Mem0Adapter,
) -> None:
    with pytest.raises(Mem0IdentityRequiredError):
        real_mem0_adapter.write(MemoryRecord(kind="working", content={"text": "orphan"}))


def test_real_query_without_identity_raises_before_calling_mem0(
    real_mem0_adapter: Mem0Adapter,
) -> None:
    with pytest.raises(Mem0IdentityRequiredError):
        real_mem0_adapter.query("working")
