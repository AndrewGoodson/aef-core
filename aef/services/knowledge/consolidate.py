"""`RuleBasedConsolidator` — the first real producer for `KnowledgeStore`, and
the middle step of WikiSkill's loop (arXiv:2608.27454): experience in,
consolidated knowledge out.

Rule-based, for the reason `RuleBasedCritic` was (ADR 0046): no LLM, no vendor
SDK, no clock read. Everything is computed from records already written by
`make_reflect_node`, which makes it testable against hand-built adversarial
records rather than only against a live model. An LLM-backed consolidator is
I5, and it changes nothing about this interface.

**Stateless recompute, deliberately.** This reads the memory store, groups, and
emits — it keeps no cursor and no "already consolidated" marker. Re-running
over an unchanged store therefore produces the same entries with the same
provenance, which the store's order-preserving dedupe absorbs into no change at
all. A cursor would be a second source of truth about what has been seen, and
ADR 0091's finding is that two records of one fact drift.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aef.services.knowledge.base import KnowledgeEntry, KnowledgeKind, KnowledgeStore
from aef.services.memory.base import MemoryRecord, MemoryStore

# A signature is a stable, derived identity for "the same thing going wrong
# again". `None` means THIS RECORD CANNOT BE SIGNED and must be dropped —
# never bucketed into a catch-all, which would merge unrelated failures into
# one entry and manufacture a lesson nobody learned.
SignatureFn = Callable[[MemoryRecord], str | None]

# Produces the human-readable lesson text for one group of records. Injected
# rather than branched on, so the LLM-backed variant (I5) swaps ONLY the prose
# and inherits the grouping, the two-run threshold, the per-run dedupe and the
# agent keying — all of which I4 measured. One code path, one set of rules.
SummariseFn = Callable[[str, list[MemoryRecord]], str | None]

# Records read per kind before grouping. This BOUNDS THE ANSWER, not just the
# work: the store returns most-recent-first, so a failure whose earlier
# occurrences sit past this depth consolidates with a lower count than it has
# earned. Stated here rather than discovered later — the same disclosure
# `MemoryRetriever.candidates_per_kind` carries.
DEFAULT_CANDIDATES_PER_KIND = 500

# Distinct RUNS a signature must appear in before it is knowledge. Two, because
# one is an episode. See `_representatives_by_run` for why runs and not records.
DEFAULT_MIN_OCCURRENCES = 2

_EPOCH = datetime.min.replace(tzinfo=UTC)


def default_signature(record: MemoryRecord) -> str | None:
    """`(kind, failing_nodes)` for failures, `(kind, objective)` for successes.

    `failing_nodes` is the key because ADR 0096 established it as the field a
    structural proposer cannot begin without — *"add a fallback to the flaky
    node" requires knowing which node was flaky* — and `make_reflect_node`
    records it for exactly that reason.

    Returns `None` when the record carries nothing stable to key on. A failure
    with no recorded failing node is unattributable, and the precedent for
    what to do about that is already in this repo: `_failing_nodes` skips
    errors whose origin was not recorded, because guessing is worse than
    omitting.

    `content` is `dict[str, Any]` and nothing constrains its shape, so every
    read here is defensive by necessity, not by superstition.
    """
    if record.kind == "failure":
        raw = record.content.get("failing_nodes")
        if not isinstance(raw, (list, tuple)):
            return None
        nodes = [n for n in raw if isinstance(n, str) and n]
        if not nodes:
            return None
        # Order preserved, not sorted: `_failing_nodes` keeps first-seen order
        # because the first failure is usually the cause and the rest are
        # consequences. A->B and B->A are different failures.
        return "failure:" + ">".join(nodes)

    if record.kind == "success":
        objective = record.content.get("objective")
        if not isinstance(objective, str) or not objective:
            return None
        return "success:" + objective

    return None


@dataclass(frozen=True)
class RuleBasedConsolidator:
    """Group records into `KnowledgeEntry`s and upsert them.

    Deterministic given the same store contents: no clock read (times come
    from `MemoryRecord.created_at`), no randomness, and every ordering is a
    stable total order.
    """

    signature_fn: SignatureFn = default_signature
    # `None` keeps the entry's text as the most recent occurrence's feedback,
    # verbatim. Anything else may only produce PROSE — see `_build_entry`,
    # where every provenance field is computed from the records and none is
    # taken from the summariser.
    summarise: SummariseFn | None = None
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES
    candidates_per_kind: int = DEFAULT_CANDIDATES_PER_KIND
    kinds: tuple[KnowledgeKind, ...] = ("failure", "success")

    def __post_init__(self) -> None:
        if self.min_occurrences < 2:
            raise ValueError(
                f"min_occurrences must be at least 2; got {self.min_occurrences}. A "
                f"threshold of 1 promotes every one-off episode to knowledge, which is "
                f"the failure this layer exists to avoid."
            )
        if self.candidates_per_kind <= 0:
            raise ValueError(
                f"candidates_per_kind must be positive; got {self.candidates_per_kind}"
            )

    def consolidate(
        self,
        memory: MemoryStore,
        knowledge: KnowledgeStore,
        *,
        agent_id: str | None,
    ) -> list[KnowledgeEntry]:
        """Read `memory`, upsert everything at or above threshold into
        `knowledge`, and return the entries written (newest last-seen first).

        `agent_id` is REQUIRED and has no default, matching
        `MemoryRetriever.agent_id` — a default of "every agent" was found by an
        adversarial round to hand one agent another's recorded failures.
        Passing `None` genuinely means "all agents" and stays safe here
        regardless, because grouping keys on each record's OWN `agent_id`; it
        reads across agents, it never merges across them.
        """
        groups: dict[tuple[str | None, str], list[MemoryRecord]] = {}
        # Every run this agent has recorded, by its latest record time. This is
        # what "runs since last seen" is counted against (ADR 0116): a lesson
        # that has stopped recurring while the agent keeps running is stale,
        # and the retriever demotes it rather than this layer deleting it.
        runs_seen: dict[tuple[str | None, str], datetime] = {}
        for kind in self.kinds:
            for record in memory.query(kind, agent_id=agent_id, limit=self.candidates_per_kind):
                if record.run_id and record.created_at is not None:
                    key = (record.agent_id, record.run_id)
                    runs_seen[key] = max(runs_seen.get(key, _EPOCH), record.created_at)
                signature = self.signature_fn(record)
                if signature is None:
                    continue
                groups.setdefault((record.agent_id, signature), []).append(record)

        written: list[KnowledgeEntry] = []
        for (record_agent_id, signature), records in groups.items():
            representatives = _representatives_by_run(records)
            if len(representatives) < self.min_occurrences:
                continue
            entry = _build_entry(signature, record_agent_id, representatives, self.summarise)
            entry = dataclasses.replace(
                entry,
                runs_since_last_seen=_runs_since(entry.last_seen, record_agent_id, runs_seen),
            )
            written.append(knowledge.upsert(entry))

        written.sort(key=lambda e: (_sort_ts(e.last_seen), e.signature), reverse=True)
        return written


def _representatives_by_run(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """At most ONE record per run, most recent within that run.

    This is what makes `occurrence_count` mean "recurred". A graph may reflect
    more than once in a single run — `make_reflect_node`'s idempotency key is
    keyed on `checkpoint_seq` precisely because successive reflections within
    one run are expected — so counting records would let one bad run report
    itself as a well-established pattern. It is the same class of defect as
    counting a re-consolidated record twice, which the store already refuses.

    Records with no `run_id` are DROPPED: a record that cannot be attributed
    to a run cannot be evidence that something recurred ACROSS runs, and
    inventing a run for it would be the guess this repo's precedent forbids.
    """
    by_run: dict[str, MemoryRecord] = {}
    for record in records:
        if not record.run_id:
            continue
        incumbent = by_run.get(record.run_id)
        if incumbent is None or _rank(record) > _rank(incumbent):
            by_run[record.run_id] = record
    return sorted(by_run.values(), key=_rank)


def _build_entry(
    signature: str,
    agent_id: str | None,
    representatives: list[MemoryRecord],
    summarise: SummariseFn | None = None,
) -> KnowledgeEntry:
    """`representatives` is already sorted oldest-first by `_rank`."""
    newest = representatives[-1]
    kind: KnowledgeKind = "failure" if newest.kind == "failure" else "success"

    content: dict[str, object] = {
        "signature": signature,
        # From the most recent occurrence, not a merge of all of them:
        # concatenating feedback across runs produces text no run ever
        # produced, and a lesson nobody can trace to an execution.
        "latest_feedback": newest.content.get("verbal_feedback"),
        "objective": newest.content.get("objective"),
        "run_ids": [r.run_id for r in representatives],
    }

    # The ONLY field a summariser may influence. Everything above and below is
    # computed from the records: a summariser that could write `run_ids` or
    # `source_record_ids` could fabricate evidence for its own lesson, and an
    # entry's occurrence count is the sole measure of how well-established it
    # is. A summariser returning None or empty leaves the verbatim feedback in
    # place rather than blanking it.
    if summarise is not None:
        summary = summarise(signature, representatives)
        if summary:
            content["summary"] = summary
    failing_nodes = newest.content.get("failing_nodes")
    if isinstance(failing_nodes, (list, tuple)):
        content["failing_nodes"] = [n for n in failing_nodes if isinstance(n, str)]

    timestamps = [r.created_at for r in representatives if r.created_at is not None]
    return KnowledgeEntry(
        signature=signature,
        kind=kind,
        content=content,
        agent_id=agent_id,
        source_record_ids=tuple(r.id for r in representatives),
        first_seen=min(timestamps) if timestamps else None,
        last_seen=max(timestamps) if timestamps else None,
        tags=newest.tags,
    )


def _runs_since(
    last_seen: datetime | None,
    agent_id: str | None,
    runs_seen: dict[tuple[str | None, str], datetime],
) -> int:
    """Distinct runs of THIS agent whose latest record is newer than the
    entry's last occurrence. Computed from the records every consolidation,
    never stored as a counter (ADR 0091: two records of one fact drift).
    Records without a run or a timestamp cannot be counted and are not
    guessed at; an entry with no `last_seen` has nothing to count from."""
    if last_seen is None:
        return 0
    return sum(
        1
        for (run_agent, _), latest in runs_seen.items()
        if run_agent == agent_id and latest > last_seen
    )


def _rank(record: MemoryRecord) -> tuple[datetime, str]:
    """Total order over records. Id breaks the tie so two records written in
    the same instant still order stably — an unstable order here would change
    which record is 'representative' between two identical consolidations."""
    return (_sort_ts(record.created_at), record.id)


def _sort_ts(value: datetime | None) -> datetime:
    return value if value is not None else _EPOCH
