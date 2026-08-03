from datetime import UTC, datetime

from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore


def test_write_then_get_round_trip() -> None:
    store = InMemoryMemoryStore()
    record = MemoryRecord(kind="working", content={"x": 1}, run_id="r1", agent_id="a1")
    returned_id = store.write(record)
    assert returned_id == record.id
    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.content == {"x": 1}


def test_write_backfills_created_at_when_missing() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    store = InMemoryMemoryStore(clock=lambda: fixed_time)
    record = MemoryRecord(kind="episodic", content={})
    store.write(record)
    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.created_at == fixed_time


def test_write_preserves_explicit_created_at() -> None:
    explicit_time = datetime(2020, 1, 1, tzinfo=UTC)
    store = InMemoryMemoryStore()
    record = MemoryRecord(kind="episodic", content={}, created_at=explicit_time)
    store.write(record)
    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.created_at == explicit_time


def test_query_filters_by_kind_run_and_agent() -> None:
    store = InMemoryMemoryStore()
    store.write(MemoryRecord(kind="working", content={}, run_id="r1", agent_id="a1"))
    store.write(MemoryRecord(kind="episodic", content={}, run_id="r1", agent_id="a1"))
    store.write(MemoryRecord(kind="working", content={}, run_id="r2", agent_id="a1"))
    store.write(MemoryRecord(kind="working", content={}, run_id="r1", agent_id="a2"))

    results = store.query("working", run_id="r1", agent_id="a1")
    assert len(results) == 1


def test_query_filters_by_tags_requires_all() -> None:
    store = InMemoryMemoryStore()
    store.write(MemoryRecord(kind="failure", content={}, tags=("azure", "auth")))
    store.write(MemoryRecord(kind="failure", content={}, tags=("azure",)))

    results = store.query("failure", tags=("azure", "auth"))
    assert len(results) == 1


def test_query_respects_limit_and_recency_order() -> None:
    store = InMemoryMemoryStore()
    times = [datetime(2026, 1, i, tzinfo=UTC) for i in (1, 2, 3)]
    for i, ts in enumerate(times):
        store.write(MemoryRecord(kind="success", content={"n": i}, created_at=ts))

    results = store.query("success", limit=2)
    assert len(results) == 2
    assert results[0].content["n"] == 2  # most recent first
    assert results[1].content["n"] == 1


def test_get_missing_returns_none() -> None:
    store = InMemoryMemoryStore()
    assert store.get("does-not-exist") is None
