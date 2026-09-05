"""The summary agent's prompt, before and after ADR 0155 wired retrieval in.

Two properties, and the first is the one that keeps the corpus replayable:

1. **With nothing retrieved the prompt is byte-identical to the one recorded
   before this change.** The golden below is the literal string
   `draft_prompt` returned at commit `7a02f12`. Every cassette in `corpus/`
   was recorded against it; a single changed byte turns every hit into a miss
   and `aef loop score` reports 0.0 on the whole split (ADR 0123).

2. **With something retrieved the lesson reaches the model.** Until ADR 0155
   it did not: `make_retrieve_node` wrote `state.retrieved_context` and
   `draft_node` built its prompt from `working_memory` alone, so arms (a),
   (b) and (c) of ADR 0110's A/B produced one identical prompt SHA-256.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from aef.kernel.contracts import Context
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider
from aef.services.runtime import agent_services
from aef.state import AEFState
from agents.summary.graph import draft_node, draft_prompt

# The exact bytes `draft_prompt("The mill burned in 1842.", 40, ["mill", "1842"])`
# returned before ADR 0155. Written out rather than computed, because a golden
# derived from the code under test asserts nothing.
GOLDEN_NO_LESSONS = (
    "Summarise the passage below in at most 40 words.\n"
    "The summary must mention each of these terms, spelled exactly as given: mill, 1842.\n"
    "\n"
    "Passage:\n"
    "The mill burned in 1842."
)


def test_the_prompt_is_byte_identical_when_nothing_was_retrieved() -> None:
    assert draft_prompt("The mill burned in 1842.", 40, ["mill", "1842"]) == GOLDEN_NO_LESSONS


def test_the_default_lessons_argument_is_the_no_lessons_case() -> None:
    """A caller that has not been updated gets the old bytes. This is what
    lets `render_retrieved_context` be appended unconditionally."""
    explicit = draft_prompt("The mill burned in 1842.", 40, ["mill", "1842"], "")
    assert explicit == GOLDEN_NO_LESSONS


def test_a_lesson_is_added_before_the_passage_and_after_the_instructions() -> None:
    block = "Lessons:\n- do not drop the year"
    out = draft_prompt("The mill burned in 1842.", 40, ["mill"], block)
    assert block in out
    assert out.index(block) < out.index("Passage:")
    assert out.index("at most 40 words") < out.index(block)
    # Everything the golden asserted is still there, in order.
    assert out.startswith("Summarise the passage below in at most 40 words.\n")
    assert out.endswith("Passage:\nThe mill burned in 1842.")


class _Recorder(ModelProvider):
    name = "recorder"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def default_model(self) -> str | None:
        return "fake"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.prompts.append("\n".join(m.content for m in request.messages if m.role == "user"))
        return CompletionResult(content="a summary", model="fake", input_tokens=1, output_tokens=1)


def _run_draft(chunks: list[dict[str, object]]) -> str:
    provider = _Recorder()
    state = AEFState(
        run_id="r1",
        agent_id="summary_agent",
        objective="summarise",
        working_memory={"text": "The mill burned in 1842.", "max_words": 40, "must_mention": []},
        retrieved_context=chunks,
    )
    ctx = Context(
        run_id="r1",
        graph_version="0.1.0",
        trace_id="t",
        node_id="draft",
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    draft_node(state, ctx, agent_services(model_provider=provider, agent_id="summary_agent"))
    return provider.prompts[0]


def test_the_draft_node_puts_a_retrieved_lesson_in_front_of_the_model() -> None:
    """The ADR 0155 defect, as a regression test: this assertion fails on the
    pre-0155 `draft_node`, which never read `retrieved_context`."""
    chunk = {
        "content": json.dumps({"latest_feedback": "you dropped the year"}, sort_keys=True),
        "source": "knowledge:failure:failure:draft",
        "relevance_score": 0.9,
        "token_estimate": 10,
        "metadata": {"kind": "failure", "signature": "failure:draft"},
    }
    prompt = _run_draft([chunk])
    assert "you dropped the year" in prompt
    assert "failure:draft" in prompt


def test_the_draft_nodes_prompt_is_unchanged_when_nothing_was_retrieved() -> None:
    prompt = _run_draft([])
    assert prompt == draft_prompt("The mill burned in 1842.", 40, [])
    assert "Lessons" not in prompt
