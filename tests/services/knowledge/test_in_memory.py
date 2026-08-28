from datetime import UTC, datetime

import pytest

from aef.services.knowledge.base import KnowledgeEntry, KnowledgeStore
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 1, 2, tzinfo=UTC)
T3 = datetime(2026, 1, 3, tzinfo=UTC)


def _entry(
    signature: str = "failure:fetch",
    *,
    kind: str = "failure",
    agent_id: str | None = "a1",
    content: dict[str, object] | None = None,
    source_record_ids: tuple[str, ...] = ("r1", "r2"),
    first_seen: datetime | None = T1,
    last_seen: datetime | None = T2,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        signature=signature,
        kind=kind,  # type: ignore[arg-type]
        content=content if content is not None else {"lesson": "fetch times out"},
        agent_id=agent_id,
        source_record_ids=source_record_ids,
        first_seen=first_seen,
        last_seen=last_seen,
    )


# ---------------------------------------------------------------------------
# Construction-time validation (ADR 0108: not at serialise time)
# ---------------------------------------------------------------------------
def test_empty_signature_rejected() -> None:
    with pytest.raises(ValueError, match="signature must be non-empty"):
        _entry(signature="")


def test_entry_without_provenance_rejected() -> None:
    """An entry with no source records is a claim with no evidence."""
    with pytest.raises(ValueError, match="claim with no evidence"):
        _entry(source_record_ids=())


def test_duplicate_provenance_rejected_at_construction() -> None:
    """The same record counted twice is fabricated evidence: occurrence_count
    is the entry's ONLY measure of how well-established it is."""
    with pytest.raises(ValueError, match="must be unique"):
        _entry(source_record_ids=("r1", "r1"))


def test_first_seen_after_last_seen_rejected() -> None:
    with pytest.raises(ValueError, match="must not be after last_seen"):
        _entry(first_seen=T3, last_seen=T1)


# ---------------------------------------------------------------------------
# Derived quantities
# ---------------------------------------------------------------------------
def test_occurrence_count_is_derived_from_provenance() -> None:
    assert _entry(source_record_ids=("r1", "r2", "r3")).occurrence_count == 3


def test_confidence_is_monotonic_and_bounded() -> None:
    counts = [2, 4, 10, 50]
    confidences = [
        _entry(source_record_ids=tuple(f"r{i}" for i in range(n))).confidence for n in counts
    ]
    assert confidences == sorted(confidences)
    assert all(0.0 < c < 1.0 for c in confidences)
    # CONFIDENCE_HALF_LIFE == 4, so four occurrences is the half-way point.
    assert confidences[1] == pytest.approx(0.5)


def test_key_is_a_tuple_not_a_joined_string() -> None:
    """A delimiter-joined key collides as soon as either part contains the
    delimiter — the defect fixed for kernel approval keys in f7e8f01."""
    colliding_a = _entry(agent_id="a:b", signature="c")
    colliding_b = _entry(agent_id="a", signature="b:c")
    assert colliding_a.key != colliding_b.key


# ---------------------------------------------------------------------------
# Upsert / merge
# ---------------------------------------------------------------------------
def test_upsert_then_get_round_trip() -> None:
    store = InMemoryKnowledgeStore()
    entry = _entry()
    store.upsert(entry)
    fetched = store.get(entry.key)
    assert fetched is not None
    assert fetched.content == {"lesson": "fetch times out"}
    assert fetched.occurrence_count == 2


def test_upsert_merges_provenance_by_key() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(source_record_ids=("r1", "r2")))
    merged = store.upsert(_entry(source_record_ids=("r3",)))
    assert merged.source_record_ids == ("r1", "r2", "r3")
    assert merged.occurrence_count == 3


def test_reupserting_the_same_record_does_not_inflate_the_count() -> None:
    """The adversarial case. A consolidator re-run over an unchanged memory
    store must not manufacture confidence out of the same evidence — an entry
    that grows on every idle pass would report certainty it never earned."""
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(source_record_ids=("r1", "r2")))
    again = store.upsert(_entry(source_record_ids=("r1", "r2")))
    assert again.source_record_ids == ("r1", "r2")
    assert again.occurrence_count == 2


def test_entries_from_different_agents_never_merge() -> None:
    """The seam this store is keyed to prevent. `MemoryRetriever.agent_id` was
    found to have defaulted to 'every agent', handing one agent another's
    recorded failures. A merged entry is worse: it cannot be un-merged."""
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(agent_id="a1", source_record_ids=("r1", "r2")))
    store.upsert(_entry(agent_id="a2", source_record_ids=("r8", "r9")))

    a1 = store.get(("a1", "failure:fetch"))
    a2 = store.get(("a2", "failure:fetch"))
    assert a1 is not None and a2 is not None
    assert a1.source_record_ids == ("r1", "r2")
    assert a2.source_record_ids == ("r8", "r9")


def test_merge_widens_the_time_window_in_both_directions() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(source_record_ids=("r1",), first_seen=T2, last_seen=T2))
    merged = store.upsert(_entry(source_record_ids=("r2",), first_seen=T1, last_seen=T3))
    assert merged.first_seen == T1
    assert merged.last_seen == T3


def test_merge_preserves_provenance_order() -> None:
    """The trail is an audit trail; one whose order changes between identical
    consolidations cannot be diffed."""
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(source_record_ids=("r5", "r1")))
    merged = store.upsert(_entry(source_record_ids=("r1", "r9", "r3")))
    assert merged.source_record_ids == ("r5", "r1", "r9", "r3")


def test_merge_takes_content_from_the_newer_consolidation() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(content={"lesson": "old"}, source_record_ids=("r1",)))
    merged = store.upsert(_entry(content={"lesson": "new"}, source_record_ids=("r2",)))
    assert merged.content == {"lesson": "new"}


def test_merge_tolerates_a_missing_timestamp_on_either_side() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(source_record_ids=("r1",), first_seen=None, last_seen=None))
    merged = store.upsert(_entry(source_record_ids=("r2",), first_seen=T1, last_seen=T2))
    assert merged.first_seen == T1
    assert merged.last_seen == T2


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
def test_query_filters_by_kind_and_agent() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(signature="s1", kind="failure", agent_id="a1"))
    store.upsert(_entry(signature="s2", kind="success", agent_id="a1"))
    store.upsert(_entry(signature="s3", kind="failure", agent_id="a2"))

    results = store.query("failure", agent_id="a1")
    assert [e.signature for e in results] == ["s1"]


def test_query_min_occurrences_excludes_thin_evidence() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(signature="thin", source_record_ids=("r1",)))
    store.upsert(_entry(signature="thick", source_record_ids=("r2", "r3", "r4")))

    results = store.query("failure", min_occurrences=3)
    assert [e.signature for e in results] == ["thick"]


def test_query_orders_by_recency_and_respects_limit() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry(signature="oldest", source_record_ids=("r1",), last_seen=T1))
    store.upsert(_entry(signature="newest", source_record_ids=("r2",), last_seen=T3))
    store.upsert(_entry(signature="middle", source_record_ids=("r3",), last_seen=T2))

    results = store.query("failure", limit=2)
    assert [e.signature for e in results] == ["newest", "middle"]


def test_query_tie_break_is_ascending_by_key_not_reversed() -> None:
    """Equal timestamps must not come back in reverse alphabetical order: the
    order has to be both TOTAL and unsurprising, or a deterministic node that
    retrieves gets a replay mismatch that is really a sort artefact."""
    store = InMemoryKnowledgeStore()
    for sig in ("c", "a", "b"):
        store.upsert(_entry(signature=sig, source_record_ids=(f"r{sig}",), last_seen=T1))

    results = store.query("failure")
    assert [e.signature for e in results] == ["a", "b", "c"]


def test_query_is_stable_across_identical_calls() -> None:
    store = InMemoryKnowledgeStore()
    for sig in ("z", "y", "x"):
        store.upsert(_entry(signature=sig, source_record_ids=(f"r{sig}",), last_seen=T1))

    assert [e.key for e in store.query("failure")] == [e.key for e in store.query("failure")]


def test_query_rejects_negative_limit() -> None:
    store = InMemoryKnowledgeStore()
    with pytest.raises(ValueError, match="limit must be non-negative"):
        store.query("failure", limit=-1)


def test_query_rejects_min_occurrences_below_one() -> None:
    store = InMemoryKnowledgeStore()
    with pytest.raises(ValueError, match="min_occurrences must be at least 1"):
        store.query("failure", min_occurrences=0)


def test_query_zero_limit_returns_nothing() -> None:
    store = InMemoryKnowledgeStore()
    store.upsert(_entry())
    assert store.query("failure", limit=0) == []


def test_get_missing_returns_none() -> None:
    store = InMemoryKnowledgeStore()
    assert store.get(("a1", "nope")) is None


# ---------------------------------------------------------------------------
# Snapshot isolation — mirrors the memory store's guarantees
# ---------------------------------------------------------------------------
def test_upsert_snapshots_nested_content() -> None:
    content: dict[str, object] = {"nested": {"value": "at-write"}}
    store = InMemoryKnowledgeStore()
    entry = _entry(content=content)
    store.upsert(entry)

    nested = content["nested"]
    assert isinstance(nested, dict)
    nested["value"] = "rewritten-later"

    fetched = store.get(entry.key)
    assert fetched is not None
    assert fetched.content == {"nested": {"value": "at-write"}}


def test_read_returns_a_snapshot_not_a_store_reference() -> None:
    store = InMemoryKnowledgeStore()
    entry = _entry(content={"nested": {"value": "stored"}})
    store.upsert(entry)

    fetched = store.get(entry.key)
    assert fetched is not None
    nested = fetched.content["nested"]
    assert isinstance(nested, dict)
    nested["value"] = "rewritten-by-reader"

    again = store.get(entry.key)
    assert again is not None
    assert again.content == {"nested": {"value": "stored"}}


def test_upsert_return_value_is_a_snapshot_too() -> None:
    store = InMemoryKnowledgeStore()
    entry = _entry(content={"nested": {"value": "stored"}})
    returned = store.upsert(entry)

    nested = returned.content["nested"]
    assert isinstance(nested, dict)
    nested["value"] = "rewritten-by-caller"

    fetched = store.get(entry.key)
    assert fetched is not None
    assert fetched.content == {"nested": {"value": "stored"}}


def test_in_memory_store_satisfies_the_interface() -> None:
    assert isinstance(InMemoryKnowledgeStore(), KnowledgeStore)
