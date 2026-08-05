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
from aef.security.tool import PolicyConfig

RUNNER_MODULE = "aef.harness.scenario_runner"

# Which splits hold the candidate. The holdout is the owner's and is never
# spent on a routine gate run.
GATED_SPLITS: tuple[Split, ...] = (Split.TRAIN, Split.VALIDATION)


def _paused_note(paused: int, added: int) -> str:
    """Say out loud that the harness did not approve anything.

    The gate deliberately supplies no `hitl_approvals`, so a HITL-gated
    scenario cannot be scored on behaviour. That is a real limit on what this
    verdict covers, and a verdict that does not state its own limits invites
    being read as broader than it is (ADR 0081).
    """
    if not paused:
        return ""
    note = (
        f" {paused} scenario(s) stopped at a human-approval gate and were NOT approved by "
        f"the harness — their behaviour is unmeasured, not passing."
    )
    if added:
        note += f" {added} of those are gates the incumbent did not have."
    return note


class G2ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class G2OutcomeNonRegression(Gate):
    id: str = "G2"
    corpus: Corpus | None = None
    # No default, for the reason `LoopConfig.entrypoint` has none (ADR 0074):
    # a default naming a layout the adopting repo does not have fails as an
    # import error inside a gate, which reads as an ordinary rejection. The
    # default was deleted from `LoopConfig` and survived here — so the driver
    # correctly reported "no entrypoint configured: G2/G3 will refuse" and G2
    # went and imported `agents.graph` anyway, crashing instead of refusing
    # (ADR 0075).
    entrypoint: str | None = None
    splits: tuple[Split, ...] = field(default_factory=lambda: GATED_SPLITS)
    # Supplied by the driver when the cohort run already executed the
    # candidate over this corpus. Materialising a variant and loading its
    # graph is the expensive step; re-running it to ask a second question
    # about the same execution would double the cost of the most expensive
    # gate for nothing.
    precomputed: dict[str, Outcome] | None = None
    policy_config: PolicyConfig | None = None

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

        if self.precomputed is not None:
            candidate_outcomes = self.precomputed
        else:
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
                    expected=scenario.expected.value,
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

        tripwires = [c for c in comparisons if c.tripwire_hit]
        if tripwires:
            # Reported separately and as a security event: a tripwire hit is
            # not one bad scenario among many, it is evidence that the
            # self-report every other score rests on is unreliable (ADR 0060).
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"{len(tripwires)} tripwire scenario(s) the owner labelled impossible "
                    f"now report success — the agent's self-report is unreliable, so no "
                    f"score derived from it means anything"
                ),
                evidence=tuple(c.summary for c in tripwires),
                security_event=True,
            )

        regressions = [c for c in comparisons if c.regressed]
        diverged = [c for c in comparisons if c.routing_diverged and not c.regressed]
        paused = [c for c in comparisons if c.candidate.hitl_paused]
        added = [c for c in comparisons if c.gate_added]

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
                + _paused_note(len(paused), len(added))
            ),
            evidence=tuple(c.summary for c in diverged + added),
        )

    def _execute(
        self, ctx: GateContext, workspace: Path, scenarios: list[Scenario]
    ) -> dict[str, Outcome]:
        if self.entrypoint is None:
            raise G2ExecutionError(
                "no entrypoint configured, so there is no graph to re-execute the corpus "
                "against. Pass --entrypoint <module>:<factory> naming the function that "
                "builds your graph."
            )
        payload = workspace / "_scenarios.json"
        payload.write_text(dumps([s.to_payload() for s in scenarios]))
        argv = ["python", "-m", RUNNER_MODULE, str(payload), self.entrypoint]
        if self.policy_config is not None:
            # From the base ref, written by the harness — never read from the
            # candidate's workspace, or it would supply its own rules
            # (ADR 0082).
            policy_payload = workspace / "_policy.json"
            policy_payload.write_text(
                json.dumps(
                    {
                        "allowed_scopes": sorted(self.policy_config.allowed_scopes),
                        "forbidden_tool_names": sorted(self.policy_config.forbidden_tool_names),
                        "require_hitl_above_risk": (self.policy_config.require_hitl_above_risk),
                    }
                )
            )
            argv.append(str(policy_payload))

        policy = ctx.sandbox_policy or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
        result = run_sandboxed(
            tuple(argv),
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
        # The runner emits {"outcome": ..., "score": ...} so one pass serves
        # both G2 and G3; tolerate the bare-outcome shape for robustness.
        return {
            sid: Outcome.from_payload(body["outcome"] if "outcome" in body else body)
            for sid, body in raw.items()
        }


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
