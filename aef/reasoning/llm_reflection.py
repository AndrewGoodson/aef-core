"""LLM-backed Critic and Judge (ADR 0115) — the Phase-3 slice ADR 0046
deferred, buildable now because ADR 0112 gave the runtime a model that needs
no key.

Two rules carried over from the summariser (ADR 0110), because they are
what keeps a model in the loop honest:

**The model writes prose; code computes every counted field.** The critic's
`grounded_in` is `failure_signals(state)` — the same citations the
rule-based critic emits — never something the model claimed to have seen.
The judge's `score` is the rule-based weighted mean over per-term scores the
model returned, with the rule-based anti-omission rule intact: a rubric term
the model did not score counts as 0.0. A model that returns nothing usable
falls back to the rule-based implementation and says so in the rationale.

**The judge sees the answer.** Evidence is the errors, the tool results, the
scores, the reflections — and the string-valued `working_memory` entries,
which on a content task is where the answer is (ADR 0126). Without them the
judges were scoring a run they could not read: on the summary corpus the
rule-based judge agreed with the owner's checks 3/18 and the LLM judge 9/18,
and neither's evidence contained the summary.

**Bias controls are structural, not requested.** The evidence the judge sees
is capped per item (`MAX_EXCERPT_CHARS`, and `MAX_ANSWER_CHARS` for the
answer class) so a longer failure cannot read as a
worse or a better one by bulk alone; and the judge asks twice with the
evidence in opposite orders and averages — a position-swap control for
single-item grading — reporting the disagreement as `position_delta` so a
judge that scores the same state differently depending on what it read
first is visible rather than averaged away silently.

Vendor isolation (constraint #3) holds: this module imports `ModelProvider`,
never a vendor SDK.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aef.providers.base import (
    CompletionRequest,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.reasoning.reflection import Critic, Critique, Judge, Judgment
from aef.reasoning.rule_based_reflection import (
    MAX_EXCERPT_CHARS,
    RuleBasedCritic,
    RuleBasedJudge,
    failure_signals,
)
from aef.state import AEFState

MAX_EVIDENCE_ITEMS = 12
DEFAULT_MAX_TOKENS = 2000

# `working_memory` strings are excerpted at a HIGHER cap than everything else,
# and the reason is that they are not corroborating evidence — on a content
# task the answer lives here, and it is the thing being scored (ADR 0126).
# `MAX_EXCERPT_CHARS` is 160; a 35-word summary is roughly 250 characters, so
# the shared cap would hand the judge the first two thirds of every answer and
# ask it to score completeness. 600 covers the corpus's longest answer with
# headroom and is still a cap: an unbounded working memory cannot flood the
# prompt, and every entry in this class is cut at the same length, so bulk
# still cannot read as quality WITHIN the class.
MAX_ANSWER_CHARS = 600
# ... and only the first few, so a state carrying many strings cannot crowd
# the errors that explain the answer out of the total item cap.
MAX_WORKING_MEMORY_ITEMS = 4

CRITIC_SYSTEM = (
    "You are the critic in an agent's reflection step. You are given the objective, "
    "the recorded errors and tool results of one run, and nothing else. Write a short "
    "verbal critique: what went wrong, the most likely cause, and one concrete change "
    "worth trying next run. Refer only to evidence shown. Do not invent errors, tools, "
    "or outcomes that are not listed. Plain prose, at most 120 words."
)

JUDGE_SYSTEM = (
    "You are the judge in an agent's reflection step. Score ONE run against a rubric. "
    "Reply with a single JSON object mapping each rubric term to a number from 0.0 to "
    "1.0 and nothing else. Length of the evidence is not quality: a run with more "
    "recorded output is not better or worse for having more of it. Score only what "
    "the evidence supports."
)


@dataclass(frozen=True)
class _Evidence:
    items: tuple[str, ...]  # already excerpted; order is the caller's

    def render(self, *, reverse: bool) -> str:
        ordered = tuple(reversed(self.items)) if reverse else self.items
        return "\n".join(f"- {item}" for item in ordered) if ordered else "- (none)"


def _excerpt(value: object, limit: int = MAX_EXCERPT_CHARS) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _evidence(state: AEFState) -> _Evidence:
    items: list[str] = []
    # First, because it is what the run produced. Measured on the summary
    # corpus (ADR 0123's A/B): the rule-based judge agreed with the owner's
    # checks on 3 of 18 states and the LLM judge on 9, and the reason was
    # this — neither judge's evidence contained the answer it was scoring.
    # Every counted field is still computed from the state; this only lets
    # the model see what it is being asked about. Sorted by key so two runs
    # with the same memory render the same prompt.
    strings = [
        (key, value)
        for key, value in sorted(state.working_memory.items(), key=lambda kv: kv[0])
        if isinstance(value, str) and value
    ]
    for key, value in strings[:MAX_WORKING_MEMORY_ITEMS]:
        items.append(f"working_memory[{key}]: {_excerpt(value, MAX_ANSWER_CHARS)}")
    for i, error in enumerate(state.errors):
        detail = error.get("error") or error.get("message") or error
        items.append(f"errors[{i}] ({error.get('node_id', '?')}): {_excerpt(detail)}")
    for i, result in enumerate(state.tool_results):
        status = "FAILED" if result.get("error") else "ok"
        items.append(f"tool_results[{i}] {status}: {_excerpt(result)}")
    if state.scores:
        items.append(f"scores: {_excerpt(dict(state.scores))}")
    for i, reflection in enumerate(state.reflections):
        items.append(f"reflections[{i}]: {_excerpt(reflection)}")
    items = items[:MAX_EVIDENCE_ITEMS]
    return _Evidence(items=tuple(items))


def _complete(provider: ModelProvider, model: str, system: str, user: str, max_tokens: int) -> str:
    result = provider.complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content=system),
                ProviderMessage(role="user", content=user),
            ),
            model=model,
            max_tokens=max_tokens,
        )
    )
    return (result.content or "").strip()


@dataclass(frozen=True)
class LLMCritic(Critic):
    """Prose from the model, citations from the state."""

    provider: ModelProvider
    model: str
    fallback: RuleBasedCritic = field(default_factory=RuleBasedCritic)
    max_tokens: int = DEFAULT_MAX_TOKENS

    def critique(self, state: AEFState) -> Critique:
        baseline = self.fallback.critique(state)
        evidence = _evidence(state)
        prompt = (
            f"Objective: {state.objective}\n\nEvidence:\n{evidence.render(reverse=False)}\n\n"
            "Write the critique."
        )
        try:
            text = _complete(self.provider, self.model, CRITIC_SYSTEM, prompt, self.max_tokens)
        except ModelProviderError as exc:
            return Critique(
                verbal_feedback=f"{baseline.verbal_feedback} [llm critic unavailable: {exc}]",
                grounded_in=baseline.grounded_in,
            )
        if not text:
            return Critique(
                verbal_feedback=f"{baseline.verbal_feedback} [llm critic returned nothing]",
                grounded_in=baseline.grounded_in,
            )
        # Added, not substituted (ADR 0110): the rule-based line is the
        # evidence the prose must remain traceable to.
        return Critique(
            verbal_feedback=f"{text}\n\nEvidence: {baseline.verbal_feedback}",
            grounded_in=failure_signals(state),
        )


@dataclass(frozen=True)
class LLMJudge(Judge):
    """Per-term scores from the model; the weighted score, the omission rule,
    and the position-swap control from code."""

    provider: ModelProvider
    model: str
    rubric: Mapping[str, float]
    position_swap: bool = True
    max_tokens: int = 400
    fallback: RuleBasedJudge | None = None
    _baseline: RuleBasedJudge = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Reuse the rule-based validation of the rubric: same rules, same
        # error messages, one place.
        object.__setattr__(self, "_baseline", RuleBasedJudge(rubric=dict(self.rubric)))

    @property
    def _rule_based(self) -> RuleBasedJudge:
        return self.fallback if self.fallback is not None else self._baseline

    def judge(self, state: AEFState) -> Judgment:
        evidence = _evidence(state)
        terms = sorted(self.rubric)
        orders = (False, True) if self.position_swap else (False,)
        samples: list[dict[str, float]] = []
        failures: list[str] = []
        for reverse in orders:
            prompt = (
                f"Objective: {state.objective}\n\nRubric terms: {', '.join(terms)}\n\n"
                f"Evidence:\n{evidence.render(reverse=reverse)}\n\n"
                'Reply with JSON only, e.g. {"' + terms[0] + '": 0.5}.'
            )
            try:
                text = _complete(self.provider, self.model, JUDGE_SYSTEM, prompt, self.max_tokens)
            except ModelProviderError as exc:
                failures.append(str(exc))
                continue
            parsed = _parse_scores(text, terms)
            if parsed is None:
                failures.append(f"unparseable reply: {text[:80]!r}")
                continue
            samples.append(parsed)
        if not samples:
            base = self._rule_based.judge(state)
            return Judgment(
                score=base.score,
                rubric=base.rubric,
                rationale=f"{base.rationale} [llm judge fell back: {'; '.join(failures)}]",
            )
        # Code owns the arithmetic. Missing terms count 0.0 (anti-omission),
        # values are clamped, and the position-swap samples are averaged.
        per_term = {
            term: sum(_clamp(s.get(term, 0.0)) for s in samples) / len(samples) for term in terms
        }
        weight_sum = sum(self.rubric.values())
        score = sum(per_term[t] * self.rubric[t] for t in terms) / weight_sum
        missing = tuple(t for t in terms if any(t not in s for s in samples))
        delta = 0.0
        if len(samples) == 2:
            first = sum(_clamp(samples[0].get(t, 0.0)) * self.rubric[t] for t in terms) / weight_sum
            second = (
                sum(_clamp(samples[1].get(t, 0.0)) * self.rubric[t] for t in terms) / weight_sum
            )
            delta = abs(first - second)
        drivers = ", ".join(f"{t}={per_term[t]:.4g}" for t in terms[:3])
        rationale = (
            f"llm-judged weighted score {score:.4g} over {len(terms)} rubric term(s) "
            f"from {len(samples)} sample(s); {drivers}; position_delta={delta:.4g}"
        )
        if missing:
            rationale += f"; missing from the model's reply (counted as 0.0): {', '.join(missing)}"
        if failures:
            rationale += f"; {len(failures)} sample(s) failed: {'; '.join(failures)}"
        return Judgment(score=score, rubric=dict(self.rubric), rationale=rationale)


def _clamp(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return min(1.0, max(0.0, number))


def _parse_scores(text: str, terms: list[str]) -> dict[str, float] | None:
    """The first JSON object in the reply, keyed by rubric term. Tolerates a
    code fence or a sentence around it; refuses anything that is not an
    object. Unknown keys are dropped — the model does not get to add terms."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload: Any = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {k: _clamp(v) for k, v in payload.items() if k in terms}
