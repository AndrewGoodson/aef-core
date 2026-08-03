from typing import Any

import pytest

from aef.services.memory.adapters.mem0_adapter import Mem0Adapter, Mem0IdentityRequiredError
from aef.services.memory.base import MemoryRecord


class _FakeMem0Client:
    """Mirrors real mem0's actual contract, confirmed by running the
    adapter against a real local mem0.Memory() (fastembed + faiss):
    `add()` returns `{"results": [{"id": <native_id>, ...}]}`, and `.get()`
    is a real by-id lookup, not a search.
    """

    def __init__(self) -> None:
        self.add_calls: list[dict[str, Any]] = []
        self._store: dict[str, dict[str, Any]] = {}
        self._next_id = 0

    def add(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = True,
    ) -> dict[str, Any]:
        self.add_calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "run_id": run_id,
                "metadata": metadata,
                "infer": infer,
            }
        )
        native_id = f"mem0-{self._next_id}"
        self._next_id += 1
        self._store[native_id] = {
            "id": native_id,
            "memory": messages[0]["content"],
            "user_id": user_id,
            "run_id": run_id,
            "metadata": metadata or {},
        }
        return {"results": [{"id": native_id}]}

    def search(
        self, query: str, *, top_k: int = 20, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"results": list(self._store.values())[:top_k]}

    def get(self, memory_id: str) -> dict[str, Any] | None:
        return self._store.get(memory_id)


def test_write_calls_add_with_infer_false_and_metadata() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    record = MemoryRecord(
        kind="semantic",
        content={"text": "the sky is blue"},
        run_id="r1",
        agent_id="a1",
        tags=("weather",),
    )

    returned_id = adapter.write(record)

    assert returned_id == record.id
    call = client.add_calls[0]
    assert call["infer"] is False
    assert call["messages"] == [{"role": "user", "content": "the sky is blue"}]
    assert call["user_id"] == "a1"
    assert call["run_id"] == "r1"
    assert call["metadata"]["aef_kind"] == "semantic"
    assert call["metadata"]["aef_tags"] == ["weather"]
    assert call["metadata"]["aef_record_id"] == record.id


def test_write_without_agent_id_or_run_id_raises() -> None:
    adapter = Mem0Adapter(_FakeMem0Client())
    record = MemoryRecord(kind="semantic", content={"text": "orphan"})
    with pytest.raises(Mem0IdentityRequiredError):
        adapter.write(record)


def test_query_without_agent_id_or_run_id_raises() -> None:
    adapter = Mem0Adapter(_FakeMem0Client())
    with pytest.raises(Mem0IdentityRequiredError):
        adapter.query("semantic")


def test_query_filters_out_other_kinds_and_missing_tags() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    adapter.write(
        MemoryRecord(kind="semantic", content={"text": "fact one"}, agent_id="a1", tags=("azure",))
    )
    adapter.write(
        MemoryRecord(kind="episodic", content={"text": "trace one"}, agent_id="a1", tags=("azure",))
    )
    adapter.write(
        MemoryRecord(kind="semantic", content={"text": "fact two"}, agent_id="a1", tags=("aws",))
    )

    results = adapter.query("semantic", agent_id="a1", tags=("azure",))

    assert len(results) == 1
    assert results[0].content["text"] == "fact one"


def test_get_round_trips_via_native_id_index() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    record = MemoryRecord(
        kind="procedural", content={"text": "plan template"}, agent_id="a1", tags=("retry",)
    )
    adapter.write(record)

    fetched = adapter.get(record.id)

    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.content == {"text": "plan template"}
    assert fetched.tags == ("retry",)


def test_get_missing_id_returns_none() -> None:
    adapter = Mem0Adapter(_FakeMem0Client())
    adapter.write(MemoryRecord(kind="working", content={"text": "irrelevant"}, agent_id="a1"))

    assert adapter.get("no-such-id") is None


def test_get_never_written_id_returns_none_without_calling_client() -> None:
    """An id this adapter instance never wrote has no native-id mapping —
    get() must short-circuit rather than call the client with a bogus id."""
    adapter = Mem0Adapter(_FakeMem0Client())
    assert adapter.get("never-seen") is None
