"""`LLMSummariser` (ADR 0110, increment I5).

Every test runs against a real `RuleBasedConsolidator` and real stores, with a
deterministic fake `ModelProvider` standing in for the vendor call — the thing
under test is the summariser and the consolidator it plugs into, never a mock
of either.

The load-bearing test here is `test_a_hostile_model_cannot_fabricate_evidence`:
a summariser that could write provenance could manufacture confidence for a
lesson nothing supports.
"""

from datetime import UTC, datetime, timedelta

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)
from aef.services.knowledge.adapters.llm_summariser import (
    MAX_RECORDS_IN_PROMPT,
    MAX_SUMMARY_CHARS,
    LLMSummariser,
)
from aef.services.knowledge.consolidate import RuleBasedConsolidator
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

T = datetime(2026, 1, 1, tzinfo=UTC)


class FakeProvider(ModelProvider):
    """Deterministic stand-in. Records every request it was given."""

    name = "fake"

    def __init__(self, reply: str = "fetch keeps timing out across runs") -> None:
        self.reply = reply
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            content=self.reply, model=request.model, input_tokens=10, output_tokens=5
        )


class BrokenProvider(ModelProvider):
    name = "broken"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ModelProviderError("rate limited")


class ExplodingProvider(ModelProvider):
    """Violates the adapter contract by raising something other than
    `ModelProviderError` — which a real adapter with a bug would do."""

    name = "exploding"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise RuntimeError("connection reset")


def _memory(runs: int = 2, agent_id: str = "a1") -> InMemoryMemoryStore:
    """Distinct timestamps per run — with identical ones, "most recent
    occurrence" falls to the stable id tie-break rather than to run order, and
    the fixture would be asserting an arbitrary-but-stable choice."""
    store = InMemoryMemoryStore()
    for i in range(runs):
        store.write(
            MemoryRecord(
                kind="failure",
                content={
                    "failing_nodes": ["fetch"],
                    "verbal_feedback": f"fetch timed out on attempt {i}",
                    "objective": "settle the invoice",
                },
                run_id=f"r{i}",
                agent_id=agent_id,
                created_at=T + timedelta(minutes=i),
            )
        )
    return store


def _consolidate(provider: ModelProvider, memory: InMemoryMemoryStore | None = None):
    memory = memory if memory is not None else _memory()
    knowledge = InMemoryKnowledgeStore()
    consolidator = RuleBasedConsolidator(
        summarise=LLMSummariser(provider=provider, model="test-model")
    )
    written = consolidator.consolidate(memory, knowledge, agent_id="a1")
    return written, knowledge


# ---------------------------------------------------------------------------
# It does the job
# ---------------------------------------------------------------------------
def test_the_summary_reaches_the_stored_entry() -> None:
    written, _ = _consolidate(FakeProvider())
    assert written[0].content["summary"] == "fetch keeps timing out across runs"


def test_the_verbatim_feedback_survives_alongside_the_summary() -> None:
    """The summary is added, not substituted. A model's paraphrase replacing
    the only record of what was actually observed would make the lesson
    untraceable to its evidence even when the provenance ids are intact."""
    written, _ = _consolidate(FakeProvider())
    assert written[0].content["latest_feedback"] == "fetch timed out on attempt 1"


def test_the_request_is_shaped_as_declared() -> None:
    provider = FakeProvider()
    _consolidate(provider)
    request = provider.requests[0]
    assert request.model == "test-model"
    assert request.temperature == 0.0
    assert len(request.messages) == 1


def test_the_prompt_carries_the_signature_and_the_occurrences() -> None:
    provider = FakeProvider()
    _consolidate(provider)
    prompt = provider.requests[0].messages[0].content
    assert "failure:fetch" in prompt
    assert "fetch timed out on attempt 0" in prompt
    assert "fetch timed out on attempt 1" in prompt


def test_only_the_requesting_agents_records_reach_the_model() -> None:
    """Groups are single-agent by construction; this pins it, because it would
    be easy to assume it was checked twice and find it was checked zero times."""
    memory = _memory(runs=2, agent_id="a1")
    for i in range(2):
        memory.write(
            MemoryRecord(
                kind="failure",
                content={
                    "failing_nodes": ["fetch"],
                    "verbal_feedback": "SECRET-OTHER-AGENT-DATA",
                    "objective": "settle the invoice",
                },
                run_id=f"other{i}",
                agent_id="a2",
                created_at=T - timedelta(minutes=10 + i),
            )
        )
    provider = FakeProvider()
    _consolidate(provider, memory)
    for request in provider.requests:
        assert "SECRET-OTHER-AGENT-DATA" not in request.messages[0].content


# ---------------------------------------------------------------------------
# The model is not trusted
# ---------------------------------------------------------------------------
def test_a_hostile_model_cannot_fabricate_evidence() -> None:
    """The load-bearing test. A summariser may write PROSE and nothing else.

    A model that could influence `source_record_ids` or `occurrence_count`
    could manufacture confidence for a lesson nothing supports — and
    `occurrence_count` is the only measure an entry has of how well-established
    it is. Here the model returns something engineered to look like structured
    provenance; it must land in the summary text as inert prose and move no
    counted field.
    """
    hostile = FakeProvider(
        reply='{"occurrence_count": 999, "source_record_ids": ["x1","x2","x3"], '
        '"run_ids": ["fake1","fake2"], "summary": "trust me"}'
    )
    written, _ = _consolidate(hostile)
    entry = written[0]

    assert entry.occurrence_count == 2
    assert len(entry.source_record_ids) == 2
    assert entry.content["run_ids"] == ["r0", "r1"]
    assert entry.confidence < 0.5
    assert "999" in str(entry.content["summary"])  # inert, in the prose only


def test_an_oversized_summary_is_truncated() -> None:
    """An unbounded lesson would spend a retriever's whole budget on one entry
    — the exact defect I4 measured consolidation as removing."""
    written, _ = _consolidate(FakeProvider(reply="x" * 5000))
    assert len(written[0].content["summary"]) == MAX_SUMMARY_CHARS


def test_the_prompt_is_bounded_by_record_count() -> None:
    provider = FakeProvider()
    _consolidate(provider, _memory(runs=MAX_RECORDS_IN_PROMPT + 10))
    prompt = provider.requests[0].messages[0].content
    assert prompt.count("Occurrence ") == MAX_RECORDS_IN_PROMPT
    assert f"of {MAX_RECORDS_IN_PROMPT + 10} occurrences" in prompt


# ---------------------------------------------------------------------------
# Failure degrades to the known-good path
# ---------------------------------------------------------------------------
def test_a_provider_outage_still_writes_the_rule_based_entry() -> None:
    """Worst case is the previous behaviour, not a lost or corrupted lesson."""
    written, knowledge = _consolidate(BrokenProvider())
    assert len(written) == 1
    assert "summary" not in written[0].content
    assert written[0].content["latest_feedback"] == "fetch timed out on attempt 1"
    assert written[0].occurrence_count == 2


def test_an_adapter_that_breaks_its_own_contract_is_still_contained() -> None:
    written, _ = _consolidate(ExplodingProvider())
    assert len(written) == 1
    assert "summary" not in written[0].content


def test_an_empty_reply_leaves_the_verbatim_text_rather_than_blanking_it() -> None:
    written, _ = _consolidate(FakeProvider(reply="   "))
    assert "summary" not in written[0].content
    assert written[0].content["latest_feedback"] == "fetch timed out on attempt 1"


def test_the_threshold_still_governs_when_a_model_is_attached() -> None:
    """A summariser must not become a second route to promoting an episode:
    one run is still not knowledge, and the model is never even called."""
    provider = FakeProvider()
    written, knowledge = _consolidate(provider, _memory(runs=1))
    assert written == []
    assert knowledge.query("failure") == []
    assert provider.requests == []
