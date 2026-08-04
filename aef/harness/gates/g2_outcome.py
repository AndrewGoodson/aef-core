"""G2 — outcome non-regression over the golden corpus.

The backbone gate, and the expensive one, which is why all four cheap gates
run before it.

**Re-execution, not replay.** `ReplayEngine` verifies that a *recorded* run
reproduces; it can say nothing about a graph that has changed, because it
re-executes recorded nodes against recorded inputs. G2 runs each scenario's
initial state through the **candidate** graph and compares outcomes.

**Outcome, not path.** See `outcome.py`: comparing execution paths admits
only no-ops. Only previously-passing scenarios are held, and routing
divergence is reported rather than rejected.

The candidate's graph is loaded and run **inside the sandbox, in the
post-merge workspace** — whose `aef/` comes from the base ref (ADR 0047), so
the runner executing agent code is the base ref's runner. The candidate is
input to it, never part of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from aef.harness.corpus import Corpus, Scenario, Split
from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult
from aef.harness.outcome import Comparison, Outcome
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy, run_sandboxed
from aef.harness.trace_codec import dumps
from aef.harness.workspace import build_candidate_workspace

RUNNER_MODULE = "aef.harness.scenario_runner"

# Which splits hold the candidate. The holdout is the owner's and is never
# spent on a routine gate run.
GATED_SPLITS: tuple[Split, ...] = (Split.TRAIN, Split.VALIDATION)


class G2ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class G2OutcomeNonRegression(Gate):
    id: str = "G2"
    corpus: Corpus | None = None
    entrypoint: str = "agents.graph:build_graph"
    splits: tuple[Split, ...] = field(default_factory=lambda: GATED_SPLITS)

    def run(self, ctx: GateContext) -> GateResult:
        if self.corpus is None or not self.corpus.scenarios:
            # An empty corpus must never read as a pass. It means the gate
            # has no evidence, which is a Tier-2 escalation (ADR 0045
            # condition 7), not an endorsement.
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    "no corpus scenarios to gate against — absence of evidence is not "
                    "evidence of non-regression; escalate rather than admit"
                ),
            )

        scenarios = [s for s in self.corpus.scenarios if s.split in self.splits]
        if not scenarios:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"corpus holds no scenarios in the gated splits "
                    f"{[s.value for s in self.splits]}"
                ),
            )

        workspace = build_candidate_workspace(
            ctx.repo, ctx.verdict.diff, ctx.workdir / "workspace", ctx.zone_policy
        )
        candidate_outcomes = self._execute(ctx, workspace, scenarios)

        comparisons: list[Comparison] = []
        missing: list[str] = []
        for scenario in scenarios:
            produced = candidate_outcomes.get(scenario.id)
            if produced is None:
                missing.append(scenario.id)
                continue
            comparisons.append(
                Comparison(
                    scenario_id=scenario.id,
                    incumbent=recorded_outcome(scenario),
                    candidate=produced,
                )
            )

        if missing:
            # A scenario the candidate could not run at all is a failure, not
            # a gap: silently skipping it is how a corpus stops binding.
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=f"{len(missing)} scenario(s) produced no outcome under the candidate",
                evidence=tuple(sorted(missing)),
            )

        regressions = [c for c in comparisons if c.regressed]
        diverged = [c for c in comparisons if c.routing_diverged and not c.regressed]

        if regressions:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"{len(regressions)} previously-passing scenario(s) no longer pass "
                    f"(zero tolerance)"
                ),
                evidence=tuple(c.summary for c in regressions),
            )

        return GateResult(
            gate=self.id,
            outcome=GateOutcome.PASS,
            reason=(
                f"{len(comparisons)} scenario(s) re-executed; every previously-passing one "
                f"still passes. {len(diverged)} changed routing (reported, not rejected)."
            ),
            evidence=tuple(c.summary for c in diverged),
        )

    def _execute(
        self, ctx: GateContext, workspace: Path, scenarios: list[Scenario]
    ) -> dict[str, Outcome]:
        payload = workspace / "_scenarios.json"
        payload.write_text(dumps([s.to_payload() for s in scenarios]))

        policy = ctx.sandbox_policy or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
        result = run_sandboxed(
            ("python", "-m", RUNNER_MODULE, str(payload), self.entrypoint),
            workdir=workspace,
            policy=policy,
        )
        if not result.ok:
            detail = "timed out" if result.timed_out else f"exit {result.returncode}"
            raise G2ExecutionError(
                f"scenario runner failed ({detail}): "
                f"{(result.stderr or result.stdout).strip()[-2000:]}"
            )

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise G2ExecutionError(
                f"scenario runner emitted invalid JSON: {exc}; stdout was {result.stdout[:500]!r}"
            ) from exc
        return {sid: Outcome.from_payload(body) for sid, body in raw.items()}


def recorded_outcome(scenario: Scenario) -> Outcome:
    """The incumbent's outcome, reconstructed from the recorded trace.

    Derived rather than stored: a scenario file records what *happened*, and
    deriving the classification means changing the classification rule
    re-classifies the whole corpus consistently instead of leaving old
    entries judged by an old rule.
    """
    final_state = scenario.initial_state
    for record in scenario.trace:
        final_state = record.delta.apply(final_state)

    from aef.kernel.contracts import END

    terminated = bool(scenario.trace) and scenario.trace[-1].route is END
    from aef.harness.outcome import classify

    return classify(final_state, scenario.trace, terminated=terminated)
