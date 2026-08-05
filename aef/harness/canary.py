"""Phase-4 criterion 6: **canary rollout stratified by tenant tag, gated on
percentiles, previous version kept warm for rollback.**

Four requirements in one sentence, and each is load-bearing:

- **stratified by tenant tag** — assignment is per tenant, not per request.
  A tenant that lands on the candidate for one request and the incumbent for
  the next sees inconsistent behaviour *and* contributes samples to both arms,
  which is how a difference between versions gets averaged into invisibility.
  Assignment here is a hash of `(graph_id, version, tenant_tag)`: stable for a
  tenant, and re-shuffled per version so the same tenants are not always the
  guinea pigs.
- **gated on percentiles** — not on means. A regression that doubles the worst
  1% while improving the median is exactly the shape a mean hides, and it is
  the shape users notice.
- **previous version kept warm** — a rollback target that has to be rebuilt is
  not a rollback, it is an outage with a plan.
- **rollout** — stages, which is what `monitor` never had: it rolls back, but
  it has nothing staged to roll back *to* partway.

`monitor` already rolls back on a regression. This is the ladder it was
missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import blake2b

# The ladder. Each rung must survive its own observation window before the next
# is entered, and 100 is a stage rather than an implicit end state so "fully
# promoted" is something the ledger records rather than something inferred from
# the absence of a next stage.
DEFAULT_LADDER: tuple[int, ...] = (1, 5, 25, 50, 100)

# Percentiles compared against the incumbent. p50 catches a broad regression;
# p95 and p99 catch the tail a mean would bury.
DEFAULT_PERCENTILES: tuple[int, ...] = (50, 95, 99)

# How much worse a percentile may be before the stage fails, as a ratio.
# 1.0 would fail on measurement noise; a value this loose is deliberate,
# because a canary's job is to catch a REGRESSION, and a gate that fires on
# jitter gets disabled by whoever is on call.
DEFAULT_TOLERANCE = 1.20

# Below this, a percentile is computed from too few samples to mean anything.
# A p99 over 20 samples is the maximum with extra steps.
MIN_SAMPLES = 100


class CanaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanaryVerdict:
    stage_percent: int
    passed: bool
    reason: str
    measurements: tuple[str, ...] = ()


def percentile(samples: list[float], p: int) -> float:
    """Nearest-rank percentile. No interpolation.

    Interpolating invents a value between two observations and then gates on
    it; nearest-rank returns a number that actually happened, which is what an
    operator asked to explain a rollback needs to be able to point at.
    """
    if not samples:
        raise CanaryError(f"cannot take p{p} of an empty sample")
    if not 0 < p <= 100:
        raise CanaryError(f"percentile must be within (0, 100]; got {p}")
    ordered = sorted(samples)
    rank = max(1, -(-p * len(ordered) // 100))
    return ordered[rank - 1]


@dataclass(frozen=True)
class CanaryPolicy:
    ladder: tuple[int, ...] = DEFAULT_LADDER
    percentiles: tuple[int, ...] = DEFAULT_PERCENTILES
    tolerance: float = DEFAULT_TOLERANCE
    min_samples: int = MIN_SAMPLES

    def __post_init__(self) -> None:
        if not self.ladder:
            raise CanaryError("a canary needs at least one stage")
        if list(self.ladder) != sorted(set(self.ladder)):
            raise CanaryError(
                f"ladder {self.ladder} must be strictly increasing and unique — a stage that "
                f"narrows exposure reads as progress while reducing the evidence"
            )
        if self.ladder[-1] != 100:
            raise CanaryError(
                f"the last stage must be 100, not {self.ladder[-1]}; otherwise 'fully "
                f"promoted' is inferred from running out of stages rather than recorded"
            )
        if not 0 < self.ladder[0]:
            raise CanaryError("the first stage must expose someone")
        if self.tolerance < 1.0:
            raise CanaryError(
                f"tolerance {self.tolerance} below 1.0 demands the candidate be BETTER than "
                f"the incumbent at every percentile to proceed, which fails on noise alone"
            )
        if self.min_samples < 1:
            raise CanaryError("min_samples must be positive")


def assigned_to_candidate(tenant_tag: str, *, graph_id: str, version: int, percent: int) -> bool:
    """Is this tenant in the candidate arm at `percent` exposure?

    Deterministic, so a tenant's arm does not change between requests, and
    **monotone in `percent`**: a tenant admitted at 5% is still admitted at 25.
    Without that, advancing a stage would reshuffle the population and throw
    away every sample gathered so far — the ladder would restart its evidence
    at every rung while appearing to accumulate it.
    """
    if not 0 <= percent <= 100:
        raise CanaryError(f"percent must be within [0, 100]; got {percent}")
    if not tenant_tag:
        raise CanaryError(
            "a canary stratified by tenant tag cannot assign an empty tag; an unlabelled "
            "request has no arm, and defaulting it to the incumbent would silently exempt "
            "whoever forgot the tag"
        )
    seed = f"{graph_id}:{version}:{tenant_tag}".encode()
    bucket = int.from_bytes(blake2b(seed, digest_size=8).digest(), "big") % 100
    return bucket < percent


@dataclass(frozen=True)
class CanaryState:
    """Where a rollout is, and what it can fall back to.

    `warm_version` is the requirement's "previous version kept warm". It is
    carried in the state rather than looked up, because a rollback that has to
    resolve its own target is a rollback that can fail at the moment it is
    needed.
    """

    graph_id: str
    candidate_version: int
    warm_version: int
    stage_index: int = 0
    policy: CanaryPolicy = field(default_factory=CanaryPolicy)
    history: tuple[str, ...] = ()
    # Set by `rollback` and never cleared. Found by this milestone's
    # adversarial round: without it a rolled-back rollout climbed the ladder
    # again on the next passing verdict, so a candidate with a real regression
    # cycled advance -> regress -> rollback -> advance forever, re-exposing
    # users on every lap. A rollback is a VERDICT ON THIS CANDIDATE, not a
    # reset — what comes next is a new version, not a retry of this one.
    rolled_back: bool = False

    def __post_init__(self) -> None:
        if self.warm_version == self.candidate_version:
            raise CanaryError(
                f"warm_version equals candidate_version ({self.warm_version}); there is "
                f"nothing to roll back TO, so this rollout has no rollback"
            )
        if not 0 <= self.stage_index < len(self.policy.ladder):
            raise CanaryError(f"stage_index {self.stage_index} is outside the ladder")

    @property
    def percent(self) -> int:
        return self.policy.ladder[self.stage_index]

    @property
    def complete(self) -> bool:
        return self.percent == 100

    def serves_candidate(self, tenant_tag: str) -> bool:
        return assigned_to_candidate(
            tenant_tag,
            graph_id=self.graph_id,
            version=self.candidate_version,
            percent=self.percent,
        )

    def evaluate(
        self, *, candidate_samples: list[float], incumbent_samples: list[float]
    ) -> CanaryVerdict:
        """Compare this stage's arms at every configured percentile.

        Lower is better — these are latencies, error counts, costs. A metric
        where higher is better must be negated by the caller, and that is
        stated here because the alternative is a `higher_is_better` flag whose
        default silently decides the direction of every gate.
        """
        stage = self.percent
        for label, samples in (("candidate", candidate_samples), ("incumbent", incumbent_samples)):
            if len(samples) < self.policy.min_samples:
                return CanaryVerdict(
                    stage_percent=stage,
                    passed=False,
                    reason=(
                        f"{len(samples)} {label} sample(s), below the floor of "
                        f"{self.policy.min_samples}. A percentile over too few observations is "
                        f"a number without a claim; this is 'keep watching', not 'regressed'"
                    ),
                )

        measurements: list[str] = []
        for p in self.policy.percentiles:
            cand = percentile(candidate_samples, p)
            base = percentile(incumbent_samples, p)
            ceiling = base * self.policy.tolerance
            measurements.append(f"p{p}: candidate {cand:.4g} vs incumbent {base:.4g}")
            if cand > ceiling:
                return CanaryVerdict(
                    stage_percent=stage,
                    passed=False,
                    reason=(
                        f"p{p} regressed: candidate {cand:.4g} exceeds {ceiling:.4g} "
                        f"({self.policy.tolerance:.2f}x incumbent {base:.4g})"
                    ),
                    measurements=tuple(measurements),
                )
        return CanaryVerdict(
            stage_percent=stage,
            passed=True,
            reason=f"all percentiles within {self.policy.tolerance:.2f}x of the incumbent",
            measurements=tuple(measurements),
        )

    def advance(self, verdict: CanaryVerdict, *, at: datetime) -> CanaryState:
        """One rung, on a passing verdict for THIS stage."""
        if not verdict.passed:
            raise CanaryError(
                f"cannot advance on a failing verdict: {verdict.reason}. Advancing past a "
                f"failure is not a rollout, it is a schedule"
            )
        if verdict.stage_percent != self.percent:
            # A verdict from a different exposure level describes a different
            # population. Accepting it would let a 1% stage's evidence promote
            # a 50% one.
            raise CanaryError(
                f"verdict describes stage {verdict.stage_percent}% but this rollout is at "
                f"{self.percent}%; that evidence is about a different population"
            )
        if self.rolled_back:
            raise CanaryError(
                f"this rollout was rolled back; v{self.candidate_version} does not climb the "
                f"ladder again. Retrying the same candidate re-exposes users to the same "
                f"regression on every lap — promote a NEW version, whose evidence is about "
                f"the fix"
            )
        if self.complete:
            raise CanaryError("already at 100%; there is no further stage to advance to")
        nxt = self.policy.ladder[self.stage_index + 1]
        entry = f"{at.isoformat()} advance {self.percent}% -> {nxt}%"
        return replace(self, stage_index=self.stage_index + 1, history=(*self.history, entry))

    def rollback(self, verdict: CanaryVerdict, *, at: datetime) -> CanaryState:
        """Back to the warm version, and TERMINAL for this candidate."""
        entry = (
            f"{at.isoformat()} rollback from {self.percent}% to v{self.warm_version}: "
            f"{verdict.reason}"
        )
        return replace(self, stage_index=0, rolled_back=True, history=(*self.history, entry))
