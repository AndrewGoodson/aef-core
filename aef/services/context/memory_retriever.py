"""`MemoryRetriever` — the smallest REAL `Retriever`, and the first thing in
this repo that enforces `AEFState.context_budget_tokens`.

Milestone 3's triage (ADR 0101) kept one of the five Phase-2/3 interfaces and
deleted the rest. This is that one, and the reason it survived is not that
retrieval is interesting: it is that **a token budget nobody enforces is the
same defect as an injection point nobody calls.** `context_budget_tokens` has
shipped since Phase 0 with a default of 8000, is carried faithfully through
every `StateDelta`, and no code has ever read it to bound anything.

What it does: rank a node's failure/success memory against a query, then
admit chunks in rank order until the next one would not fit. Deterministic —
no model, no embedding — because the loop replays deterministic nodes and
asserts their output matches (constraint #1), so a retriever a node can call
during a replayed run must produce the same answer twice.

**Scoring is lexical overlap, and that is stated rather than dressed up.** It
is a real ranking with a real failure mode: a query sharing no vocabulary with
a relevant record ranks it last. An embedding-backed retriever belongs behind
this same interface, which is what the interface is for; what it must not do
is arrive without anything having ever exercised the contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from aef.services.context.base import RetrievedChunk, Retriever
from aef.services.memory.base import MemoryKind, MemoryStore

# The kinds a retriever draws on by default: what went wrong before, and what
# went right. Deliberately not `working` (this run's own scratch, which the
# node already has) and not `semantic` (temporal validity is a KG concern, and
# ADR 0101 records why no knowledge graph is wired).
DEFAULT_KINDS: tuple[MemoryKind, ...] = ("failure", "success")

# Characters per token. A crude estimate, and crude on purpose: a real
# tokenizer is provider-specific, and importing one here would put a vendor
# dependency in `aef/services/` outside an adapter, which constraint #3
# forbids. Named and testable rather than buried, and deliberately an
# OVER-estimate on average so the budget binds early rather than late — a
# retriever that overshoots a budget it claims to enforce is worse than one
# that admits one chunk fewer.
CHARS_PER_TOKEN = 4

_WORD = re.compile(r"[a-z0-9_]+")


def estimate_tokens(text: str) -> int:
    """Chunk size in tokens, rounded UP. A chunk never costs zero: a
    zero-cost chunk would let an unbounded number through a finite budget."""
    return max(1, -(-len(text) // CHARS_PER_TOKEN))


def _terms(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _render(content: dict[str, object]) -> str:
    """Record content as text a node can read.

    `sort_keys` because the ordering of a dict built by a node is not a
    property any test should depend on, and because a chunk whose text
    changes between two identical runs would break replay for any
    deterministic node that retrieved it.
    """
    return json.dumps(content, sort_keys=True, default=str)


@dataclass(frozen=True)
class MemoryRetriever(Retriever):
    """Retrieve -> rank -> prune, bounded by `token_budget`.

    No compression and no summarisation: both need a model, and a "compressor"
    that truncates is a lossy edit wearing the word compression. Report §13's
    rule — never optimise for fewer tokens as an end in itself — is honoured
    by pruning whole chunks rather than damaging them.
    """

    memory: MemoryStore

    # REQUIRED, and explicitly so. Found by this milestone's adversarial
    # round: with a default of `None` this read every agent's memory, so a
    # retriever built without thinking about it handed one agent another's
    # recorded failures. `None` is still expressible and still means "all
    # agents" — what changed is that it must be CHOSEN. Deny-by-default is
    # the discipline everywhere else in this repo (constraint #6); a
    # convenience default that widens scope is the one place it was not.
    agent_id: str | None

    kinds: tuple[MemoryKind, ...] = DEFAULT_KINDS
    # Per-kind read depth before ranking.
    #
    # This BOUNDS THE ANSWER, not just the work, and the first draft of this
    # comment claimed the opposite. The store returns most-recent-first, so a
    # highly relevant record at position 51 is never scored and can never be
    # returned. That is a real ceiling on recall and it is stated here rather
    # than discovered later — the same class of error as three ADRs in this
    # program: a true statement about one property offered as an answer about
    # a different one.
    candidates_per_kind: int = 50
    # An owner-set CEILING, from `context.token_budget`. A node asking for
    # more gets the ceiling, silently in the sense that it is not an error —
    # a node is entitled to ask, and the owner is entitled to decide. Without
    # this the config field would be one nothing reads, which is the defect
    # this whole milestone exists to remove (ADR 0101).
    max_token_budget: int | None = None

    def __post_init__(self) -> None:
        if self.candidates_per_kind <= 0:
            raise ValueError(
                f"candidates_per_kind must be positive; got {self.candidates_per_kind}"
            )
        if self.max_token_budget is not None and self.max_token_budget <= 0:
            raise ValueError(f"max_token_budget must be positive; got {self.max_token_budget}")

    def retrieve(self, query: str, *, token_budget: int) -> list[RetrievedChunk]:
        if token_budget <= 0:
            # Not an empty list quietly: a caller asking for a non-positive
            # budget has a bug, and returning nothing would let it read as
            # "there was nothing to retrieve".
            raise ValueError(
                f"token_budget must be positive; got {token_budget}. A zero budget cannot "
                f"admit any chunk, so an empty result would be indistinguishable from an "
                f"empty memory."
            )

        if self.max_token_budget is not None:
            token_budget = min(token_budget, self.max_token_budget)

        query_terms = _terms(query)
        scored: list[tuple[float, str, RetrievedChunk]] = []
        for kind in self.kinds:
            for record in self.memory.query(
                kind, agent_id=self.agent_id, limit=self.candidates_per_kind
            ):
                text = _render(record.content)
                score = self._score(query_terms, text)
                if score <= 0.0:
                    continue
                scored.append(
                    (
                        score,
                        record.id,
                        RetrievedChunk(
                            content=text,
                            source=f"memory:{kind}:{record.id}",
                            relevance_score=score,
                            token_estimate=estimate_tokens(text),
                            metadata={"kind": kind, "record_id": record.id},
                        ),
                    )
                )

        # Highest score first, ties broken by record id. A stable total order
        # rather than whatever the store happened to return: two runs of the
        # same node must retrieve the same context in the same order or
        # `ReplayEngine` reports a determinism violation that is really a
        # sort-order artefact.
        scored.sort(key=lambda item: (-item[0], item[1]))

        admitted: list[RetrievedChunk] = []
        spent = 0
        for _, _, chunk in scored:
            if spent + chunk.token_estimate > token_budget:
                # Prune, do not stop: a large low-ranked chunk must not block
                # a small one behind it. Skipping keeps the budget's meaning
                # ("fit as much of the best as fits") rather than turning it
                # into "stop at the first thing too big".
                continue
            admitted.append(chunk)
            spent += chunk.token_estimate
        return admitted

    @staticmethod
    def _score(query_terms: set[str], text: str) -> float:
        """Jaccard overlap between query and chunk vocabulary.

        Jaccard rather than raw overlap count, so a long record does not
        outrank a precisely matching short one purely by containing more
        words.
        """
        if not query_terms:
            return 0.0
        chunk_terms = _terms(text)
        if not chunk_terms:
            return 0.0
        shared = query_terms & chunk_terms
        if not shared:
            return 0.0
        return len(shared) / len(query_terms | chunk_terms)
