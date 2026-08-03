from typing import Any

from aef.services.memory.adapters.mem0_adapter import Mem0Adapter
from aef.services.memory.base import MemoryRecord


class _FakeMem0Client:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, Any]] = []
        self._store: list[dict[str, Any]] = []

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
        self._store.append(
            {
                "memory": messages[0]["content"],
                "user_id": user_id,
                "run_id": run_id,
                "metadata": metadata or {},
                "id": f"mem0-{len(self._store)}",
            }
        )
        return {"results": [self._store[-1]]}

    def search(
        self, query: str, *, top_k: int = 20, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"results": list(self._store)[:top_k]}


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


def test_query_filters_out_other_kinds_and_missing_tags() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    adapter.write(MemoryRecord(kind="semantic", content={"text": "fact one"}, tags=("azure",)))
    adapter.write(MemoryRecord(kind="episodic", content={"text": "trace one"}, tags=("azure",)))
    adapter.write(MemoryRecord(kind="semantic", content={"text": "fact two"}, tags=("aws",)))

    results = adapter.query("semantic", tags=("azure",))

    assert len(results) == 1
    assert results[0].content["text"] == "fact one"


def test_get_round_trips_via_record_id_metadata() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    record = MemoryRecord(kind="procedural", content={"text": "plan template"}, tags=("retry",))
    adapter.write(record)

    fetched = adapter.get(record.id)

    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.content == {"text": "plan template"}
    assert fetched.tags == ("retry",)


def test_get_missing_id_returns_none() -> None:
    client = _FakeMem0Client()
    adapter = Mem0Adapter(client)
    adapter.write(MemoryRecord(kind="working", content={"text": "irrelevant"}))

    assert adapter.get("no-such-id") is None
