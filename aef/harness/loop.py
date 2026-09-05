"""The loop driver — the orchestration that was missing.

Every piece of the harness existed and was tested; nothing strung them
together. This module is that wiring, and it is where the ordering
decisions live.

**The kill switch is checked before anything else.** Not after reading the
ledger, not after computing the candidate — first. A halt evaluated after
the work is a report, not a stop.

**The ledger chain is verified before any command acts**, and a broken chain
refuses rather than being appended to. Appending onto damage buries the
tampering further from where it happened (ADR 0055).

**A Zone B or Zone C violation halts the loop.** It is not an ordinary
rejection to be logged and moved past — `05-approval-policy.md` §6 makes it
a halt criterion, because a proposal reaching for the judge is a category
signal about the proposer, not a fact about that one candidate.

**Tier-1 auto-merge is off, and the driver cannot turn it on.** Enabling it
is an owner action; `LoopConfig.tier1_enabled` exists so the code path can be
tested, and every caller in this repo passes `False`.
"""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aef.config import build_policy_config
from aef.config.loader import AgentConfigError, load_agent_config_text
from aef.config.schema import AgentConfig
from aef.harness import archive, ledger
from aef.harness.candidate import CandidateVerdict, inspect_candidate
from aef.harness.corpus import (
    MANIFEST_FILENAME,
    Corpus,
    CorpusManifest,
    Scenario,
    check_never_shrinks,
    load_manifest,
)
from aef.harness.gates.base import Gate, GateContext, PipelineResult, run_pipeline
from aef.harness.gates.g0_static_safety import G0StaticSafety
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.gates.g2_outcome import GATED_SPLITS, G2OutcomeNonRegression
from aef.harness.gates.g3_improvement import DEFAULT_MIN_COHORT_SIZE, G3Improvement
from aef.harness.gates.g4_separation import G4SeparationOfPowers
from aef.harness.gates.g5_rate_drift import DRIFT_EXHAUSTED, AcceptedChange, G5RateAndDrift
from aef.harness.git import GitError, GitRepo
from aef.harness.monitoring import (
    Action,
    Digest,
    KillSwitch,
    MonitorPolicy,
    Observation,
    Verdict,
    assess_halt,
    build_digest,
    evaluate_window,
)
from aef.harness.proposer import Proposal
from aef.harness.review import Decision, Disposition, decide, render_report
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.harness.suite import CohortBuilder
from aef.harness.zones import DEFAULT_AGENT_PATH, ZonePolicy
from aef.observability.base import Tracer
from aef.providers.base import ModelProvider
from aef.security.tool import PolicyConfig

# The gates that judge a candidate WITHOUT executing it.
_CHEAP: frozenset[str] = frozenset({"G0", "G1", "G4", "G5"})

# The proposers `cycle` can run (ADR 0122). `rule_based` is the default and
# `llm` is opt-in: measured on the flaky fixture and the demo agent before
# the default was chosen, and the ADR carries the numbers.
PROPOSERS: tuple[str, ...] = ("rule_based", "llm")

OBSERVATIONS_FILENAME = "observations.jsonl"

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_HALTED = 2
# The command could not do its job — an unexpected exception, or a
# configuration error that stops the turn before it starts.
#
# Distinct from `EXIT_REJECTED` because `aef/cli/main.py`'s catch-all returns
# **1** for any exception, and 1 is also "this candidate is no good, the system
# is working". The rendered nightly workflow fails the job on `status >= 2`,
# so a bad config, a missing corpus, an import error, a provider that is down,
# or the `agents.migrated.graph` placeholder whose `build_graph()` raises
# `NotImplementedError` all read as a healthy rejection and the job stays
# green — and, since the exception escaped before the attempt was journalled,
# `cycles.jsonl` gained nothing and the staleness alarm could never fire for
# those nights either (reproduced, ADR 0167).
#
# 3 rather than reusing 2: a halt and a crash call for different actions
# (release the kill switch versus fix the invocation), and `>= 2` catches both.
EXIT_ERROR = 3


@dataclass(frozen=True)
class LoopPaths:
    """Everything the loop persists. All of it is Zone B."""

    root: Path

    @property
    def ledger_dir(self) -> Path:
        return self.root

    @property
    def archive_dir(self) -> Path:
        return self.root / "archive"

    @property
    def observations(self) -> Path:
        return self.root / OBSERVATIONS_FILENAME

    @property
    def kill_switch(self) -> KillSwitch:
        return KillSwitch(root=self.root)


@dataclass(frozen=True)
class LoopConfig:
    repo: GitRepo
    paths: LoopPaths
    base_ref: str = "main"
    graph_id: str = "default"
    zone_policy: ZonePolicy = field(default_factory=ZonePolicy)
    corpus: Corpus | None = None
    monitor_policy: MonitorPolicy = field(default_factory=MonitorPolicy)
    # Attested by the CI container, passed in from the CLI. Never read from
    # the environment inside `sandbox.py` — the value must come from Zone B
    # configuration, not from anything a candidate can set.
    network_isolated: bool = False
    # HARD-STOP. Present so the merge path is reachable in a test; no caller
    # in this repo passes True. Turning it on is an owner action (ADR 0045).
    tier1_enabled: bool = False
    # No default. A default naming a layout the adopting repo does not have
    # fails as an import traceback buried in a ledger note, and reads as an
    # ordinary gate rejection (ADR 0069 defect 3, ADR 0074).
    entrypoint: str | None = None
    build_commands: tuple[tuple[str, ...], ...] | None = None
    cohort_size: int = 5
    cohort_seed: int = 0
    # Path to the agent config, READ FROM THE BASE REF. `None` means
    # deny-by-default, which is what an unconfigured production run gets.
    config_path: str | None = None
    # One span per gate run, when the owner wants them. Injected rather than
    # constructed, for the same reason nodes take a Tracer via Services.
    tracer: Tracer | None = None
    # Per-gate overrides, e.g. G0's max_changed_lines. Declared on
    # `GateContext` since ADR 0044 and never supplied.
    gate_limits: dict[str, Any] = field(default_factory=dict)
    gates: tuple[Gate, ...] | None = None
    sandbox_image: str | None = None
    # Which proposer `cycle` runs (ADR 0122). "llm" needs a provider and a
    # model; both are refused loudly at construction rather than at the first
    # turn, so a misconfigured run never reaches the ledger.
    proposer: str = "rule_based"
    proposer_provider: ModelProvider | None = None
    proposer_model: str | None = None
    # How a scenario's recorded model calls are replayed under the gates
    # (ADR 0123). "fail": a request the recording never saw is a failed
    # node — deterministic, credential-free, the default. "live": misses go
    # to the provider named in the base ref's `model_provider`, and the
    # score is a live one; the opt-in for scoring a prompt change.
    cassette_miss: str = "fail"

    def __post_init__(self) -> None:
        if self.cassette_miss not in ("fail", "live"):
            raise ValueError(f"cassette_miss must be 'fail' or 'live', got {self.cassette_miss!r}")
        if self.cohort_size < DEFAULT_MIN_COHORT_SIZE:
            raise ValueError(
                f"cohort_size {self.cohort_size} is below G3's minimum of "
                f"{DEFAULT_MIN_COHORT_SIZE}; every candidate would be rejected for an "
                f"undersized cohort. Raise it, or change G3's floor deliberately."
            )
        if self.proposer not in PROPOSERS:
            raise ValueError(f"proposer must be one of {PROPOSERS}, got {self.proposer!r}")
        if self.proposer == "llm" and (self.proposer_provider is None or not self.proposer_model):
            raise ValueError(
                "proposer='llm' needs proposer_provider (a ModelProvider) and proposer_model "
                "(the model it asks); neither has a default, because a proposer that "
                "silently ran rule-based when asked for a model would report a measurement "
                "it never made"
            )

    def sandbox_policy(self) -> SandboxPolicy:
        # An image beats an attestation. `network_isolated=True` is the CI
        # job saying "I am inside a --network none container"; an image is
        # the local run BUILDING one, and the difference is that the second
        # is verified by a probe rather than asserted (ADR 0102). That is 4b:
        # the two places can now make the same claim on the same evidence.
        if self.sandbox_image is not None:
            return SandboxPolicy(
                network=NetworkPolicy.REQUIRE_ISOLATED, container_image=self.sandbox_image
            )
        if self.network_isolated:
            return SandboxPolicy(
                network=NetworkPolicy.REQUIRE_ISOLATED, network_isolation_attested=True
            )
        return SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)

    def default_gates(self) -> tuple[Gate, ...]:
        """All six, always registered, with no evidence attached.

        A gate with no evidence **fails** rather than being omitted —
        omitting would make a candidate look gated when it was not. Real
        evidence is attached by `_gates_with_evidence` at gate time, because
        building it requires the candidate diff.
        """
        return (
            G0StaticSafety(),
            G1Builds(commands=self.build_commands) if self.build_commands else G1Builds(),
            G4SeparationOfPowers(),
            G5RateAndDrift(),
            G2OutcomeNonRegression(corpus=self.corpus),
            G3Improvement(),
        )


@dataclass(frozen=True)
class GateRun:
    decision: Decision
    result: PipelineResult
    report: str
    exit_code: int
    halted: bool = False
    # G3's task-metric means for this candidate and the incumbent it was
    # gated against, when the behavioural gates ran (ADR 0121). None when a
    # cheap gate rejected first and nothing was scored.
    candidate_score: float | None = None
    incumbent_score: float | None = None


class PolicyConfigError(RuntimeError):
    """`--config` was given and could not be turned into a policy.

    Loud, because the alternative was silent deny-by-default: a run that
    looks configured, is not, and says nothing (ADR 0090)."""


class LoopStateInsideRepoError(RuntimeError):
    """The loop's state directory sits inside the repository it judges."""


def _check_state_is_outside_the_repo(config: LoopConfig) -> None:
    """Refuse to run with loop state inside the working tree.

    Found by running the driver rather than by reading it: with `--state
    .loop` inside the repo, an ordinary `git add -A` sweeps the ledger and
    archive into the candidate's own commit. The ledger then appears as
    added lines in the diff being judged, every candidate looks like it
    touches Zone C, and the audit trail becomes part of the thing it is
    auditing. Deny rather than document.
    """
    repo_root = config.repo.root.resolve()
    state_root = config.paths.root.resolve()
    if state_root == repo_root or state_root.is_relative_to(repo_root):
        raise LoopStateInsideRepoError(
            f"loop state directory {state_root} is inside the repository {repo_root}. "
            f"The ledger and archive would be swept into candidate diffs by `git add -A`, "
            f"making the audit trail part of what it audits. Put --state outside the "
            f"working tree."
        )


def _corpus_baseline_manifest(config: LoopConfig, corpus: Corpus) -> CorpusManifest:
    """The never-shrinks baseline: from the BASE REF where that is possible.

    Reading it from the working tree lets a candidate delete a scenario and
    its manifest entry in one commit and pass. Reading it from the base ref
    does not, which is why the base ref is tried first and the working tree is
    a documented fallback for a corpus that lives outside the repository or is
    untracked (ADR 0141).
    """
    root = corpus.root.resolve()
    try:
        rel = root.relative_to(config.repo.root.resolve())
    except ValueError:
        return load_manifest(root)  # corpus outside the repo; nothing to read from git
    ref = f"{config.base_ref}:{rel.as_posix()}/{MANIFEST_FILENAME}"
    try:
        raw = config.repo.run_bytes("show", ref)
    except GitError:  # untracked, or no such ref — neither is a shrink
        return load_manifest(root)
    try:
        return CorpusManifest.from_payload(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError):
        return load_manifest(root)


def _preflight(config: LoopConfig) -> tuple[ledger.LedgerEntry, ...]:
    """State location, kill switch, then ledger, archive and corpus integrity.
    In that order.

    The kill switch check comes before any work, but after the location
    check: a state directory in the wrong place means the kill switch itself
    is inside the repo, so its answer cannot be trusted.
    """
    _check_state_is_outside_the_repo(config)
    config.paths.kill_switch.check()  # raises LoopHaltedError
    entries = ledger.read(config.paths.ledger_dir)
    # The ledger's hash chain was verified on every command and the
    # ARCHIVE's append-only property never was — so a deleted version left
    # `status` reporting healthy while the rollback target it names no longer
    # existed. Both are the audit trail; both get checked (ADR 0075).
    archive.check_never_shrinks(
        config.paths.archive_dir,
        config.graph_id,
        tuple(v for _, v in ledger.merged_versions(config.paths.ledger_dir)),
    )
    # And the CORPUS's, which had the same shape of hole for longer:
    # `corpus.check_never_shrinks` had no production caller at all, so
    # deleting the two scenarios an agent fails raised `aef loop score` from
    # 0.6667 to 1.0000 with nothing complaining, while
    # `recorder.refuse_existing_ids` cited this guard as its justification
    # (ADR 0141). It is the same audit-trail argument as the two above.
    if config.corpus is not None:
        check_never_shrinks(config.corpus, _corpus_baseline_manifest(config, config.corpus))
    return entries


def _halt(config: LoopConfig, *, at: datetime, proposal_id: str, reasons: tuple[str, ...]) -> None:
    joined = "; ".join(reasons)
    config.paths.kill_switch.engage(joined)
    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.HALTED,
        at=at,
        proposal_id=proposal_id,
        summary=joined,
        detail={"reasons": list(reasons)},
    )


def _agent_config_from_base_ref(config: LoopConfig) -> AgentConfig | None:
    """The adopter's `aef.yaml`, as of the BASE REF.

    Not from the workspace and not from the working tree. `aef.yaml` is Zone
    C — not agent-writable — but the gate must still read it the way it reads
    every other rule it judges by, or a candidate that edited it would be
    judged under rules it supplied. Same reason `trust.py` exists: if an agent
    can modify what judges it, the judgement carries no information
    (ADR 0044, ADR 0082).

    A missing or unreadable config is deny-by-default, never a pass.
    """
    if config.config_path is None:
        return None

    # `--repo`, `--state` and `--workdir` are all filesystem paths, so an
    # absolute `--config` is the natural thing to type — and `git show
    # <ref>:/abs/path` finds nothing, so the configured policy was silently
    # discarded and the run continued deny-by-default with no message. A
    # policy that quietly does not apply is worse than one that refuses
    # (ADR 0090).
    if Path(config.config_path).is_absolute():
        raise PolicyConfigError(
            f"--config must be a path INSIDE the repository, relative to its root — got "
            f"{config.config_path!r}. The gate reads it from the base ref via `git show`, "
            f"which cannot resolve an absolute path."
        )

    if not config.repo.path_exists_at(config.base_ref, config.config_path):
        raise PolicyConfigError(
            f"{config.config_path!r} does not exist at {config.base_ref!r}. The gate reads "
            f"policy from the base ref so a candidate cannot widen its own rules; a config "
            f"that exists only on the candidate branch is exactly what that prevents."
        )

    try:
        raw = config.repo.show(config.base_ref, config.config_path)
        agent_config = load_agent_config_text(raw, source=f"{config.base_ref}:{config.config_path}")
    except AgentConfigError as exc:
        # Deny-by-default is the right VALUE and silence was the wrong
        # delivery: an invalid config became indistinguishable from a
        # deliberately restrictive one.
        raise PolicyConfigError(
            f"agent config at {config.base_ref}:{config.config_path} did not load, so no "
            f"policy could be built: {exc}"
        ) from exc
    return agent_config


def _policy_from_base_ref(config: LoopConfig) -> PolicyConfig | None:
    """The adopter's configured policy, as of the BASE REF (see above).
    A missing config is deny-by-default, never a pass."""
    agent_config = _agent_config_from_base_ref(config)
    if agent_config is None:
        return None
    return build_policy_config(agent_config.tools, agent_config.policies)


def _live_provider_from_base_ref(config: LoopConfig) -> dict[str, str] | None:
    """Which provider the worker may build for cassette misses (ADR 0123).

    Only under `cassette_miss="live"`, and only the impl and model named by
    the BASE REF's `model_provider` — read the way the policy is read, so a
    candidate cannot point the gate at a provider of its choosing by
    editing the workspace's config. `None` otherwise, and a live miss with
    no config then fails in the worker naming the absence.
    """
    if config.cassette_miss != "live":
        return None
    agent_config = _agent_config_from_base_ref(config)
    if agent_config is None:
        return None
    return {"impl": agent_config.model_provider.impl, "model": agent_config.model_provider.model}


def _cheap_gates(config: LoopConfig, verdict: CandidateVerdict, now: datetime) -> tuple[Gate, ...]:
    """G0, G1, G4, G5 — everything that can reject a candidate WITHOUT
    executing its corpus. Run first so a rejected candidate never runs."""
    if config.gates is not None:
        return tuple(g for g in config.gates if g.id in _CHEAP)
    gates = [g for g in config.default_gates() if g.id in _CHEAP]
    return tuple(_with_g5(config, verdict, now, gates))


def _behavioural_only(gates: tuple[Gate, ...]) -> tuple[Gate, ...]:
    return tuple(g for g in gates if g.id not in _CHEAP)


class CorpusGraphMismatchError(RuntimeError):
    """The corpus holds several graphs' recordings and none are this one's.

    Named, and raised, rather than returning an empty scenario list: an empty
    corpus reads to G2/G3 as "no evidence", which escalates — the same
    outcome a corpus this loop simply cannot use, with none of the
    information about why (ADR 0125).
    """


def _scenarios_for_graph(
    config: LoopConfig, scenarios: tuple[Scenario, ...]
) -> tuple[tuple[Scenario, ...], str]:
    """The gated scenarios recorded FROM this graph.

    `corpus/` now holds two agents' recordings (`demo_agent` and
    `summary_agent`, ADR 0123), and the gates ran every one of them against
    whichever graph the entrypoint named — so a demo candidate was scored on
    summary scenarios it could not possibly satisfy and every mean was
    diluted by them. `aef loop score` already filtered (it can load the
    graph in-process and read `graph.id`); the gates, which cannot, did not.

    The rule, stated because it is a choice rather than a deduction:

    - Some gated scenario carries `graph_id == config.graph_id` → gate on
      exactly those. This is the case the mixed corpus creates.
    - No scenario matches and the corpus records ONE graph → gate on all of
      them. `--graph-id` defaults to `"default"` and is the ARCHIVE key, a
      different namespace from `graph.id`; a single-graph corpus has nothing
      to disambiguate, so requiring the two namespaces to agree would break
      every existing single-graph corpus to fix a mixed-corpus defect.
    - No scenario matches and the corpus records SEVERAL graphs → refuse by
      name. There is no defensible subset, and running all of them is the
      defect.
    """
    matching = tuple(s for s in scenarios if s.graph_id == config.graph_id)
    present = sorted({s.graph_id for s in scenarios})
    if matching:
        return matching, (
            f"{len(matching)}/{len(scenarios)} gated scenario(s) recorded from "
            f"graph {config.graph_id!r}"
        )
    if len(present) == 1:
        return scenarios, (
            f"corpus records one graph ({present[0]!r}); gating all "
            f"{len(scenarios)} gated scenario(s)"
        )
    raise CorpusGraphMismatchError(
        f"the corpus records {len(present)} graphs ({', '.join(repr(g) for g in present)}) "
        f"and none of them is --graph-id {config.graph_id!r}. Gating one graph against "
        f"another's scenarios dilutes every mean with scenarios the candidate cannot "
        f"satisfy. Pass --graph-id naming the graph this loop improves."
    )


def _gates_with_evidence(
    config: LoopConfig, verdict: CandidateVerdict, workdir: Path, now: datetime
) -> tuple[tuple[Gate, ...], str]:
    """Attach real evidence to G2, G3 and G5.

    Without this, G3 returns FAIL on every run because nothing constructs a
    `CohortVerdict` (ADR 0051), and G5 returns FAIL because nothing supplies
    a blessed baseline. The gates were built and tested; they had no caller
    feeding them, which meant the pipeline could not pass a candidate even
    with a perfect corpus.

    `now` is the caller's clock, threaded down rather than read from config.
    It used to come from `LoopConfig.now_for_gates`, which **no CLI command
    ever set** — so G5 ran with `now=None`, failed, and the fail-fast pipeline
    stopped before G2 and G3. Those two gates had never executed outside a
    test (ADR 0074).

    G5 is wired **before** the cohort is attempted, because a cohort failure
    is not evidence about the baseline: wiring it afterwards meant one
    `SuiteError` disabled three gates and made G5 report a missing baseline
    that was sitting in the archive.

    Building the cohort costs N+2 corpus passes. It is NOT skipped merely
    because it is expensive — a gate that is dropped when it is inconvenient
    is not a gate.
    """
    if config.gates is not None:
        return _behavioural_only(config.gates), "gates supplied explicitly"

    gates = _with_g5(config, verdict, now, list(config.default_gates()))

    if config.entrypoint is None:
        return _behavioural_only(tuple(gates)), (
            "no entrypoint configured: G2/G3 will refuse. Pass --entrypoint "
            "<module>:<factory> naming the function that builds your graph."
        )
    if config.corpus is None or not config.corpus.scenarios:
        return _behavioural_only(tuple(gates)), "no corpus: G2/G3 will refuse for lack of evidence"

    scenarios = tuple(s for s in config.corpus.scenarios if s.split in GATED_SPLITS)
    if not scenarios:
        return _behavioural_only(tuple(gates)), "no gated-split scenarios: G2/G3 will refuse"
    scenarios, graph_note = _scenarios_for_graph(config, scenarios)

    policy_config = _policy_from_base_ref(config)
    builder = CohortBuilder(
        repo=config.repo,
        entrypoint=config.entrypoint,
        policy=config.sandbox_policy(),
        zone_policy=config.zone_policy,
        cohort_size=config.cohort_size,
        seed=config.cohort_seed,
        policy_config=policy_config,
        cassette_miss=config.cassette_miss,
        live_provider=_live_provider_from_base_ref(config),
    )
    try:
        cohort_verdict, candidate_run, note = builder.build(
            verdict.diff, scenarios, workdir / "variants"
        )
    except Exception as exc:  # noqa: BLE001 - see below
        # ANY exception, not just SuiteError. `_gates_with_evidence` sits
        # BETWEEN the two `run_pipeline` calls, so `_run_traced`'s
        # raise-to-FAIL conversion (ADR 0090) does not cover it — a KeyError
        # from `_parse`, a GitError from workspace materialisation, anything
        # at all escaped `gate()` and left the proposal with a PROPOSED
        # ledger entry and no verdict. The exact hole ADR 0090 §1 says was
        # closed, on the one path that executes candidate code (ADR 0093).
        # Reported, not swallowed: G2/G3 stay in the pipeline and refuse,
        # so the candidate escalates rather than slipping through ungated.
        # G5 keeps its evidence — see the docstring.
        return _behavioural_only(
            tuple(gates)
        ), f"could not build evidence ({exc}); G2/G3 will refuse"

    rebuilt: list[Gate] = []
    for g in gates:
        if isinstance(g, G2OutcomeNonRegression):
            rebuilt.append(
                G2OutcomeNonRegression(
                    # The SAME scenarios the cohort ran. G2 reads its corpus
                    # itself and reports anything absent from `precomputed`
                    # as missing — so handing it the unfiltered corpus after
                    # filtering the cohort would turn every other graph's
                    # scenario into a missing one, which is a rejection.
                    corpus=replace(config.corpus, scenarios=scenarios),
                    precomputed=candidate_run.outcomes,
                    policy_config=policy_config,
                )
            )
        elif isinstance(g, G3Improvement):
            # G3's cohort floor is deliberately left at its own default.
            # Passing the configured size through as the floor made the guard
            # unsatisfiable — the builder generates exactly that many members,
            # so the comparison could never be true, and a two-member cohort
            # passed with p95 computed over two samples. A floor that moves
            # with the thing it floors is not a floor (ADR 0063).
            rebuilt.append(G3Improvement(verdict=cohort_verdict))
        else:
            rebuilt.append(g)
    return _behavioural_only(tuple(rebuilt)), f"{note}; {graph_note}"


def _with_g5(
    config: LoopConfig, verdict: CandidateVerdict, now: datetime, gates: list[Gate]
) -> list[Gate]:
    baseline = _blessed_baseline(config)
    if baseline is None:
        return gates
    return [
        G5RateAndDrift(
            baseline_files=baseline,
            candidate_files=_candidate_files(config, verdict),
            history=_accepted_history(config),
            now=now,
        )
        if isinstance(g, G5RateAndDrift)
        else g
        for g in gates
    ]


def _blessed_baseline(config: LoopConfig) -> dict[str, bytes] | None:
    """The owner-blessed archive version G5 measures drift against."""
    existing = archive.versions(config.paths.archive_dir, config.graph_id)
    if not existing:
        return None
    return archive.read_files(config.paths.archive_dir, config.graph_id, existing[0])


def _candidate_files(config: LoopConfig, verdict: CandidateVerdict) -> dict[str, bytes]:
    """The candidate's **whole Zone A tree**, not just the files it changed.

    Drift is `structural_drift(baseline, candidate)`, which unions the two key
    sets. Passing only the changed files made every blessed file the candidate
    left alone score as fully deleted, and every added file score against a
    denominator missing the untouched tree — so the *first* candidate after a
    blessing was rejected for 0.583 drift it had not caused (ADR 0074).
    """
    root = config.zone_policy.agent_root
    paths = set(config.repo.list_tree(verdict.diff.head_sha, root))
    # A deletion inside Zone A is real drift and must survive: it is absent
    # from the head tree by definition, so the union with the baseline's keys
    # is what charges it.
    return {p: config.repo.run_bytes("show", f"{verdict.diff.head_sha}:{p}") for p in sorted(paths)}


def _accepted_history(config: LoopConfig) -> tuple[AcceptedChange, ...]:
    entries = ledger.read(config.paths.ledger_dir)
    return tuple(
        AcceptedChange(version=int(e.detail.get("archive_version", 0)), at=e.at)
        for e in entries
        if e.kind is ledger.EventKind.MERGED
    )


def _drift_exhausted_twice(entries: tuple[ledger.LedgerEntry, ...]) -> bool:
    """Halt criterion 3. Read from the ledger, which has always held the
    evidence — `assess_halt` accepted the flag and nothing ever computed it,
    so two of the five criteria were dead parameters (ADR 0074).

    "In quick succession" is read as the two most recent gated verdicts: a
    proposer that exhausts the drift budget, is told so, and immediately does
    it again is not responding to the signal.
    """
    drift_failures = [
        any(
            g.get("gate") == "G5"
            and g.get("outcome") == "fail"
            and g.get("reason", "").startswith(DRIFT_EXHAUSTED)
            for g in e.detail.get("gates", [])
        )
        for e in entries
        if e.kind is ledger.EventKind.GATED
    ]
    return len(drift_failures) >= 2 and all(drift_failures[-2:])


def _consecutive_escalation_rejections(entries: tuple[ledger.LedgerEntry, ...]) -> int:
    """Halt criterion 4: escalations subsequently resolved by rejection.

    Counted over the TRAILING run of proposals, stopping at the first one
    that ended any other way. The first implementation only reset on
    `MERGED` — which is written solely on the auto-merge path, and Tier-1 is
    off — so nothing reset it from the CLI and it was a lifetime counter.
    Two re-gated proposals thirty days apart, with twenty ordinary rejections
    between them, halted the loop for "working outside its evidence base"
    (ADR 0080).

    Escalation is the NORMAL terminal state while Tier-1 is off, so this has
    to be about a trailing pattern or it is about nothing.
    """
    outcome: dict[str, list[ledger.EventKind]] = {}
    order: list[str] = []
    for entry in entries:
        if entry.kind not in (
            ledger.EventKind.ESCALATED,
            ledger.EventKind.REJECTED,
            ledger.EventKind.MERGED,
        ):
            continue
        if entry.proposal_id not in outcome:
            outcome[entry.proposal_id] = []
            order.append(entry.proposal_id)
        outcome[entry.proposal_id].append(entry.kind)

    run = 0
    for proposal_id in reversed(order):
        kinds = outcome[proposal_id]
        escalated_then_rejected = (
            ledger.EventKind.ESCALATED in kinds
            and ledger.EventKind.REJECTED in kinds
            and kinds.index(ledger.EventKind.ESCALATED) < kinds.index(ledger.EventKind.REJECTED)
        )
        if not escalated_then_rejected:
            break
        run += 1
    return run


def gate(
    config: LoopConfig,
    head_ref: str,
    *,
    now: datetime,
    workdir: Path,
    proposal: Proposal | None = None,
) -> GateRun:
    """Evaluate one candidate branch end to end."""
    _preflight(config)

    proposal_id = f"{head_ref}@{config.repo.rev_parse(head_ref)[:12]}"
    verdict = inspect_candidate(config.repo, config.base_ref, head_ref, config.zone_policy)

    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.PROPOSED,
        at=now,
        proposal_id=proposal_id,
        summary=f"{verdict.diff.changed_files} file(s), {verdict.diff.changed_lines} line(s)",
        detail={"base": config.base_ref, "head": head_ref, "paths": list(verdict.diff.paths)},
    )

    ctx = GateContext(
        # `tracer` had exactly one production construction site and it passed
        # neither of these, so `_run_traced`'s traced branch never executed
        # outside a test and G0's `max_changed_lines`/`max_changed_files`
        # overrides were unreachable by construction (ADR 0092).
        tracer=config.tracer,
        limits=dict(config.gate_limits),
        repo=config.repo,
        base_ref=config.base_ref,
        head_ref=head_ref,
        verdict=verdict,
        workdir=workdir,
        zone_policy=config.zone_policy,
        sandbox_policy=config.sandbox_policy(),
    )
    # TWO PASSES, and the split is a containment boundary, not an
    # optimisation. Building evidence EXECUTES THE CANDIDATE'S CODE — N+2
    # corpus passes in subprocesses — and it used to happen before
    # `run_pipeline` ran anything. So G0's import allowlist, the control that
    # exists for exactly this, ran second: a candidate G0 would reject for
    # `import socket` had already run its module-level code by then.
    # `gates/base.py` states the opposite ordering as the design ("all four
    # cheap gates run before the expensive corpus re-execution in G2. G4 is
    # deliberately early: a proposal reaching for its own tests is rejected
    # before it gets to run them"). It was not true (ADR 0085).
    #
    # Canonical order is preserved exactly — G0,G1,G4,G5 then G2,G3 — and a
    # candidate rejected by a cheap gate now never executes at all.
    candidate_score: float | None = None
    incumbent_score: float | None = None
    cheap = run_pipeline(_cheap_gates(config, verdict, now), ctx)
    if not cheap.passed:
        result = cheap
        rejected_by = cheap.failed_at.gate if cheap.failed_at else "a cheap gate"
        evidence_note = (
            f"not built: {rejected_by} rejected the candidate first, so its code was never executed"
        )
    else:
        behavioural, evidence_note = _gates_with_evidence(config, verdict, workdir, now)
        result = PipelineResult(results=cheap.results + run_pipeline(behavioural, ctx).results)
        cohort_verdict = next(
            (g.verdict for g in behavioural if isinstance(g, G3Improvement) and g.verdict),
            None,
        )
        if cohort_verdict is not None and cohort_verdict.candidate.n and cohort_verdict.incumbent.n:
            candidate_score = cohort_verdict.candidate.mean
            incumbent_score = cohort_verdict.incumbent.mean

    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.GATED,
        at=now,
        proposal_id=proposal_id,
        summary=f"ran {', '.join(result.ran)}; passed={result.passed}",
        detail={
            "gates": [
                {"gate": r.gate, "outcome": r.outcome.value, "reason": r.reason}
                for r in result.results
            ],
            # NOT `security_event`. The REJECTED entry below carries that key,
            # and the digest counts one per entry carrying it — so a single
            # incident was reported to the owner as two (ADR 0074). The gate
            # results above already record which gate raised it.
            "security_gates": [r.gate for r in result.results if r.security_event],
            "evidence": evidence_note,
            # The memory records this proposal was grounded in. Dropped
            # before, so the audit trail could not answer "what did the
            # proposer read to justify this" after the fact (ADR 0075).
            #
            # Rendered to strings, not passed as objects: `ledger.append`
            # JSON-serialises `detail`, and `Citation` is a frozen dataclass.
            # Writing the objects raised `Object of type Citation is not JSON
            # serializable` and killed `aef loop cycle` outright — the fix for
            # a dropped audit trail broke the command it was auditing, and the
            # test defending the wire only asserted source text (ADR 0078).
            "grounded_in": [str(c) for c in proposal.grounded_in] if proposal else [],
            # Which proposer produced it, so a ledger read after the fact can
            # separate the model's candidates from the rule-based ones.
            "proposer": config.proposer if proposal else None,
        },
    )

    decision = decide(result, tier1_enabled=config.tier1_enabled)
    report = _render(config, head_ref, proposal_id, result, decision, proposal)

    if result.security_events:
        # Halt criterion 2: a proposal reaching for the judge is a category
        # signal about the proposer, not a fact about this one candidate.
        assessment = assess_halt(zone_violation=True)
        ledger.append(
            config.paths.ledger_dir,
            kind=ledger.EventKind.REJECTED,
            at=now,
            proposal_id=proposal_id,
            summary=decision.reason,
            detail={"security_event": True},
        )
        _halt(config, at=now, proposal_id=proposal_id, reasons=assessment.reasons)
        return GateRun(
            decision=decision,
            result=result,
            report=report,
            exit_code=EXIT_HALTED,
            halted=True,
        )

    if decision.disposition is Disposition.REJECT:
        ledger.append(
            config.paths.ledger_dir,
            kind=ledger.EventKind.REJECTED,
            at=now,
            proposal_id=proposal_id,
            summary=decision.reason,
        )
        # Halt criteria 3 and 4, read from a ledger that now includes this
        # run. `assess_halt` accepted both flags and NOTHING EVER COMPUTED
        # THEM — two of five criteria were dead parameters while the ledger
        # held the evidence all along (ADR 0074, fixed in ADR 0077).
        history = ledger.read(config.paths.ledger_dir)
        assessment = assess_halt(
            drift_exhausted_twice=_drift_exhausted_twice(history),
            consecutive_escalation_rejections=_consecutive_escalation_rejections(history),
        )
        if assessment.should_halt:
            _halt(config, at=now, proposal_id=proposal_id, reasons=assessment.reasons)
            return GateRun(
                decision=decision,
                result=result,
                report=report,
                exit_code=EXIT_HALTED,
                halted=True,
            )
        return GateRun(
            decision=decision,
            result=result,
            report=report,
            exit_code=EXIT_REJECTED,
            candidate_score=candidate_score,
            incumbent_score=incumbent_score,
        )

    if decision.disposition is Disposition.ESCALATE:
        ledger.append(
            config.paths.ledger_dir,
            kind=ledger.EventKind.ESCALATED,
            at=now,
            proposal_id=proposal_id,
            summary=decision.reason,
            detail={"question": decision.question},
        )
        # Exit 0: an escalation is a successful run that produced a question,
        # not a failure. A non-zero exit here would train whoever reads CI to
        # treat "needs your decision" as "broken".
        return GateRun(
            decision=decision,
            result=result,
            report=report,
            exit_code=EXIT_OK,
            candidate_score=candidate_score,
            incumbent_score=incumbent_score,
        )

    # AUTO_MERGE — unreachable while tier1_enabled is False.
    files = {
        entry.path: config.repo.run_bytes("show", f"{verdict.diff.head_sha}:{entry.path}")
        for entry in verdict.diff.entries
        if not entry.is_deletion
    }
    archived = archive.record(
        config.paths.archive_dir,
        config.graph_id,
        files=files,
        base_sha=verdict.diff.base_sha,
        head_sha=verdict.diff.head_sha,
        recorded_at=now,
        gate_report=tuple(f"{r.gate}: {r.reason}" for r in result.results),
    )
    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.MERGED,
        at=now,
        proposal_id=proposal_id,
        summary=decision.reason,
        # No baseline_pass_rate is written, deliberately. Nothing in the harness
        # measures a live pass rate, and writing a literal 1.0 asserted that
        # production was perfect before every merge — so any agent below 95%
        # live read as REGRESSED, which halts the loop permanently with a
        # message blaming the gates (ADR 0072). Absence now means unmeasured.
        detail={"archive_version": archived.version},
    )
    return GateRun(
        decision=decision,
        result=result,
        report=report,
        exit_code=EXIT_OK,
        candidate_score=candidate_score,
        incumbent_score=incumbent_score,
    )


def _render(
    config: LoopConfig,
    head_ref: str,
    proposal_id: str,
    result: PipelineResult,
    decision: Decision,
    proposal: Proposal | None = None,
) -> str:
    """Render a report for a candidate BRANCH.

    `gate` judges a branch, which may not have come from this repo's proposer
    at all, so there is no `Proposal` object to render. The diff is taken
    from git rather than left as a placeholder — a report whose evidence
    section says "see the diff elsewhere" is the rubber stamp M9's ordering
    was designed to prevent, just with an extra step.
    """
    try:
        diff = config.repo.run("diff", f"{config.base_ref}...{head_ref}")
    except Exception:  # noqa: BLE001 - a missing diff must not lose the report
        diff = f"(could not render a diff for {proposal_id})\n"

    # A branch that came from this repo's proposer HAS a rationale and
    # citations; rendering the stub for it reported a memory-grounded
    # proposal as "none (control-cohort member)" in the owner's own review
    # report — the audit trail contradicting the thing it audits (ADR 0075).
    stub = Proposal(
        id=proposal_id,
        path=proposal.path if proposal else "(candidate branch)",
        original="",
        proposed=diff or "(empty diff)\n",
        rationale=proposal.rationale if proposal else f"candidate branch {proposal_id}",
        grounded_in=proposal.grounded_in if proposal else (),
        # Only the stub is exempt from the grounding requirement. A real
        # proposal already satisfied it at construction.
        is_control=proposal.is_control if proposal else True,
    )
    report = render_report(stub, result, decision)
    # render_report emits a unified diff of original->proposed; here the
    # "proposed" content IS already a diff, so present it directly.
    marker = "## The change itself"
    head, _, _ = report.partition(marker)
    return f"{head}{marker}\n\n```diff\n{diff.rstrip()}\n```\n"


# --------------------------------------------------------------------------
# monitor
# --------------------------------------------------------------------------


def load_observations(path: Path) -> tuple[Observation, ...]:
    """`{"at": iso, "passed": bool, "cost_tokens": int}` per line.

    **Nothing in this repo writes this file.** A deployment running agents in
    production emits it; the loop only reads it. Recorded plainly because a
    monitoring system with no input silently reports every window as
    unobserved — which, correctly, rolls everything back.
    """
    if not path.is_file():
        return ()
    out: list[Observation] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            out.append(
                Observation(
                    at=datetime.fromisoformat(payload["at"]),
                    passed=bool(payload["passed"]),
                    cost_tokens=int(payload.get("cost_tokens", 0)),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{number}: malformed observation: {exc}") from exc
    return tuple(out)


@dataclass(frozen=True)
class MonitorRun:
    checked: int = 0
    rolled_back: tuple[str, ...] = ()
    halted: bool = False
    halt_reasons: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    exit_code: int = EXIT_OK


def monitor(config: LoopConfig, *, now: datetime, restore_to: Path | None = None) -> MonitorRun:
    entries = _preflight(config)
    observations = load_observations(config.paths.observations)

    # BLESSED entries are baselines, not merges: they have no predecessor to
    # roll back to. Filtering on kind alone would be enough today; the
    # `blessed` detail check is belt-and-braces against a mislabelled entry.
    merges = [
        e for e in entries if e.kind is ledger.EventKind.MERGED and not e.detail.get("blessed")
    ]
    rolled_back_versions = {
        e.detail.get("archive_version") for e in entries if e.kind is ledger.EventKind.ROLLED_BACK
    }

    lines: list[str] = []
    rolled: list[str] = []
    gated_rollback = False

    # NEWEST FIRST. `archive.rollback(v)` APPENDS v's content as a new
    # version, so reverting in ledger order made each rollback undo the
    # previous one: with v2 and v3 both un-settled, reverting v2 restored the
    # baseline and reverting v3 then restored v2 — reinstating the first
    # regression, having reported both as rolled back. Reverting newest-first
    # unwinds the stack in the order it was built (ADR 0084).
    for merge in sorted(
        merges, key=lambda e: int(e.detail.get("archive_version") or 0), reverse=True
    ):
        version = merge.detail.get("archive_version")
        if version is None or version in rolled_back_versions:
            continue
        measured = merge.detail.get("baseline_pass_rate")
        if measured is None:
            # Unmeasured, so nothing can be concluded about regression. Report
            # it as such: AMBIGUOUS still rolls back (rollback-by-default,
            # ADR 0056) but does NOT halt the loop, because there is no
            # evidence the gates missed anything.
            lines.append(
                f"{merge.proposal_id} (v{version}): no measured pre-merge baseline, so "
                f"regression cannot be judged — reverting without blaming the gates"
            )
            _rollback_merge(config, merge, int(version), now, restore_to, "no measured baseline")
            rolled.append(merge.proposal_id)
            continue

        result = evaluate_window(
            observations,
            baseline_pass_rate=float(measured),
            merged_at=merge.at,
            now=now,
            policy=config.monitor_policy,
        )
        lines.append(f"{merge.proposal_id} (v{version}): {result.verdict.value} — {result.reason}")

        if result.action is not Action.ROLLBACK:
            continue

        _rollback_merge(config, merge, int(version), now, restore_to, result.reason)
        rolled.append(merge.proposal_id)
        if result.verdict is Verdict.REGRESSED:
            gated_rollback = True

    assessment = assess_halt(gated_rollback=gated_rollback)
    if assessment.should_halt:
        _halt(config, at=now, proposal_id="(monitor)", reasons=assessment.reasons)

    return MonitorRun(
        checked=len(merges),
        rolled_back=tuple(rolled),
        halted=assessment.should_halt,
        halt_reasons=assessment.reasons,
        lines=tuple(lines),
        exit_code=EXIT_HALTED if assessment.should_halt else EXIT_OK,
    )


# --------------------------------------------------------------------------
# digest / status
# --------------------------------------------------------------------------


def _rollback_merge(
    config: LoopConfig,
    merge: ledger.LedgerEntry,
    version: int,
    now: datetime,
    restore_to: Path | None,
    reason: str,
) -> None:
    """Restore the state that preceded `version`, not `version` itself.

    `archive.rollback(v)` restores v's CONTENT. Passing the version the merge
    *produced* therefore restored the regressing change — the rollback
    reinstated exactly what it was reverting (ADR 0072). The target is the
    version before it.
    """
    target = version - 1
    existing = archive.versions(config.paths.archive_dir, config.graph_id)
    if target not in existing:
        # Refuse rather than restore the wrong thing. A rollback with no
        # predecessor to return to is a gap in the archive, not a licence to
        # reinstate the change being reverted.
        raise archive.ArchiveError(
            f"cannot roll back {merge.proposal_id}: no archived version {target} preceding "
            f"v{version} for graph {config.graph_id!r}. Archive a blessed baseline before "
            f"enabling any path that merges."
        )

    archive.rollback(
        config.paths.archive_dir,
        config.graph_id,
        target,
        restore_to or (config.paths.root / "restored"),
        recorded_at=now,
        notes=reason,
    )
    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.ROLLED_BACK,
        at=now,
        proposal_id=merge.proposal_id,
        summary=reason,
        detail={"archive_version": version, "restored_version": target},
    )


def digest(
    config: LoopConfig,
    *,
    since: datetime,
    until: datetime,
    owner_edits: int = 0,
    halt_channel_configured: bool = False,
    runs_recorded: int = 0,
) -> Digest:
    # Deliberately NOT behind the kill switch: reading the record of why the
    # loop halted is exactly what you want to do while it is halted.
    entries = ledger.read(config.paths.ledger_dir)
    return build_digest(
        entries,
        since=since,
        until=until,
        owner_edits=owner_edits,
        halt_channel_configured=halt_channel_configured,
        runs_recorded=runs_recorded,
    )


@dataclass(frozen=True)
class Status:
    halted: bool
    halt_reason: str
    ledger_entries: int
    ledger_ok: bool
    ledger_error: str
    archived_versions: tuple[int, ...]
    open_merges: int

    def render(self) -> str:
        lines = [
            f"kill switch : {'ENGAGED — ' + self.halt_reason if self.halted else 'clear'}",
            f"ledger      : {self.ledger_entries} entries, "
            + ("chain verified" if self.ledger_ok else f"BROKEN — {self.ledger_error}"),
            f"archive     : {len(self.archived_versions)} version(s)",
            f"open windows: {self.open_merges} merge(s) not yet settled or rolled back",
        ]
        return "\n".join(lines)


def status(config: LoopConfig) -> Status:
    """Reports rather than raises — `status` is what you run when something
    is wrong, so it must work when the ledger is broken and the loop halted."""
    _check_state_is_outside_the_repo(config)
    switch = config.paths.kill_switch
    entries: tuple[ledger.LedgerEntry, ...] = ()
    ledger_ok, ledger_error = True, ""
    try:
        entries = ledger.read(config.paths.ledger_dir)
    except ledger.LedgerError as exc:
        ledger_ok, ledger_error = False, str(exc)

    merged = {e.detail.get("archive_version") for e in entries if e.kind is ledger.EventKind.MERGED}
    rolled = {
        e.detail.get("archive_version") for e in entries if e.kind is ledger.EventKind.ROLLED_BACK
    }

    return Status(
        halted=switch.engaged,
        halt_reason=switch.reason,
        ledger_entries=len(entries),
        ledger_ok=ledger_ok,
        ledger_error=ledger_error,
        archived_versions=archive.versions(config.paths.archive_dir, config.graph_id),
        open_merges=len(merged - rolled),
    )


def default_digest_window(now: datetime) -> tuple[datetime, datetime]:
    """Q-A4 owner default: weekly."""
    return now - timedelta(days=7), now


def observations_payload(observations: tuple[Observation, ...]) -> list[dict[str, Any]]:
    return [
        {"at": o.at.isoformat(), "passed": o.passed, "cost_tokens": o.cost_tokens}
        for o in observations
    ]


# --------------------------------------------------------------------------
# cycle — the whole loop, once
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleRun:
    harvested: tuple[str, ...] = ()
    proposed: str | None = None
    decision: Decision | None = None
    lines: tuple[str, ...] = ()
    exit_code: int = EXIT_OK
    score: float | None = None  # G3 candidate mean, when the behavioural gates ran
    incumbent_score: float | None = None


def cycle(
    config: LoopConfig,
    *,
    now: datetime,
    workdir: Path,
    runs_dir: Path | None = None,
    corpus_root: Path | None = None,
    graph: Any = None,
    memory: Any = None,
    agent_path: str = DEFAULT_AGENT_PATH,
) -> CycleRun:
    """One turn of the loop: harvest -> propose -> gate -> record.

    **Nothing is pushed and nothing is merged.** The candidate branch is
    created in the local checkout only, which needs no repository permission
    at all — a job with `contents: read` can do it. Pushing is what needs
    write access, and the gate job must never have it (ADR 0057).

    **At most one candidate per turn.** A loop that can emit many per cycle
    can exhaust the rate budget in a single run, and every candidate costs
    N+2 corpus passes to gate.
    """
    entries = _preflight(config)  # kill switch, then ledger chain — in that order
    lines: list[str] = [f"ledger verified: {len(entries)} entr(ies)"]

    harvested: tuple[str, ...] = ()
    if runs_dir is not None and corpus_root is not None and graph is not None:
        from aef.harness.harvest import harvest as _harvest

        outcome = _harvest(runs_dir, corpus_root, graph, now=now)
        harvested = outcome.promoted
        lines.extend(outcome.lines)

    if memory is None:
        lines.append("no memory store configured: nothing to learn from, no candidate")
        return CycleRun(harvested=harvested, lines=tuple(lines))

    from aef.harness.proposer import MemoryEvidence

    evidence = MemoryEvidence.from_store(memory, config.corpus)
    if evidence.excluded:
        lines.append(
            f"{len(evidence.excluded)} memory record(s) excluded as validation/holdout-derived"
        )
    if not evidence.records:
        # The proposer does not speculate. No recorded failures means no
        # hypothesis, which is a legitimate outcome and not an error.
        lines.append("no admissible failure memory: no candidate this cycle")
        return CycleRun(harvested=harvested, lines=tuple(lines))

    # The BASE REF's source, not the working tree's. The candidate branch is
    # built from `base_ref` and the diff is taken against it, so proposing
    # from whatever happens to be checked out laundered every un-proposed
    # working-tree change into the candidate: the rationale said "raising
    # RETRY_BUDGET from 3 to 4" while the diff G0 sized and scanned also
    # carried an `import os` nobody had reasoned about. Reading from the same
    # ref the diff is against makes the artefact judged the artefact proposed
    # (ADR 0078).
    if not config.repo.path_exists_at(config.base_ref, agent_path):
        lines.append(f"no agent source at {agent_path} in {config.base_ref}: no candidate")
        return CycleRun(harvested=harvested, lines=tuple(lines))

    proposals = _build_proposer(config).propose_from_memory(
        evidence,
        proposal_id=f"cycle-{now:%Y%m%dT%H%M%S}",
        path=agent_path,
        source=config.repo.show(config.base_ref, agent_path),
    )
    if not proposals:
        lines.append("the proposer produced nothing from the available evidence")
        return CycleRun(harvested=harvested, lines=tuple(lines))

    proposal = proposals[0]  # at most one candidate per cycle, deliberately
    branch = f"loop/{proposal.id}"
    _materialise_candidate_branch(config, branch, agent_path, proposal.proposed)
    lines.append(
        f"proposed {proposal.id} on local branch {branch} (never pushed; "
        f"proposer={config.proposer})"
    )
    if "[llm proposer fell back" in proposal.rationale:
        lines.append(proposal.rationale[proposal.rationale.index("[llm proposer fell back") :])

    run = gate(config, branch, now=now, workdir=workdir, proposal=proposal)
    lines.append(f"gated: {run.decision.disposition.value} — {run.decision.reason}")

    return CycleRun(
        harvested=harvested,
        proposed=proposal.id,
        decision=run.decision,
        lines=tuple(lines),
        exit_code=run.exit_code,
        score=run.candidate_score,
        incumbent_score=run.incumbent_score,
    )


def _build_proposer(config: LoopConfig) -> Any:
    """The proposer `config.proposer` names (ADR 0122). Both share
    `propose_from_memory(evidence, *, proposal_id, path, source)`; the LLM
    one takes the zone policy and G0's line budget from the same config the
    gates read, so it refuses what they would refuse."""
    from aef.harness.proposer import RuleBasedProposer

    if config.proposer != "llm":
        return RuleBasedProposer()
    from aef.harness.gates.g0_static_safety import DEFAULT_MAX_CHANGED_LINES
    from aef.harness.llm_proposer import LLMProposer

    assert config.proposer_provider is not None and config.proposer_model  # __post_init__
    return LLMProposer(
        provider=config.proposer_provider,
        model=config.proposer_model,
        zone_policy=config.zone_policy,
        max_changed_lines=int(
            config.gate_limits.get("max_changed_lines", DEFAULT_MAX_CHANGED_LINES)
        ),
    )


@dataclass(frozen=True)
class LoopTurn:
    turn: int
    proposed: str | None
    disposition: Disposition | None
    kept: bool
    kept_ref: str  # the kept branch's commit after this turn
    parent_ref: str = ""  # what this turn proposed FROM
    score: float | None = None
    duplicate: bool = False  # tree already in the archive; neither kept nor reverted


@dataclass
class ArchiveMember:
    """One kept candidate, DGM-style (ADR 0121): its score, its parent, and
    how many children have been proposed from it. Children count is the
    novelty term — a member that has spawned many attempts is less worth
    sampling again than one that has spawned none."""

    ref: str
    score: float | None
    parent_ref: str | None
    children: int = 0
    tree: str = ""


@dataclass(frozen=True)
class LoopRun:
    """What `run_loop` did: the autoresearch shape inside the gates (ADR 0114),
    with DGM's archive when `sample_parents` is on (ADR 0121)."""

    turns: tuple[LoopTurn, ...]
    kept_branch: str
    kept_ref: str
    stopped_because: str
    lines: tuple[str, ...]
    archive: tuple[ArchiveMember, ...] = ()

    @property
    def kept_count(self) -> int:
        return sum(1 for t in self.turns if t.kept)

    @property
    def reverted_count(self) -> int:
        return sum(
            1 for t in self.turns if t.proposed is not None and not t.kept and not t.duplicate
        )

    @property
    def distinct_kept_trees(self) -> int:
        return len({m.tree for m in self.archive if m.parent_ref is not None})


class KeptBranchCheckedOutError(RuntimeError):
    """`run_loop` was started while HEAD is the branch it advances.

    The loop moves the kept branch with `update-ref`, which changes where the
    branch points WITHOUT touching the index or the working tree. When that
    branch is also HEAD, the result is a repository whose index disagrees
    with its own HEAD commit: `git status` reads as a staged reversal of the
    change the loop just kept, and the next `git commit` in that checkout
    would undo it. Reproduced, not argued (ADR 0125).

    `update-ref` is deliberate — `merge`/`reset` on the checked-out branch is
    the loop touching a person's working tree, which ADR 0114 refuses. So the
    refusal is the fix: the reviewer stands somewhere else.
    """


def _refuse_if_kept_branch_is_checked_out(config: LoopConfig, kept_branch: str) -> None:
    head = config.repo.run("rev-parse", "--abbrev-ref", "HEAD").strip()
    if head != kept_branch:
        return
    raise KeptBranchCheckedOutError(
        f"HEAD is {kept_branch!r}, the branch this loop advances with update-ref — "
        f"which would leave your index reading as a staged reversal of whatever the "
        f"loop keeps. Check out another branch first "
        f"(e.g. `git checkout {config.base_ref}`) and re-run; {kept_branch} is for "
        f"reviewing, and `git log {kept_branch}` reads it without standing on it."
    )


def _ensure_branch(config: LoopConfig, branch: str) -> str:
    try:
        return config.repo.rev_parse(branch)
    except Exception:  # noqa: BLE001 - "no such ref" is the only thing we act on
        config.repo.run("branch", branch, config.base_ref)
        return config.repo.rev_parse(branch)


def _tree_of(config: LoopConfig, ref: str) -> str:
    return config.repo.run("rev-parse", f"{ref}^{{tree}}").strip()


def _parent_weight(member: ArchiveMember) -> float:
    """DGM's sampling rule in miniature: a sigmoid of the score, scaled by
    1/(1+children). A member with no score yet (the root, before anything
    was gated against it) weighs as a 0.5."""
    score = 0.5 if member.score is None else member.score
    fitness = 1.0 / (1.0 + math.exp(-10.0 * (score - 0.5)))
    return fitness / (1.0 + member.children)


def _choose_parent(archive: list[ArchiveMember], rng: random.Random) -> ArchiveMember:
    weights = [_parent_weight(m) for m in archive]
    return rng.choices(archive, weights=weights, k=1)[0]


def run_loop(
    config: LoopConfig,
    *,
    now: datetime,
    workdir: Path,
    turns: int,
    budget_seconds: float,
    kept_branch: str = "loop/kept",
    clock: Callable[[], float] = time.monotonic,
    cycle_fn: Callable[..., CycleRun] | None = None,
    sample_parents: bool = False,
    seed: int = 0,
    **cycle_kwargs: Any,
) -> LoopRun:
    """Keep/revert on the metric, inside the gates (ADR 0114).

    autoresearch's loop is: propose, measure, keep if better, else revert,
    repeat until the budget is spent. This is that loop with the gates as
    the measurement and one deliberate difference: **"keep" advances a
    LOCAL branch, never `main`.** Every gate passing means the candidate
    beat the null cohort on the task metric with zero per-scenario
    regression (G3) — and `decide()` still returns ESCALATE, because
    Tier-1 auto-merge is off and stays off. The kept branch is what a person
    reviews and merges; what the loop gains is that the next proposal is
    made FROM the kept state, so improvements stack instead of each cycle
    re-proposing from the same base.

    With `sample_parents` (ADR 0121) the next proposal is made from a parent
    SAMPLED from the archive of everything kept so far — weighted by score
    and against how many children it already has — rather than always from
    the latest kept. Stepping stones survive; the kept branch points at the
    best-scoring member. Off by default: measured, not assumed.

    Stops on: the turn count, the wall-clock budget, a halt, a turn that
    produced no candidate, or a candidate whose tree matches one already
    rejected in this run — the proposer is deterministic from its evidence,
    so re-gating the same rejected diff would spend N+2 corpus passes to
    learn nothing. A candidate whose tree matches one already KEPT is a
    duplicate: neither kept nor reverted, and the loop continues, because a
    different parent may produce something new.
    """
    _cycle = cycle if cycle_fn is None else cycle_fn
    started = clock()
    rng = random.Random(seed)
    # BEFORE anything is created or gated: standing on the kept branch makes
    # every `update-ref` below leave a staged reversal behind (ADR 0125).
    _refuse_if_kept_branch_is_checked_out(config, kept_branch)
    kept_ref = _ensure_branch(config, kept_branch)
    main_before = config.repo.rev_parse(config.base_ref)
    root = ArchiveMember(ref=kept_ref, score=None, parent_ref=None, tree=_tree_of(config, kept_ref))
    archive: list[ArchiveMember] = [root]
    lines: list[str] = [f"kept branch {kept_branch} at {kept_ref[:12]} (from {config.base_ref})"]
    rejected_trees: set[str] = set()
    done: list[LoopTurn] = []
    stopped_because = f"turn budget of {turns} exhausted"
    for turn in range(1, turns + 1):
        elapsed = clock() - started
        if elapsed > budget_seconds:
            stopped_because = (
                f"wall-clock budget of {budget_seconds:.0f}s exceeded after {turn - 1} turn(s)"
            )
            break
        parent = _choose_parent(archive, rng) if sample_parents else archive[-1]
        parent.children += 1
        turn_config = replace(config, base_ref=parent.ref)
        # A scratch dir PER TURN. G1 materialises the candidate into
        # `workdir/workspace` and `trust._prepare_empty_destination` refuses a
        # non-empty one — so with one workdir for the whole run, every turn
        # after the first was rejected by G1 with a TrustBoundaryError before
        # any behavioural gate ran, whatever the proposer had done. Found by
        # RUNNING the I10 measurement (ADR 0122): the "turn 2 rejected" in
        # ADR 0114's and 0121's runs was this, not G3.
        run = _cycle(
            turn_config,
            now=now + timedelta(seconds=turn),
            workdir=workdir / f"turn-{turn}",
            **cycle_kwargs,
        )
        lines.extend(f"turn {turn}: {line}" for line in run.lines)
        if run.proposed is None:
            done.append(LoopTurn(turn, None, None, False, kept_ref, parent.ref))
            stopped_because = f"turn {turn} produced no candidate"
            break
        candidate_branch = f"loop/{run.proposed}"
        disposition = run.decision.disposition if run.decision else None
        passed = disposition in (Disposition.ESCALATE, Disposition.AUTO_MERGE)
        tree = _tree_of(config, candidate_branch)
        if any(m.tree == tree for m in archive):
            done.append(
                LoopTurn(
                    turn, run.proposed, disposition, False, kept_ref, parent.ref, run.score, True
                )
            )
            lines.append(f"turn {turn}: duplicate of a kept tree from {parent.ref[:12]}; skipped")
            continue
        if passed and run.exit_code != EXIT_HALTED:
            candidate_ref = config.repo.rev_parse(candidate_branch)
            if root.score is None and run.incumbent_score is not None:
                root.score = run.incumbent_score
            member = ArchiveMember(
                ref=candidate_ref, score=run.score, parent_ref=parent.ref, tree=tree
            )
            archive.append(member)
            # The kept branch points at the best-scoring member (greedy mode:
            # always the newest, since each is proposed from the last).
            best = max(
                (m for m in archive if m.parent_ref is not None),
                key=lambda m: (m.score if m.score is not None else -1.0, m.ref),
            )
            if sample_parents:
                target = best.ref
            else:
                target = candidate_ref
            config.repo.run("update-ref", f"refs/heads/{kept_branch}", target, kept_ref)
            kept_ref = target
            ledger.append(
                config.paths.ledger_dir,
                kind=ledger.EventKind.KEPT,
                at=now + timedelta(seconds=turn),
                proposal_id=run.proposed,
                summary=f"every gate passed; {kept_branch} -> {kept_ref[:12]} (not main)",
                detail={
                    "turn": turn,
                    "kept_branch": kept_branch,
                    "kept_ref": kept_ref,
                    "candidate_ref": candidate_ref,
                    "parent_ref": parent.ref,
                    "score": run.score,
                    "incumbent_score": run.incumbent_score,
                },
            )
            lines.append(
                f"turn {turn}: KEPT {candidate_ref[:12]} from {parent.ref[:12]} "
                f"(score {run.score}); {kept_branch}@{kept_ref[:12]}"
            )
            done.append(
                LoopTurn(turn, run.proposed, disposition, True, kept_ref, parent.ref, run.score)
            )
        else:
            done.append(
                LoopTurn(turn, run.proposed, disposition, False, kept_ref, parent.ref, run.score)
            )
            lines.append(
                f"turn {turn}: reverted ({disposition.value if disposition else 'halted'})"
            )
            if run.exit_code == EXIT_HALTED:
                stopped_because = f"halted at turn {turn}"
                break
            if tree in rejected_trees:
                stopped_because = (
                    f"turn {turn} re-proposed a tree already rejected in this run; "
                    "the proposer has nothing new"
                )
                break
            rejected_trees.add(tree)
    if config.repo.rev_parse(config.base_ref) != main_before:  # pragma: no cover - invariant
        raise RuntimeError(f"{config.base_ref} moved during run_loop; this must never happen")
    lines.append(f"stopped: {stopped_because}")
    return LoopRun(
        turns=tuple(done),
        kept_branch=kept_branch,
        kept_ref=kept_ref,
        stopped_because=stopped_because,
        lines=tuple(lines),
        archive=tuple(archive),
    )


def _materialise_candidate_branch(config: LoopConfig, branch: str, path: str, content: str) -> None:
    """Create the candidate as a LOCAL branch. Never pushed.

    The starting position is recorded as a SHA, not a branch name.
    `rev-parse --abbrev-ref HEAD` returns the literal string `"HEAD"` on a
    detached checkout — which is the normal CI shape, since
    `actions/checkout` with a ref or SHA detaches — so the restore was
    `git checkout HEAD`, a no-op, and the job was left standing on the
    candidate branch with an un-gated mutation in its working tree. The next
    cycle then read that mutation as its starting point and proposed on top
    of it while still diffing against the base (ADR 0078).
    """
    # The branch name when there is one, so an owner running this on `main`
    # is put back on `main` rather than left detached; the SHA otherwise.
    symbolic = config.repo.run("rev-parse", "--abbrev-ref", "HEAD").strip()
    original = symbolic if symbolic != "HEAD" else config.repo.run("rev-parse", "HEAD").strip()
    config.repo.run("checkout", "-q", "-B", branch, config.base_ref)
    try:
        target = config.repo.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        config.repo.run("add", "--", path)
        config.repo.run(
            "-c",
            "user.email=loop@aef",
            "-c",
            "user.name=aef-loop",
            "commit",
            "-q",
            "-m",
            f"loop: {branch}",
        )
    finally:
        # `--force` because the candidate content is committed on the branch
        # by this point; without it a leftover working-tree difference would
        # abort the restore and strand the caller on the candidate.
        config.repo.run("checkout", "-q", "--force", original)
