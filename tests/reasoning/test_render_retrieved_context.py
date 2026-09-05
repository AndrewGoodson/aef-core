"""`render_retrieved_context` — the reader ADR 0118's writer never had.

ADR 0118 wired `make_retrieve_node`, which writes chunks to
`state.retrieved_context`. Nothing in the package then read them back into a
prompt, so retrieval could not change a run's behaviour (ADR 0155). These
tests pin the renderer: what it extracts, what it labels, what it refuses to
do, and — the load-bearing one — that it returns the empty string when there
is nothing, because a caller appending it unconditionally must otherwise
change every prompt it has ever recorded.
"""

from __future__ import annotations

import json

import pytest

from aef.reasoning.nodes import LESSON_HEADER, render_retrieved_context
from aef.state import AEFState


def _state(chunks: list[dict[str, object]]) -> AEFState:
    return AEFState(run_id="r1", agent_id="summary_agent", objective="o", retrieved_context=chunks)


def _memory_chunk(feedback: str, *, kind: str = "failure", record_id: str = "rec1") -> dict:
    return {
        "content": json.dumps({"verbal_feedback": feedback, "score": 0.5}, sort_keys=True),
        "source": f"memory:{kind}:{record_id}",
        "relevance_score": 0.4,
        "token_estimate": 12,
        "metadata": {"kind": kind, "record_id": record_id},
    }


def _knowledge_chunk(feedback: str, *, signature: str = "failure:draft") -> dict:
    return {
        "content": json.dumps(
            {"latest_feedback": feedback, "signature": signature, "run_ids": ["a", "b"]},
            sort_keys=True,
        ),
        "source": f"knowledge:failure:{signature}",
        "relevance_score": 0.6,
        "token_estimate": 20,
        "metadata": {"kind": "failure", "signature": signature, "occurrence_count": 2},
    }


def test_nothing_retrieved_renders_the_empty_string() -> None:
    """The contract the cassettes depend on. Not a header with no bullets."""
    assert render_retrieved_context(_state([])) == ""


def test_a_raw_record_renders_its_verbal_feedback() -> None:
    out = render_retrieved_context(_state([_memory_chunk("the summary omitted 'cider'")]))
    assert out.startswith(LESSON_HEADER)
    assert "the summary omitted 'cider'" in out
    # The surrounding JSON is NOT pasted in when a known key was found.
    assert "verbal_feedback" not in out
    assert "score" not in out


def test_a_consolidated_entry_renders_its_feedback_and_signature() -> None:
    out = render_retrieved_context(_state([_knowledge_chunk("draft keeps dropping terms")]))
    assert "draft keeps dropping terms" in out
    assert "[failure:draft]" in out, "provenance must travel with the lesson"


def test_the_summariser_prose_wins_over_the_verbatim_feedback() -> None:
    """`_LESSON_TEXT_KEYS` order, pinned: the ADR 0110 summariser writes
    `summary` alongside — never instead of — `latest_feedback`, so a renderer
    that preferred the verbatim text would make the summariser unobservable."""
    chunk = {
        "content": json.dumps(
            {"summary": "SUMMARY TEXT", "latest_feedback": "VERBATIM TEXT"}, sort_keys=True
        ),
        "source": "knowledge:failure:sig",
        "metadata": {"kind": "failure", "signature": "sig"},
    }
    out = render_retrieved_context(_state([chunk]))
    assert "SUMMARY TEXT" in out
    assert "VERBATIM TEXT" not in out


def test_an_unreadable_chunk_degrades_to_its_raw_text_rather_than_vanishing() -> None:
    chunk = {"content": "not json at all", "source": "memory:failure:x", "metadata": {}}
    out = render_retrieved_context(_state([chunk]))
    assert "not json at all" in out


def test_a_chunk_with_no_content_is_skipped_entirely() -> None:
    chunk = {"content": "   ", "source": "memory:failure:x", "metadata": {"kind": "failure"}}
    assert render_retrieved_context(_state([chunk])) == ""


def test_newlines_in_a_lesson_are_collapsed_to_one_line() -> None:
    """A lesson containing a newline would break the bullet list, and the
    fragment after the break reads to a model as an instruction of its own."""
    out = render_retrieved_context(_state([_memory_chunk("line one\n- do something else")]))
    bullets = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(bullets) == 1
    assert "line one - do something else" in bullets[0]


def test_max_items_caps_the_bullets_most_relevant_first() -> None:
    chunks = [_memory_chunk(f"lesson {i}", record_id=f"rec{i}") for i in range(5)]
    out = render_retrieved_context(_state(chunks), max_items=2)
    assert out.count("\n- ") == 2
    assert "lesson 0" in out and "lesson 1" in out
    assert "lesson 2" not in out


def test_max_items_zero_renders_nothing() -> None:
    assert render_retrieved_context(_state([_memory_chunk("x")]), max_items=0) == ""


def test_a_negative_cap_is_refused_rather_than_silently_empty() -> None:
    with pytest.raises(ValueError, match="max_items must be non-negative"):
        render_retrieved_context(_state([]), max_items=-1)


def test_a_very_long_lesson_is_bounded() -> None:
    out = render_retrieved_context(_state([_memory_chunk("x" * 5000)]))
    assert len(out) < 1200, "one unbounded blob would swamp the prompt it informs"


def test_the_renderer_is_deterministic_and_reads_only_state() -> None:
    """Safe inside a `deterministic=True` node: two calls on the same state
    must be byte-identical, or `ReplayEngine` reports a violation that is
    really a rendering artefact."""
    state = _state([_knowledge_chunk("a"), _memory_chunk("b")])
    assert render_retrieved_context(state) == render_retrieved_context(state)
