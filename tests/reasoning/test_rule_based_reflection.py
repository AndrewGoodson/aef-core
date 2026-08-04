"""`RuleBasedCritic` / `RuleBasedJudge` — the first real (non-stub) Critic and
Judge. Built to the same standard as `RuleBasedEvaluator`: no LLM call, no
vendor SDK, grounded strictly in signals already recorded on `AEFState`.

Adversarial fixtures are the point here, not the happy path — a Critic that
only works on well-formed state is not a Critic, it is a template.
"""

import math

import pytest

from aef.reasoning.reflection import Critic, Judge
from aef.reasoning.rule_based_reflection import (
    RuleBasedCritic,
    RuleBasedJudge,
    failure_signals,
)
from aef.state import AEFState


def _state(**overrides: object) -> AEFState:
    defaults: dict[str, object] = {"run_id": "r1", "agent_id": "a1", "objective": "obj"}
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# failure_signals — the single shared "what counts as a failure" convention
# --------------------------------------------------------------------------


def test_no_signals_on_clean_state() -> None:
    assert failure_signals(_state()) == ()


def test_errors_are_cited_by_index() -> None:
    state = _state(errors=[{"error": "boom"}, {"error": "bang"}])
    assert failure_signals(state) == ("errors[0]", "errors[1]")


def test_tool_failure_uses_the_same_error_key_convention_as_the_evaluator() -> None:
    # RuleBasedEvaluator._tool_call_accuracy keys off `result.get("error")`
    # truthiness (rule_based.py). A second, competing convention here would
    # be a bug in the making — this pins that they agree.
    state = _state(tool_results=[{"ok": 1}, {"error": "timeout"}, {"error": ""}])
    assert failure_signals(state) == ("tool_results[1]",)


def test_signals_combine_errors_and_tool_results() -> None:
    state = _state(errors=[{"error": "e"}], tool_results=[{"error": "t"}])
    assert failure_signals(state) == ("errors[0]", "tool_results[0]")


def test_an_empty_error_entry_still_counts_as_a_failure_signal() -> None:
    # Presence in `state.errors` is itself the signal; a node that appended
    # an empty dict still reported a failure.
    assert failure_signals(_state(errors=[{}])) == ("errors[0]",)


# --------------------------------------------------------------------------
# RuleBasedCritic
# --------------------------------------------------------------------------


def test_critic_is_a_real_critic() -> None:
    assert isinstance(RuleBasedCritic(), Critic)


def test_critique_of_a_clean_state_cites_nothing() -> None:
    critique = RuleBasedCritic().critique(_state(tool_results=[{"ok": 1}]))
    assert critique.grounded_in == ()
    assert "no failure signals" in critique.verbal_feedback


def test_critique_grounded_in_is_populated_not_left_empty() -> None:
    state = _state(errors=[{"error": "boom"}], tool_results=[{"error": "timeout"}])
    critique = RuleBasedCritic().critique(state)
    assert critique.grounded_in == ("errors[0]", "tool_results[0]")


def test_every_citation_resolves_to_a_real_entry() -> None:
    state = _state(
        errors=[{"error": "a"}, {"error": "b"}],
        tool_results=[{"ok": 1}, {"error": "c"}],
    )
    for ref in RuleBasedCritic().critique(state).grounded_in:
        field, index = ref.rstrip("]").split("[")
        assert index.isdigit()
        assert int(index) < len(getattr(state, field))


def test_critique_quotes_the_actual_error_text() -> None:
    critique = RuleBasedCritic().critique(_state(errors=[{"error": "disk on fire"}]))
    assert "disk on fire" in critique.verbal_feedback


def test_critique_survives_an_error_entry_with_no_error_key() -> None:
    # `AEFState.errors` is `list[dict[str, Any]]` — nothing constrains the
    # shape, so a missing key must not raise.
    critique = RuleBasedCritic().critique(_state(errors=[{"node_id": "n1"}]))
    assert critique.grounded_in == ("errors[0]",)
    assert "n1" in critique.verbal_feedback


def test_critique_survives_a_non_string_error_value() -> None:
    critique = RuleBasedCritic().critique(_state(errors=[{"error": {"code": 500}}]))
    assert critique.grounded_in == ("errors[0]",)
    assert "500" in critique.verbal_feedback


def test_critique_truncates_a_huge_error_so_feedback_stays_bounded() -> None:
    # Reflections are appended to state and written to memory, both of which
    # are read back into a context window later. An unbounded error string
    # would silently blow the context budget.
    critique = RuleBasedCritic().critique(_state(errors=[{"error": "x" * 100_000}]))
    assert len(critique.verbal_feedback) < 2_000
    assert "…" in critique.verbal_feedback


def test_critique_is_deterministic() -> None:
    state = _state(errors=[{"error": "boom"}], tool_results=[{"error": "t"}])
    critic = RuleBasedCritic()
    assert critic.critique(state) == critic.critique(state)


def test_critique_does_not_mutate_state() -> None:
    state = _state(errors=[{"error": "boom"}], tool_results=[{"error": "t"}])
    before = state.model_dump_json()
    RuleBasedCritic().critique(state)
    assert state.model_dump_json() == before


# --------------------------------------------------------------------------
# RuleBasedJudge — construction guards
# --------------------------------------------------------------------------


def test_judge_is_a_real_judge() -> None:
    assert isinstance(RuleBasedJudge(rubric={"quality": 1.0}), Judge)


def test_empty_rubric_is_rejected_at_construction() -> None:
    # `Judgment.score` is `float`, not `float | None`, so an empty rubric has
    # no honest return value — 0.0 would be indistinguishable from "scored
    # zero". Reject the misconfiguration instead of fabricating a number.
    with pytest.raises(ValueError, match="rubric must not be empty"):
        RuleBasedJudge(rubric={})


def test_negative_weight_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RuleBasedJudge(rubric={"quality": -1.0})


def test_all_zero_weights_are_rejected_at_construction() -> None:
    # Would divide by zero and produce nan, which AEFState.scores rejects
    # (ADR 0022) several steps later instead of here.
    with pytest.raises(ValueError, match="sum to a positive"):
        RuleBasedJudge(rubric={"a": 0.0, "b": 0.0})


@pytest.mark.parametrize("weight", [math.inf, -math.inf, math.nan])
def test_non_finite_weight_is_rejected_at_construction(weight: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        RuleBasedJudge(rubric={"quality": weight})


# --------------------------------------------------------------------------
# RuleBasedJudge — scoring
# --------------------------------------------------------------------------


def test_score_is_the_weighted_mean_of_recorded_scores() -> None:
    judge = RuleBasedJudge(rubric={"a": 1.0, "b": 3.0})
    judgment = judge.judge(_state(scores={"a": 1.0, "b": 0.0}))
    assert judgment.score == pytest.approx(0.25)


def test_a_rubric_key_missing_from_scores_is_zero_not_skipped() -> None:
    # Skipping would let a candidate improve its score by simply not
    # reporting a metric — the exact reward-hacking shape this program
    # exists to prevent. Missing scores 0.0; you cannot gain by omission.
    judge = RuleBasedJudge(rubric={"a": 1.0, "b": 1.0})
    with_both = judge.judge(_state(scores={"a": 1.0, "b": 1.0}))
    with_one_missing = judge.judge(_state(scores={"a": 1.0}))
    assert with_both.score == pytest.approx(1.0)
    assert with_one_missing.score == pytest.approx(0.5)
    assert with_one_missing.score < with_both.score


def test_missing_rubric_keys_are_named_in_the_rationale() -> None:
    judgment = RuleBasedJudge(rubric={"a": 1.0, "b": 1.0}).judge(_state(scores={"a": 1.0}))
    assert "b" in judgment.rationale
    assert "missing" in judgment.rationale.lower()


def test_scores_outside_the_rubric_are_ignored() -> None:
    judge = RuleBasedJudge(rubric={"a": 1.0})
    assert judge.judge(_state(scores={"a": 1.0, "unrelated": 0.0})).score == pytest.approx(1.0)


def test_judgment_reports_the_weights_it_applied() -> None:
    judgment = RuleBasedJudge(rubric={"a": 2.0, "b": 1.0}).judge(_state(scores={"a": 1.0}))
    assert judgment.rubric == {"a": 2.0, "b": 1.0}


def test_score_is_always_finite() -> None:
    # AEFState.scores is validated finite (ADR 0022) and weights are
    # validated finite and positive-sum, so the quotient cannot be nan/inf.
    judgment = RuleBasedJudge(rubric={"a": 1e300, "b": 1e300}).judge(
        _state(scores={"a": 1.0, "b": 1.0})
    )
    assert math.isfinite(judgment.score)


def test_judge_is_deterministic() -> None:
    judge = RuleBasedJudge(rubric={"a": 1.0})
    state = _state(scores={"a": 0.7})
    assert judge.judge(state) == judge.judge(state)


def test_judge_does_not_mutate_state() -> None:
    state = _state(scores={"a": 0.7})
    before = state.model_dump_json()
    RuleBasedJudge(rubric={"a": 1.0}).judge(state)
    assert state.model_dump_json() == before
