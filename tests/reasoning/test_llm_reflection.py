"""LLM critic and judge (ADR 0115). A fake provider records every request
and returns scripted replies; no process, no network. What is pinned is
what the model is NOT trusted with: citations, arithmetic, omission,
clamping, and the position-swap control."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)
from aef.reasoning.llm_reflection import LLMCritic, LLMJudge
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.state import AEFState


@dataclass
class FakeProvider(ModelProvider):
    name = "fake"
    replies: list[str] = field(default_factory=list)
    requests: list[CompletionRequest] = field(default_factory=list)
    fail: bool = False

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.fail:
            raise ModelProviderError("fake outage")
        reply = self.replies.pop(0) if self.replies else ""
        return CompletionResult(content=reply, model="fake-model", input_tokens=1, output_tokens=1)


def _failed_state() -> AEFState:
    return AEFState(
        run_id="r1",
        agent_id="a",
        objective="fetch the report",
        errors=[{"node_id": "fetch", "error": "upstream timed out after 30s"}],
        tool_results=[{"name": "http_get", "error": "timeout"}, {"name": "parse", "ok": True}],
        scores={"quality": 0.0},
    )


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------
def test_critic_prose_comes_from_the_model_and_citations_from_the_state() -> None:
    provider = FakeProvider(replies=["The fetch node timed out; add a bounded retry."])
    critique = LLMCritic(provider=provider, model="m").critique(_failed_state())
    assert critique.verbal_feedback.startswith("The fetch node timed out; add a bounded retry.")
    # Same citations the rule-based critic emits — computed, never claimed.
    assert critique.grounded_in == RuleBasedCritic().critique(_failed_state()).grounded_in
    assert critique.grounded_in == ("errors[0]", "tool_results[0]")
    # The rule-based evidence line travels with the prose (ADR 0110: add, don't substitute).
    assert "Evidence: 1 error(s) recorded; 1/2 tool call(s) failed." in critique.verbal_feedback


def test_critic_prompt_carries_only_state_evidence() -> None:
    provider = FakeProvider(replies=["x"])
    LLMCritic(provider=provider, model="m").critique(_failed_state())
    request = provider.requests[0]
    assert request.model == "m"
    assert request.messages[0].role == "system"
    user = request.messages[1].content
    assert "fetch the report" in user
    assert "errors[0] (fetch): upstream timed out after 30s" in user
    assert "tool_results[0] FAILED" in user


def test_critic_falls_back_to_rule_based_on_provider_failure() -> None:
    critique = LLMCritic(provider=FakeProvider(fail=True), model="m").critique(_failed_state())
    baseline = RuleBasedCritic().critique(_failed_state())
    assert critique.verbal_feedback.startswith(baseline.verbal_feedback)
    assert "llm critic unavailable" in critique.verbal_feedback
    assert critique.grounded_in == baseline.grounded_in


def test_critic_falls_back_when_the_model_says_nothing() -> None:
    critique = LLMCritic(provider=FakeProvider(replies=["   "]), model="m").critique(
        _failed_state()
    )
    assert "llm critic returned nothing" in critique.verbal_feedback


# ---------------------------------------------------------------------------
# Judge — the model scores terms, code owns everything else
# ---------------------------------------------------------------------------
def test_judge_averages_the_position_swapped_samples_and_reports_the_delta() -> None:
    provider = FakeProvider(
        replies=['{"quality": 0.8, "speed": 0.4}', '{"quality": 0.6, "speed": 0.4}']
    )
    judge = LLMJudge(provider=provider, model="m", rubric={"quality": 3.0, "speed": 1.0})
    judgment = judge.judge(_failed_state())
    # quality mean 0.7, speed 0.4 -> (0.7*3 + 0.4*1) / 4
    assert judgment.score == pytest.approx((0.7 * 3 + 0.4) / 4)
    # sample 1: (0.8*3+0.4)/4 = 0.7 ; sample 2: (0.6*3+0.4)/4 = 0.55
    assert "position_delta=0.15" in judgment.rationale
    assert judgment.rubric == {"quality": 3.0, "speed": 1.0}
    assert len(provider.requests) == 2


def test_judge_presents_evidence_in_opposite_orders() -> None:
    provider = FakeProvider(replies=['{"quality": 1}', '{"quality": 1}'])
    LLMJudge(provider=provider, model="m", rubric={"quality": 1.0}).judge(_failed_state())
    first, second = (r.messages[1].content for r in provider.requests)
    first_lines = [line for line in first.splitlines() if line.startswith("- ")]
    second_lines = [line for line in second.splitlines() if line.startswith("- ")]
    assert first_lines == list(reversed(second_lines))
    assert len(first_lines) >= 3


def test_judge_counts_a_term_the_model_omitted_as_zero() -> None:
    """The rule-based anti-omission rule survives: a model that scores only
    the easy term cannot lift the score by leaving the hard one out."""
    provider = FakeProvider(replies=['{"quality": 1.0}'])
    judge = LLMJudge(
        provider=provider, model="m", rubric={"quality": 1.0, "safety": 1.0}, position_swap=False
    )
    judgment = judge.judge(_failed_state())
    assert judgment.score == pytest.approx(0.5)
    assert "missing from the model's reply (counted as 0.0): safety" in judgment.rationale


def test_judge_clamps_and_ignores_terms_the_model_invented() -> None:
    provider = FakeProvider(replies=['{"quality": 7, "bonus": 1.0, "speed": -3}'])
    judge = LLMJudge(
        provider=provider, model="m", rubric={"quality": 1.0, "speed": 1.0}, position_swap=False
    )
    judgment = judge.judge(_failed_state())
    assert judgment.score == pytest.approx(0.5)  # quality clamped to 1, speed to 0, bonus dropped
    assert judgment.rubric == {"quality": 1.0, "speed": 1.0}


def test_judge_tolerates_a_fenced_reply() -> None:
    provider = FakeProvider(replies=['Sure:\n```json\n{"quality": 0.25}\n```'])
    judge = LLMJudge(provider=provider, model="m", rubric={"quality": 1.0}, position_swap=False)
    assert judge.judge(_failed_state()).score == pytest.approx(0.25)


def test_judge_falls_back_to_rule_based_when_every_sample_fails() -> None:
    state = _failed_state()
    provider = FakeProvider(replies=["not json", "still not json"])
    judgment = LLMJudge(provider=provider, model="m", rubric={"quality": 1.0}).judge(state)
    baseline = RuleBasedJudge(rubric={"quality": 1.0}).judge(state)
    assert judgment.score == baseline.score
    assert "llm judge fell back" in judgment.rationale


def test_judge_uses_the_one_good_sample_and_names_the_failed_one() -> None:
    provider = FakeProvider(replies=["garbage", '{"quality": 0.5}'])
    judgment = LLMJudge(provider=provider, model="m", rubric={"quality": 1.0}).judge(
        _failed_state()
    )
    assert judgment.score == pytest.approx(0.5)
    assert "1 sample(s) failed" in judgment.rationale
    assert "position_delta=0" in judgment.rationale


def test_judge_rubric_is_validated_like_the_rule_based_one() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        LLMJudge(provider=FakeProvider(), model="m", rubric={})
    with pytest.raises(ValueError, match="non-negative"):
        LLMJudge(provider=FakeProvider(), model="m", rubric={"q": -1.0})


def test_evidence_is_excerpted_so_bulk_cannot_read_as_quality() -> None:
    state = AEFState(
        run_id="r",
        agent_id="a",
        objective="o",
        errors=[{"node_id": "n", "error": "x" * 5000}],
    )
    provider = FakeProvider(replies=['{"quality": 1}'])
    LLMJudge(provider=provider, model="m", rubric={"quality": 1.0}, position_swap=False).judge(
        state
    )
    user = provider.requests[0].messages[1].content
    assert "x" * 200 not in user


# ---------------------------------------------------------------------------
# Wiring: reachable from aef.yaml, refused early when it cannot work
# ---------------------------------------------------------------------------
def test_agent_services_wires_llm_reflection_when_asked() -> None:
    from aef.services.runtime import agent_services

    services = agent_services(
        model_provider=FakeProvider(), reflection="llm", reflection_model="claude-x"
    )
    assert isinstance(services.require_critic(), LLMCritic)
    judge = services.require_judge()
    assert isinstance(judge, LLMJudge)
    assert judge.model == "claude-x"


def test_agent_services_refuses_llm_reflection_without_a_provider() -> None:
    from aef.services.runtime import agent_services

    with pytest.raises(ValueError, match="needs a model provider"):
        agent_services(reflection="llm")


def test_agent_services_default_is_still_rule_based() -> None:
    from aef.services.runtime import agent_services

    assert isinstance(agent_services().require_critic(), RuleBasedCritic)
    assert isinstance(agent_services().require_judge(), RuleBasedJudge)


def test_reflection_config_refuses_an_unknown_impl() -> None:
    from aef.config.schema import ReflectionConfig

    assert ReflectionConfig().impl == "rule_based"
    assert ReflectionConfig(impl="llm").impl == "llm"
    with pytest.raises(ValueError, match="reflection.impl"):
        ReflectionConfig(impl="oracle")
