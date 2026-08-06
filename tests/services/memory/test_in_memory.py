import threading
from datetime import UTC, datetime
from typing import Any, cast

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


def test_falsey_explicit_clock_is_not_replaced() -> None:
    expected = datetime(2020, 1, 2, tzinfo=UTC)

    class FalseyClock:
        def __bool__(self) -> bool:
            return False

        def __call__(self) -> datetime:
            return expected

    store = InMemoryMemoryStore(clock=FalseyClock())
    record = MemoryRecord(kind="semantic", content={"text": "x"})

    store.write(record)

    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.created_at == expected


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


def test_write_snapshots_nested_record_content() -> None:
    content = {"nested": {"value": "at-write"}}
    record = MemoryRecord(kind="semantic", content=content)
    store = InMemoryMemoryStore()

    store.write(record)
    content["nested"]["value"] = "rewritten-later"

    fetched = store.get(record.id)
    assert fetched is not None
    assert fetched.content == {"nested": {"value": "at-write"}}


def test_read_returns_snapshot_not_mutable_store_reference() -> None:
    record = MemoryRecord(kind="semantic", content={"nested": {"value": "stored"}})
    store = InMemoryMemoryStore()
    store.write(record)

    fetched = store.get(record.id)
    assert fetched is not None
    fetched.content["nested"]["value"] = "rewritten-by-reader"

    fetched_again = store.get(record.id)
    assert fetched_again is not None
    assert fetched_again.content == {"nested": {"value": "stored"}}


def test_query_and_write_can_run_concurrently() -> None:
    entered_comparison = threading.Event()
    release_comparison = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()
    errors: list[BaseException] = []

    class _BlockingKind:
        def __eq__(self, other: object) -> bool:
            entered_comparison.set()
            assert release_comparison.wait(timeout=2)
            return other == "working"

    store = InMemoryMemoryStore()
    store.write(
        MemoryRecord(
            kind=cast(Any, _BlockingKind()),
            content={"position": "first"},
        )
    )

    def query() -> None:
        try:
            store.query("working")
        except BaseException as exc:
            errors.append(exc)

    def write() -> None:
        writer_started.set()
        store.write(MemoryRecord(kind="working", content={"position": "second"}))
        writer_finished.set()

    query_thread = threading.Thread(target=query)
    writer_thread = threading.Thread(target=write)
    query_thread.start()
    assert entered_comparison.wait(timeout=1)
    writer_thread.start()
    assert writer_started.wait(timeout=1)

    # Without synchronization the write completes while the query's dict
    # iterator is suspended, deterministically invalidating that iterator.
    writer_finished.wait(timeout=0.1)
    release_comparison.set()
    query_thread.join(timeout=2)
    writer_thread.join(timeout=2)

    assert not query_thread.is_alive()
    assert not writer_thread.is_alive()
    assert errors == []
    assert writer_finished.is_set()
