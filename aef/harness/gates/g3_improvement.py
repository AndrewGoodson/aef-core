"""G3 — improvement, measured against a null hypothesis.

G2 established the candidate broke nothing. G3 asks whether it *helped*, and
refuses to answer from a comparison that cannot support the conclusion.

Four rejection rules:

1. **No control cohort ⇒ FAIL.** Beating the incumbent proves nothing:
   generate enough random variants and some score higher by chance on a
   fixed scenario set. Without a cohort there is no null hypothesis to
   reject, so the gate has no signal — escalate (Tier 2), never pass.
2. **Inside the cohort's spread ⇒ FAIL**, even if the incumbent is beaten.
   This is the null hypothesis holding.
3. **A previously-passing scenario now scoring below threshold ⇒ FAIL**,
   regardless of the aggregate. Zero tolerance, deterministic, and
   independent of any statistic — this is the rule that still binds when
   the sample is too small for the statistics to say anything.
4. **Cost blow-up ⇒ FAIL.** A candidate scoring marginally better while
   spending far more is not an improvement.

Confidence intervals are **reported, never gated on**. At n≈20 they overlap
routinely, and gating on means would launder noise into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from aef.harness.evaluation import CohortVerdict, ScoreSet
from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult

DEFAULT_COHORT_PERCENTILE = 95.0
DEFAULT_MIN_COHORT_SIZE = 5
DEFAULT_MAX_COST_RATIO = 1.5
PASS_THRESHOLD = 0.5


@dataclass(frozen=True)
class G3Improvement(Gate):
    id: str = "G3"
    verdict: CohortVerdict | None = None
    min_cohort_size: int = DEFAULT_MIN_COHORT_SIZE
    max_cost_ratio: float = DEFAULT_MAX_COST_RATIO

    def run(self, ctx: GateContext) -> GateResult:
        verdict = self.verdict
        if verdict is None or not verdict.cohort:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    "no null-hypothesis control cohort — beating the incumbent proves "
                    "nothing without one, so this gate has no signal and the candidate "
                    "escalates rather than passing"
                ),
            )

        if len(verdict.cohort) < self.min_cohort_size:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"control cohort of {len(verdict.cohort)} is below the minimum of "
                    f"{self.min_cohort_size}; a percentile over too few samples is not a "
                    f"threshold, it is a coin flip"
                ),
            )

        regressed = _regressed_scenarios(verdict.incumbent, verdict.candidate)
        if regressed:
            # Deterministic and independent of any statistic — the rule that
            # still binds when the sample is too small to say anything.
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"{len(regressed)} previously-passing scenario(s) now score below "
                    f"{PASS_THRESHOLD} (zero tolerance, regardless of the aggregate)"
                ),
                evidence=tuple(sorted(regressed)) + verdict.report,
            )

        cost_failure = self._check_cost(verdict)
        if cost_failure is not None:
            return cost_failure

        if not verdict.beats_cohort:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"candidate does not beat the p{verdict.percentile:g} of the random "
                    f"control cohort — this is the null hypothesis, not an improvement"
                ),
                evidence=verdict.report,
            )

        return GateResult(
            gate=self.id,
            outcome=GateOutcome.PASS,
            reason=(
                f"candidate mean {verdict.candidate.mean:.4g} beats the control cohort's "
                f"p{verdict.percentile:g} of {verdict.threshold:.4g}"
            ),
            evidence=verdict.report,
        )

    def _check_cost(self, verdict: CohortVerdict) -> GateResult | None:
        """Cost is SELF-REPORTED, and this rule says so.

        `cost_tokens` is `sum(p.token_cost for p in state.provenance)`, and
        `Provenance` is written by agent-authored nodes in their own
        `StateDelta`. Nothing else produces it. So a candidate that deletes
        `provenance=[...]` reports zero tokens and this rule cannot bind —
        the same shape as ADR 0080's `recovered` marker, on the cost axis
        (ADR 0092).

        Deleting the reporting is not a cheaper agent, it is an agent that
        stopped saying. An incumbent that reported and a candidate that does
        not is therefore treated as a cost violation, not a free pass. The
        rule remains unenforceable against an agent that never reported at
        all, and that limit is stated in the gate's own evidence rather than
        left for someone to discover.
        """
        incumbent_cost = verdict.incumbent.cost_tokens
        if incumbent_cost <= 0:
            # Nothing to compare against; say so rather than dividing by zero
            # or silently treating "unmeasured" as "free".
            return None

        if verdict.candidate.cost_tokens <= 0:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"the incumbent reported {incumbent_cost} tokens and the candidate "
                    f"reports none. Cost is self-reported from Provenance the agent emits, "
                    f"so dropping it reads as free rather than cheap — a candidate that "
                    f"stopped reporting has not shown it costs less"
                ),
                evidence=(
                    f"incumbent {incumbent_cost} tokens, candidate 0",
                    *verdict.report,
                ),
            )

        ratio = verdict.candidate.cost_tokens / incumbent_cost
        if ratio <= self.max_cost_ratio:
            return None
        return GateResult(
            gate=self.id,
            outcome=GateOutcome.FAIL,
            reason=(
                f"cost blow-up: candidate spends {ratio:.2f}x the incumbent's tokens, over "
                f"the {self.max_cost_ratio:.2f}x budget — a marginal score gain bought with "
                f"a large cost increase is not an improvement"
            ),
            evidence=(
                f"incumbent {incumbent_cost} tokens, candidate {verdict.candidate.cost_tokens}",
                *verdict.report,
            ),
        )


def _regressed_scenarios(incumbent: ScoreSet, candidate: ScoreSet) -> set[str]:
    """Scenario ids the incumbent passed and the candidate does not.

    A scenario the incumbent passed that the candidate did not score at all
    counts as regressed: a missing score is not a passing one.
    """
    return {
        sid for sid in incumbent.passing if candidate.per_scenario.get(sid, 0.0) < PASS_THRESHOLD
    }
