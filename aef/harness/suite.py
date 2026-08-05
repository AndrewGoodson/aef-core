"""Running the corpus against a variant, and building G3's cohort verdict.

This is the piece that made G2 and G3 able to pass at all. Both gates were
built and tested; neither had anything supplying it with evidence. G3 in
particular returned FAIL on every run because nothing constructed a
`CohortVerdict` — the control cohort generator existed (ADR 0054) and had no
caller.

**One execution answers both gates.** Materialising a variant and loading its
graph is the expensive step, so `scenario_runner` emits the outcome *and* the
score from a single pass. Running the corpus twice to answer two questions
about the same execution would double the cost of the most expensive gate in
the pipeline for nothing.

**The cohort costs N+2 corpus passes**, and there is no way around that: the
null hypothesis is "what do random changes score", and answering it means
scoring random changes. That expense is the price of the claim G3 makes, and
it is reported rather than hidden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aef.harness.candidate import CandidateDiff
from aef.harness.corpus import Scenario
from aef.harness.evaluation import CohortVerdict, ScoreSet
from aef.harness.git import GitRepo
from aef.harness.outcome import Outcome
from aef.harness.proposer import ControlCohortGenerator, ProposalError
from aef.harness.sandbox import SandboxPolicy, run_sandboxed
from aef.harness.trace_codec import dumps
from aef.harness.workspace import build_candidate_workspace
from aef.harness.zones import ZonePolicy
from aef.security.tool import PolicyConfig

RUNNER_MODULE = "aef.harness.scenario_runner"


class SuiteError(RuntimeError):
    pass


@dataclass(frozen=True)
class VariantRun:
    """One variant's results over the whole corpus."""

    label: str
    outcomes: dict[str, Outcome]
    scores: ScoreSet

    @property
    def scenario_ids(self) -> frozenset[str]:
        return frozenset(self.outcomes)


def _parse(label: str, stdout: str) -> VariantRun:
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SuiteError(
            f"variant {label!r} runner emitted invalid JSON: {exc}; stdout was {stdout[:400]!r}"
        ) from exc

    outcomes: dict[str, Outcome] = {}
    per_scenario: dict[str, float] = {}
    cost = 0
    for scenario_id, body in raw.items():
        outcomes[scenario_id] = Outcome.from_payload(body["outcome"])
        per_scenario[scenario_id] = float(body.get("score", 0.0))
        cost += int(body.get("cost_tokens", 0))

    return VariantRun(
        label=label,
        outcomes=outcomes,
        scores=ScoreSet(label=label, per_scenario=per_scenario, cost_tokens=cost),
    )


def _policy_payload(config: PolicyConfig) -> dict[str, object]:
    return {
        "allowed_scopes": sorted(config.allowed_scopes),
        "forbidden_tool_names": sorted(config.forbidden_tool_names),
        "require_hitl_above_risk": config.require_hitl_above_risk,
    }


def run_variant(
    workspace: Path,
    scenarios: list[Scenario] | tuple[Scenario, ...],
    *,
    label: str,
    entrypoint: str,
    policy: SandboxPolicy,
    policy_config: PolicyConfig | None = None,
) -> VariantRun:
    """Score one already-materialised workspace over the corpus, in the sandbox."""
    payload = workspace / "_scenarios.json"
    payload.write_text(dumps([s.to_payload() for s in scenarios]))
    argv = ["python", "-m", RUNNER_MODULE, str(payload), entrypoint]
    if policy_config is not None:
        # Written into the workspace by the HARNESS, from the base ref. The
        # candidate never supplies the rules it is judged under (ADR 0082).
        policy_payload = workspace / "_policy.json"
        policy_payload.write_text(json.dumps(_policy_payload(policy_config)))
        argv.append(str(policy_payload))

    result = run_sandboxed(
        tuple(argv),
        workdir=workspace,
        policy=policy,
    )
    if not result.ok:
        detail = "timed out" if result.timed_out else f"exit {result.returncode}"
        raise SuiteError(
            f"variant {label!r} failed ({detail}): "
            f"{(result.stderr or result.stdout).strip()[-1500:]}"
        )
    return _parse(label, result.stdout)


@dataclass(frozen=True)
class CohortPlan:
    """What a full G3 evaluation will cost, computed before spending it."""

    cohort_size: int
    scenarios: int

    @property
    def corpus_passes(self) -> int:
        """candidate + incumbent + one per control."""
        return self.cohort_size + 2

    @property
    def scenario_executions(self) -> int:
        return self.corpus_passes * self.scenarios

    def describe(self) -> str:
        return (
            f"{self.corpus_passes} corpus pass(es) "
            f"({self.scenario_executions} scenario execution(s)): 1 candidate + 1 incumbent "
            f"+ {self.cohort_size} random control(s)"
        )


@dataclass(frozen=True)
class CohortBuilder:
    """Builds the `CohortVerdict` G3 refuses to run without.

    The cohort mutates the **same files the candidate changed**, using the
    same machinery (ADR 0054). A cohort drawn from anywhere else would be
    measuring a different distribution than the candidate sits in, and
    beating it would prove nothing about the candidate.
    """

    repo: GitRepo
    entrypoint: str
    policy: SandboxPolicy
    zone_policy: ZonePolicy = ZonePolicy()
    cohort_size: int = 5
    seed: int = 0
    policy_config: PolicyConfig | None = None

    def plan(self, scenarios: tuple[Scenario, ...]) -> CohortPlan:
        return CohortPlan(cohort_size=self.cohort_size, scenarios=len(scenarios))

    def build(
        self,
        diff: CandidateDiff,
        scenarios: tuple[Scenario, ...],
        workroot: Path,
    ) -> tuple[CohortVerdict, VariantRun, str]:
        """Returns `(verdict, candidate_run, cost_note)`.

        The candidate's `VariantRun` is returned too so G2 can reuse it —
        the outcomes and the scores came from the same execution.
        """
        if not scenarios:
            raise SuiteError("cannot build a cohort against an empty corpus")

        candidate_ws = build_candidate_workspace(
            self.repo, diff, workroot / "candidate", self.zone_policy
        )
        candidate = run_variant(
            candidate_ws,
            scenarios,
            label="candidate",
            entrypoint=self.entrypoint,
            policy=self.policy,
            policy_config=self.policy_config,
        )

        incumbent_ws = _materialise_base(self.repo, diff, workroot / "incumbent")
        incumbent = run_variant(
            incumbent_ws,
            scenarios,
            label="incumbent",
            entrypoint=self.entrypoint,
            policy=self.policy,
            policy_config=self.policy_config,
        )

        cohort = tuple(
            run_variant(
                ws,
                scenarios,
                label=label,
                entrypoint=self.entrypoint,
                policy=self.policy,
                policy_config=self.policy_config,
            ).scores
            for label, ws in self._control_workspaces(diff, workroot)
        )

        plan = self.plan(scenarios)
        verdict = CohortVerdict(
            candidate=candidate.scores, incumbent=incumbent.scores, cohort=cohort
        )
        return verdict, candidate, plan.describe()

    def _control_workspaces(self, diff: CandidateDiff, workroot: Path) -> list[tuple[str, Path]]:
        """One workspace per random mutation of a file the candidate touched."""
        targets = [e.path for e in diff.entries if not e.is_deletion and e.path.endswith(".py")]
        if not targets:
            raise SuiteError(
                "the candidate changed no Python file, so there is nothing to mutate for a "
                "control cohort and G3 has no null hypothesis to test against"
            )

        source_path = targets[0]
        # The INCUMBENT's source, not the candidate's. The null hypothesis is
        # "would a random change to the incumbent have done as well as this
        # reasoned change to the incumbent" — so the cohort must start where
        # the candidate started. Mutating the candidate instead asks whether
        # random *further* changes match it, which is a different question
        # with a much higher answer: perturbing an already-improved variant
        # frequently keeps the improvement, so the threshold rises to meet
        # the candidate and nothing can ever beat it. Found by running the
        # pipeline against a candidate that should plainly have passed.
        if not self.repo.path_exists_at(diff.base_sha, source_path):
            raise SuiteError(
                f"{source_path!r} does not exist at the base ref, so there is no incumbent "
                f"version to mutate. A cohort drawn from the candidate itself tests the "
                f"wrong hypothesis; a new file needs a different control design."
            )
        source = self.repo.show(diff.base_sha, source_path)
        try:
            controls = ControlCohortGenerator(seed=self.seed).generate(
                path=source_path, source=source, size=self.cohort_size
            )
        except ProposalError as exc:
            raise SuiteError(f"cannot build a control cohort: {exc}") from exc

        # Controls are materialised from the INCUMBENT, not from the candidate
        # workspace. Overlaying the candidate diff and then replacing only
        # `targets[0]` left every control carrying the candidate's changes to
        # files 1..n — so on a two-file candidate all five controls scored
        # identically to the candidate, p95 rose to meet it, and G3 could
        # never pass. This is the same failure the comment above records for
        # the single-file case; the fix had been applied to one file only
        # (ADR 0074).
        made: list[tuple[str, Path]] = []
        for control in controls:
            workspace = _materialise_base(self.repo, diff, workroot / control.id)
            (workspace / source_path).write_text(control.proposed)
            made.append((control.id, workspace))
        return made


def _materialise_base(repo: GitRepo, diff: CandidateDiff, dest: Path) -> Path:
    """The incumbent: the base ref with no candidate overlay at all."""
    empty = CandidateDiff(
        base_ref=diff.base_ref,
        head_ref=diff.base_ref,
        base_sha=diff.base_sha,
        head_sha=diff.base_sha,
        entries=(),
    )
    return build_candidate_workspace(repo, empty, dest)
