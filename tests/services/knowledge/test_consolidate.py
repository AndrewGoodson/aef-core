import dataclasses
from datetime import UTC, datetime

import pytest

from aef.services.knowledge.consolidate import (
    RuleBasedConsolidator,
    default_signature,
)
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 1, 2, tzinfo=UTC)
T3 = datetime(2026, 1, 3, tzinfo=UTC)


def _failure(
    *,
    run_id: str,
    failing_nodes: list[str] | object = ("fetch",),
    agent_id: str | None = "a1",
    created_at: datetime | None = T1,
    feedback: str = "fetch timed out",
    objective: str = "settle the invoice",
) -> MemoryRecord:
    return MemoryRecord(
        kind="failure",
        content={
            "failing_nodes": list(failing_nodes)  # type: ignore[call-overload]
            if isinstance(failing_nodes, (list, tuple))
            else failing_nodes,
            "verbal_feedback": feedback,
            "objective": objective,
        },
        run_id=run_id,
        agent_id=agent_id,
        created_at=created_at,
    )


def _success(
    *,
    run_id: str,
    objective: str = "settle the invoice",
    agent_id: str | None = "a1",
    created_at: datetime | None = T1,
) -> MemoryRecord:
    return MemoryRecord(
        kind="success",
        content={"objective": objective, "verbal_feedback": "clean run"},
        run_id=run_id,
        agent_id=agent_id,
        created_at=created_at,
    )


def _stores(records: list[MemoryRecord]) -> tuple[InMemoryMemoryStore, InMemoryKnowledgeStore]:
    memory = InMemoryMemoryStore()
    for record in records:
        memory.write(record)
    return memory, InMemoryKnowledgeStore()


# ---------------------------------------------------------------------------
# The signature function
# ---------------------------------------------------------------------------
def test_failure_signature_uses_failing_nodes() -> None:
    assert default_signature(_failure(run_id="r1", failing_nodes=["fetch", "parse"])) == (
        "failure:fetch>parse"
    )


def test_failure_signature_preserves_node_order() -> None:
    """A->B and B->A are different failures: the first failure is usually the
    cause and the rest are consequences, which is why `_failing_nodes` keeps
    first-seen order rather than sorting."""
    a = default_signature(_failure(run_id="r1", failing_nodes=["fetch", "parse"]))
    b = default_signature(_failure(run_id="r1", failing_nodes=["parse", "fetch"]))
    assert a != b


def test_unattributable_failure_has_no_signature() -> None:
    """Dropped, never bucketed into a catch-all — a catch-all would merge
    unrelated failures into one entry and manufacture a lesson nobody learned."""
    assert default_signature(_failure(run_id="r1", failing_nodes=[])) is None


def test_signature_survives_malformed_content() -> None:
    """`content` is dict[str, Any] and nothing constrains its shape."""
    assert default_signature(_failure(run_id="r1", failing_nodes="not-a-list")) is None
    assert default_signature(_failure(run_id="r1", failing_nodes=[None, 42])) is None


def test_success_signature_uses_objective() -> None:
    assert default_signature(_success(run_id="r1", objective="ship it")) == "success:ship it"


def test_success_without_objective_has_no_signature() -> None:
    assert default_signature(_success(run_id="r1", objective="")) is None


def test_other_memory_kinds_have_no_signature() -> None:
    record = MemoryRecord(kind="working", content={"objective": "x"}, run_id="r1")
    assert default_signature(record) is None


# ---------------------------------------------------------------------------
# The threshold — the point of the whole layer
# ---------------------------------------------------------------------------
def test_a_single_occurrence_is_not_knowledge() -> None:
    """THE planted-fault check for this increment. One occurrence is an
    episode; a consolidator that emits from it promotes noise to knowledge."""
    memory, knowledge = _stores([_failure(run_id="r1")])
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert written == []
    assert knowledge.query("failure") == []


def test_two_occurrences_across_runs_become_knowledge() -> None:
    memory, knowledge = _stores(
        [_failure(run_id="r1", created_at=T1), _failure(run_id="r2", created_at=T2)]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert len(written) == 1
    entry = written[0]
    assert entry.signature == "failure:fetch"
    assert entry.occurrence_count == 2
    assert entry.first_seen == T1
    assert entry.last_seen == T2


def test_repeated_reflections_within_one_run_are_one_occurrence() -> None:
    """A graph may reflect more than once per run — `make_reflect_node`'s
    idempotency key is keyed on checkpoint_seq for exactly that reason. Three
    records from one run is one bad run, not an established pattern."""
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", created_at=T1),
            _failure(run_id="r1", created_at=T2),
            _failure(run_id="r1", created_at=T3),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert written == []


def test_records_without_a_run_id_cannot_evidence_recurrence() -> None:
    """A record not attributable to a run cannot show something recurred
    ACROSS runs, and inventing a run for it would be a guess."""
    memory = InMemoryMemoryStore()
    for _ in range(3):
        memory.write(
            MemoryRecord(
                kind="failure",
                content={"failing_nodes": ["fetch"], "verbal_feedback": "x"},
                run_id=None,
                agent_id="a1",
                created_at=T1,
            )
        )
    knowledge = InMemoryKnowledgeStore()
    assert RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1") == []


def test_unsignable_records_are_dropped_not_pooled() -> None:
    """Found by a planted fault that the first draft of this file MISSED.

    `default_signature` returning None was asserted at the unit level, but
    nothing asserted what the consolidator does with it. Bucketing the
    unsignable into a shared 'unknown' key passes every other test here and
    fabricates a lesson: two unrelated, unattributable failures reach the
    threshold together and emerge as one entry claiming both as its evidence.
    """
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", failing_nodes=[], feedback="disk full"),
            _failure(run_id="r2", failing_nodes=[], feedback="auth expired"),
        ]
    )
    assert RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1") == []
    assert knowledge.query("failure") == []


def test_signable_and_unsignable_records_do_not_contaminate_each_other() -> None:
    """The mixed case: a genuine recurring failure alongside unattributable
    noise must consolidate to itself alone, with the noise in neither its
    provenance nor its count."""
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", failing_nodes=["fetch"], created_at=T1),
            _failure(run_id="r2", failing_nodes=["fetch"], created_at=T2),
            _failure(run_id="r3", failing_nodes=[], created_at=T3),
            _failure(run_id="r4", failing_nodes=[], created_at=T3),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert [e.signature for e in written] == ["failure:fetch"]
    assert written[0].occurrence_count == 2
    assert written[0].content["run_ids"] == ["r1", "r2"]


def test_threshold_below_two_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="min_occurrences must be at least 2"):
        RuleBasedConsolidator(min_occurrences=1)


def test_raising_the_threshold_raises_the_bar() -> None:
    records = [_failure(run_id=f"r{i}", created_at=T1) for i in range(3)]
    memory, knowledge = _stores(records)
    assert (
        RuleBasedConsolidator(min_occurrences=4).consolidate(memory, knowledge, agent_id="a1") == []
    )
    assert (
        len(RuleBasedConsolidator(min_occurrences=3).consolidate(memory, knowledge, agent_id="a1"))
        == 1
    )


# ---------------------------------------------------------------------------
# Grouping and isolation
# ---------------------------------------------------------------------------
def test_distinct_signatures_do_not_merge() -> None:
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", failing_nodes=["fetch"]),
            _failure(run_id="r2", failing_nodes=["fetch"]),
            _failure(run_id="r3", failing_nodes=["parse"]),
            _failure(run_id="r4", failing_nodes=["parse"]),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert sorted(e.signature for e in written) == ["failure:fetch", "failure:parse"]


def test_agents_are_never_merged_even_when_reading_across_them() -> None:
    """`agent_id=None` means 'read every agent'. It must NOT mean 'merge
    them': grouping keys on each record's own agent_id."""
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", agent_id="a1"),
            _failure(run_id="r2", agent_id="a1"),
            _failure(run_id="r3", agent_id="a2"),
            _failure(run_id="r4", agent_id="a2"),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id=None)
    assert len(written) == 2
    assert {e.agent_id for e in written} == {"a1", "a2"}
    assert all(e.occurrence_count == 2 for e in written)


def test_one_agents_runs_do_not_top_up_anothers_threshold() -> None:
    """Two agents failing once each is not one agent failing twice."""
    memory, knowledge = _stores(
        [_failure(run_id="r1", agent_id="a1"), _failure(run_id="r2", agent_id="a2")]
    )
    assert RuleBasedConsolidator().consolidate(memory, knowledge, agent_id=None) == []


def test_successes_consolidate_too() -> None:
    memory, knowledge = _stores(
        [_success(run_id="r1", created_at=T1), _success(run_id="r2", created_at=T2)]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert [e.kind for e in written] == ["success"]


# ---------------------------------------------------------------------------
# Determinism and idempotence
# ---------------------------------------------------------------------------
def test_reconsolidating_unchanged_memory_changes_nothing() -> None:
    """Stateless recompute: no cursor, no 'already consolidated' marker. The
    store's dedupe must absorb the re-run into no change at all, or every idle
    pass would inflate confidence."""
    memory, knowledge = _stores(
        [_failure(run_id="r1", created_at=T1), _failure(run_id="r2", created_at=T2)]
    )
    consolidator = RuleBasedConsolidator()
    first = consolidator.consolidate(memory, knowledge, agent_id="a1")
    second = consolidator.consolidate(memory, knowledge, agent_id="a1")
    assert first[0].occurrence_count == 2
    assert second[0].occurrence_count == 2
    assert second[0].source_record_ids == first[0].source_record_ids


def test_a_new_run_extends_the_existing_entry() -> None:
    memory, knowledge = _stores(
        [_failure(run_id="r1", created_at=T1), _failure(run_id="r2", created_at=T2)]
    )
    consolidator = RuleBasedConsolidator()
    consolidator.consolidate(memory, knowledge, agent_id="a1")
    memory.write(_failure(run_id="r3", created_at=T3))
    written = consolidator.consolidate(memory, knowledge, agent_id="a1")
    assert written[0].occurrence_count == 3
    assert written[0].last_seen == T3


def test_output_is_identical_across_repeated_calls() -> None:
    memory, knowledge = _stores(
        [_failure(run_id=f"r{i}", failing_nodes=[f"n{i % 2}"], created_at=T1) for i in range(6)]
    )
    consolidator = RuleBasedConsolidator()
    a = consolidator.consolidate(memory, knowledge, agent_id="a1")
    b = consolidator.consolidate(memory, knowledge, agent_id="a1")
    assert [e.key for e in a] == [e.key for e in b]
    assert [e.source_record_ids for e in a] == [e.source_record_ids for e in b]


# ---------------------------------------------------------------------------
# Entry contents
# ---------------------------------------------------------------------------
def test_content_takes_feedback_from_the_latest_occurrence_not_a_concatenation() -> None:
    """Merging feedback across runs produces text no run ever produced, and a
    lesson nobody can trace back to an execution."""
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", created_at=T1, feedback="first"),
            _failure(run_id="r2", created_at=T2, feedback="latest"),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert written[0].content["latest_feedback"] == "latest"


def test_provenance_records_the_contributing_runs() -> None:
    memory, knowledge = _stores(
        [_failure(run_id="r1", created_at=T1), _failure(run_id="r2", created_at=T2)]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    assert written[0].content["run_ids"] == ["r1", "r2"]
    assert len(written[0].source_record_ids) == 2


def test_candidates_per_kind_must_be_positive() -> None:
    with pytest.raises(ValueError, match="candidates_per_kind must be positive"):
        RuleBasedConsolidator(candidates_per_kind=0)


def test_a_custom_signature_function_is_honoured() -> None:
    """Knowledge is one of the five per-agent axes; the MECHANISM stays
    shared, which is what the injection point is for."""
    memory, knowledge = _stores(
        [
            _failure(run_id="r1", failing_nodes=["fetch"]),
            _failure(run_id="r2", failing_nodes=["parse"]),
        ]
    )
    written = RuleBasedConsolidator(
        signature_fn=lambda r: "everything-is-one-lesson" if r.kind == "failure" else None
    ).consolidate(memory, knowledge, agent_id="a1")
    assert len(written) == 1
    assert written[0].occurrence_count == 2


# ---------------------------------------------------------------------------
# The helpful/harmful tally (ADR 0118, corrected by ADR 0126)
# ---------------------------------------------------------------------------
def _shown(record: MemoryRecord, signatures: list[str]) -> MemoryRecord:
    """The same record, with `retrieved_signatures` — what `make_reflect_node`
    writes when the retrieve node put those lessons in context."""
    content = dict(record.content)
    content["retrieved_signatures"] = signatures
    return dataclasses.replace(record, content=content)


def test_a_success_lesson_is_never_tallied() -> None:
    """A success entry keeps (0, 0). Reproduced end-to-end before the fix: four
    identical clean runs left `success:<objective>` at harmful=2, because every
    run that repeats a success re-produces its signature and equality read that
    as 'the lesson failed to prevent it'."""
    signature = "success:settle the invoice"
    memory, knowledge = _stores(
        [
            _success(run_id="s0", created_at=T1),
            _success(run_id="s1", created_at=T1),
            _shown(_success(run_id="s2", created_at=T2), [signature]),
            _shown(_success(run_id="s3", created_at=T3), [signature]),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    entry = next(e for e in written if e.signature == signature)
    assert entry.occurrence_count == 4
    assert (entry.helpful, entry.harmful) == (0, 0)


def test_a_chained_failure_reproduces_the_lesson_it_was_shown() -> None:
    """`failure:fetch` in context and the run fails `fetch` -> `parse`: the
    fetch failure recurred, so the lesson is harmful. Before the fix the
    produced signature `failure:fetch>parse` was a different string and the
    lesson was credited as helpful for the very failure it did not prevent."""
    memory, knowledge = _stores(
        [
            _failure(run_id="f0", failing_nodes=["fetch"], created_at=T1),
            _failure(run_id="f1", failing_nodes=["fetch"], created_at=T1),
            _shown(
                _failure(run_id="f2", failing_nodes=["fetch", "parse"], created_at=T2),
                ["failure:fetch"],
            ),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    entry = next(e for e in written if e.signature == "failure:fetch")
    assert (entry.helpful, entry.harmful) == (0, 1)


def test_a_downstream_node_counts_as_a_recurrence_of_its_own_lesson() -> None:
    """`failure:parse` recurs inside `failure:fetch>parse` — the parse failure
    did happen — so the lesson that was shown is harmful."""
    memory, knowledge = _stores(
        [
            _failure(run_id="p0", failing_nodes=["parse"], created_at=T1),
            _failure(run_id="p1", failing_nodes=["parse"], created_at=T1),
            _shown(
                _failure(run_id="p2", failing_nodes=["fetch", "parse"], created_at=T2),
                ["failure:parse"],
            ),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    entry = next(e for e in written if e.signature == "failure:parse")
    assert (entry.helpful, entry.harmful) == (0, 1)


def test_a_reordered_chain_is_a_different_failure_and_is_not_a_recurrence() -> None:
    """The rule is SUBSEQUENCE, not set membership. `default_signature` states
    that `A>B` and `B>A` are different failures — a run shown `fetch>parse`
    that instead failed `parse>fetch` did not reproduce the lesson, and a set
    subset would have said it did."""
    memory, knowledge = _stores(
        [
            _failure(run_id="q0", failing_nodes=["fetch", "parse"], created_at=T1),
            _failure(run_id="q1", failing_nodes=["fetch", "parse"], created_at=T1),
            _shown(
                _failure(run_id="q2", failing_nodes=["parse", "fetch"], created_at=T2),
                ["failure:fetch>parse"],
            ),
        ]
    )
    written = RuleBasedConsolidator().consolidate(memory, knowledge, agent_id="a1")
    entry = next(e for e in written if e.signature == "failure:fetch>parse")
    assert (entry.helpful, entry.harmful) == (1, 0)
