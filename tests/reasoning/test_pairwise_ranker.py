"""`PairwiseRanker` — the first judge in this repo that ranks model outputs
against each other, and the self-preference guard the measurement earned
(ADR 0162).

A fake provider records every request and returns scripted replies; no
process, no network, no quota. What is pinned is what the model is NOT
trusted with — the tally, the position swap, and above all the fact that
neither candidate's authorship reaches the prompt — plus the guard itself,
which is the only new *refusal* in this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pytest

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)
from aef.reasoning.llm_reflection import (
    RANKER_SYSTEM,
    Candidate,
    PairwiseRanker,
    SelfRankingError,
)


@dataclass
class FakeProvider(ModelProvider):
    name = "fake"
    replies: list[str] = field(default_factory=list)
    requests: list[CompletionRequest] = field(default_factory=list)
    answered_by: str = "fake-model"
    fail: bool = False

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.fail:
            raise ModelProviderError("fake outage")
        reply = self.replies.pop(0) if self.replies else ""
        return CompletionResult(
            content=reply, model=self.answered_by, input_tokens=1, output_tokens=1
        )


OPUS = Candidate(label="incumbent", text="A short summary of the thing.", model="claude-opus-5")
HAIKU = Candidate(label="candidate", text="Another summary, differently put.", model="haiku-x")
TASK = "Summarise the passage below in at most 10 words."


def _ranker(provider: ModelProvider, **kwargs: object) -> PairwiseRanker:
    return PairwiseRanker(provider=provider, model="judge-model", **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the prompt is the one that was measured
# ---------------------------------------------------------------------------
def test_the_system_prompt_is_byte_identical_to_the_one_adr_0162_measured() -> None:
    """The 66 committed judgments in `docs/research/j4/rankings.jsonl` were
    issued by `run_j4_selfpref.py`'s own inline strings; this class was written
    afterwards and the two renderings were proved equal before the local copies
    were deleted. The hash keeps them equal — a judge prompt that drifts from
    the one the numbers were taken under makes the ADR's tables claims about
    code that no longer exists."""
    assert (
        hashlib.sha256(RANKER_SYSTEM.encode()).hexdigest()
        == "9a04e625894a066c7c7aa3f02791935ed559b19973ebd1df07143f9693501efb"
    )


def test_the_user_turn_is_the_measured_shape() -> None:
    prompt = _ranker(FakeProvider()).prompt(TASK, OPUS, HAIKU)
    assert prompt == (
        "Instructions given to both writers:\n"
        "Summarise the passage below in at most 10 words.\n\n"
        "Candidate A:\nA short summary of the thing.\n\n"
        "Candidate B:\nAnother summary, differently put.\n\n"
        "Which candidate better satisfies the instructions? "
        'Reply with JSON only, e.g. {"better": "A"}.'
    )


def test_neither_the_label_nor_the_writer_model_reaches_the_prompt() -> None:
    """The control is only a control if the judge cannot tell who wrote what.
    A caller labelling its candidates "incumbent"/"candidate" — which the loop
    does — would otherwise hand the judge the answer."""
    provider = FakeProvider(replies=['{"better": "A"}', '{"better": "B"}'])
    _ranker(provider).rank(TASK, OPUS, HAIKU)
    assert provider.requests
    for request in provider.requests:
        blob = "\n".join(m.content for m in request.messages)
        assert "incumbent" not in blob
        assert "claude-opus-5" not in blob
        assert "haiku-x" not in blob
        # The two candidates are named by POSITION and nothing else.
        assert "Candidate A:" in blob and "Candidate B:" in blob


# ---------------------------------------------------------------------------
# the self-preference guard
# ---------------------------------------------------------------------------
def test_a_judge_refuses_to_rank_its_own_models_output_before_spending_a_call() -> None:
    provider = FakeProvider(replies=['{"better": "A"}'])
    ranker = PairwiseRanker(provider=provider, model="claude-opus-5")
    with pytest.raises(SelfRankingError, match="wrote candidate 'incumbent'"):
        ranker.rank(TASK, OPUS, HAIKU)
    assert provider.requests == [], "the guard must fire before the call, not after it"


def test_the_guard_sees_through_a_context_window_suffix() -> None:
    """`claude-opus-5[1m]` and `claude-opus-5` are one model. A guard that
    missed that would be defeated by how the name happened to be written —
    and the harness CLI writes it both ways (ADR 0169)."""
    ranker = PairwiseRanker(provider=FakeProvider(), model="claude-opus-5[1m]")
    with pytest.raises(SelfRankingError):
        ranker.rank(TASK, OPUS, HAIKU)


def test_the_guard_fires_on_the_answering_model_when_the_judge_model_is_empty() -> None:
    """The repo's own default is `model: ""` — the harness session's default
    answers — so the declared name cannot be checked in advance. The second
    guard reads `CompletionResult.model` and costs exactly one call, which the
    class docstring states rather than hides."""
    provider = FakeProvider(replies=['{"better": "A"}'], answered_by="claude-opus-5[1m]")
    ranker = PairwiseRanker(provider=provider, model="")
    with pytest.raises(SelfRankingError, match="after the call"):
        ranker.rank(TASK, OPUS, HAIKU)
    assert len(provider.requests) == 1


def test_an_owner_can_opt_out_and_then_it_ranks() -> None:
    provider = FakeProvider(replies=['{"better": "A"}', '{"better": "B"}'])
    ranker = PairwiseRanker(provider=provider, model="claude-opus-5", allow_self_ranking=True)
    ranking = ranker.rank(TASK, OPUS, HAIKU)
    assert ranking.winner == "incumbent"
    assert ranking.consistent


def test_a_candidate_with_no_declared_writer_cannot_trip_the_guard() -> None:
    """An empty `model` on a candidate means "unknown", and an unknown writer
    must not match every judge by accident — that would make the guard fire on
    every call and get switched off wholesale."""
    anonymous = Candidate(label="x", text="t", model="")
    provider = FakeProvider(replies=['{"better": "A"}', '{"better": "B"}'])
    ranking = PairwiseRanker(provider=provider, model="claude-opus-5").rank(TASK, anonymous, HAIKU)
    assert ranking.winner == "x"


# ---------------------------------------------------------------------------
# the position swap, and what the model does not get to decide
# ---------------------------------------------------------------------------
def test_the_swap_is_two_calls_with_the_candidates_in_opposite_positions() -> None:
    provider = FakeProvider(replies=['{"better": "A"}', '{"better": "B"}'])
    ranking = _ranker(provider).rank(TASK, OPUS, HAIKU)
    first, second = (r.messages[1].content for r in provider.requests)
    assert first.index(OPUS.text) < first.index(HAIKU.text)
    assert second.index(HAIKU.text) < second.index(OPUS.text)
    # "A" then "B" both name the FIRST-shown candidate's opposite number:
    # position A in run 1 is the incumbent, position B in run 2 is also the
    # incumbent. Same winner, so the judge is position-stable here.
    assert ranking.verdicts == ("incumbent", "incumbent")
    assert ranking.winner == "incumbent" and ranking.consistent


def test_a_position_flip_names_no_winner_and_says_so() -> None:
    """Both replies say "A", which means the judge preferred whatever was shown
    first — the definition of a position-dependent verdict. It must not average
    into a winner."""
    provider = FakeProvider(replies=['{"better": "A"}', '{"better": "A"}'])
    ranking = _ranker(provider).rank(TASK, OPUS, HAIKU)
    assert ranking.verdicts == ("incumbent", "candidate")
    assert ranking.winner is None
    assert ranking.consistent is False


def test_an_unparseable_reply_is_not_a_verdict() -> None:
    provider = FakeProvider(replies=["I prefer the first one, obviously.", '{"better": "B"}'])
    ranking = _ranker(provider).rank(TASK, OPUS, HAIKU)
    assert ranking.verdicts == (None, "incumbent")
    assert ranking.winner is None
    assert "unparseable reply" in ranking.rationale


def test_a_reply_naming_a_letter_that_is_not_a_position_is_refused() -> None:
    provider = FakeProvider(replies=['{"better": "C"}', '{"better": "B"}'])
    ranking = _ranker(provider).rank(TASK, OPUS, HAIKU)
    assert ranking.verdicts[0] is None


def test_a_provider_outage_is_recorded_rather_than_swallowed() -> None:
    provider = FakeProvider(fail=True)
    ranking = _ranker(provider).rank(TASK, OPUS, HAIKU)
    assert ranking.verdicts == (None, None)
    assert ranking.winner is None
    assert "fake outage" in ranking.rationale


def test_the_swap_can_be_turned_off_and_then_it_is_one_call() -> None:
    provider = FakeProvider(replies=['{"better": "B"}'])
    ranking = _ranker(provider, position_swap=False).rank(TASK, OPUS, HAIKU)
    assert len(provider.requests) == 1
    assert ranking.winner == "candidate"
    # One sample cannot disagree with itself; `consistent` says the swap did
    # not contradict, never that a control ran.
    assert ranking.consistent
    assert "over 1 sample(s)" in ranking.rationale


def test_two_candidates_with_the_same_label_is_refused() -> None:
    twin = Candidate(label="incumbent", text="other", model="z")
    with pytest.raises(ValueError, match="both candidates are labelled"):
        _ranker(FakeProvider()).rank(TASK, OPUS, twin)
