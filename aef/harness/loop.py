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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aef.harness import archive, ledger
from aef.harness.candidate import inspect_candidate
from aef.harness.corpus import Corpus
from aef.harness.gates.base import Gate, GateContext, PipelineResult, run_pipeline
from aef.harness.gates.g0_static_safety import G0StaticSafety
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.gates.g2_outcome import G2OutcomeNonRegression
from aef.harness.gates.g3_improvement import G3Improvement
from aef.harness.gates.g4_separation import G4SeparationOfPowers
from aef.harness.gates.g5_rate_drift import G5RateAndDrift
from aef.harness.git import GitRepo
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
from aef.harness.review import Decision, Disposition, decide, render_report
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.harness.zones import ZonePolicy

OBSERVATIONS_FILENAME = "observations.jsonl"

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_HALTED = 2


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
    gates: tuple[Gate, ...] | None = None

    def sandbox_policy(self) -> SandboxPolicy:
        if self.network_isolated:
            return SandboxPolicy(
                network=NetworkPolicy.REQUIRE_ISOLATED, network_isolation_attested=True
            )
        return SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)

    def default_gates(self) -> tuple[Gate, ...]:
        """All six, always registered.

        A gate with no evidence configured **fails** rather than being
        omitted — G2 without a corpus, G3 without a control cohort, G5
        without a blessed baseline all refuse. Omitting them instead would
        make a candidate look gated when it was not.
        """
        return (
            G0StaticSafety(),
            G1Builds(),
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


def _preflight(config: LoopConfig) -> tuple[ledger.LedgerEntry, ...]:
    """State location, kill switch, then ledger integrity. In that order.

    The kill switch check comes before any work, but after the location
    check: a state directory in the wrong place means the kill switch itself
    is inside the repo, so its answer cannot be trusted.
    """
    _check_state_is_outside_the_repo(config)
    config.paths.kill_switch.check()  # raises LoopHaltedError
    return ledger.read(config.paths.ledger_dir)


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


def gate(config: LoopConfig, head_ref: str, *, now: datetime, workdir: Path) -> GateRun:
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
        repo=config.repo,
        base_ref=config.base_ref,
        head_ref=head_ref,
        verdict=verdict,
        workdir=workdir,
        zone_policy=config.zone_policy,
        sandbox_policy=config.sandbox_policy(),
    )
    result = run_pipeline(config.gates or config.default_gates(), ctx)

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
            "security_event": bool(result.security_events),
        },
    )

    decision = decide(result, tier1_enabled=config.tier1_enabled)
    report = _render(config, head_ref, proposal_id, result, decision)

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
        return GateRun(decision=decision, result=result, report=report, exit_code=EXIT_REJECTED)

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
        return GateRun(decision=decision, result=result, report=report, exit_code=EXIT_OK)

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
        detail={"archive_version": archived.version, "baseline_pass_rate": 1.0},
    )
    return GateRun(decision=decision, result=result, report=report, exit_code=EXIT_OK)


def _render(
    config: LoopConfig,
    head_ref: str,
    proposal_id: str,
    result: PipelineResult,
    decision: Decision,
) -> str:
    """Render a report for a candidate BRANCH.

    `gate` judges a branch, which may not have come from this repo's proposer
    at all, so there is no `Proposal` object to render. The diff is taken
    from git rather than left as a placeholder — a report whose evidence
    section says "see the diff elsewhere" is the rubber stamp M9's ordering
    was designed to prevent, just with an extra step.
    """
    from aef.harness.proposer import Proposal

    try:
        diff = config.repo.run("diff", f"{config.base_ref}...{head_ref}")
    except Exception:  # noqa: BLE001 - a missing diff must not lose the report
        diff = f"(could not render a diff for {proposal_id})\n"

    stub = Proposal(
        id=proposal_id,
        path="(candidate branch)",
        original="",
        proposed=diff or "(empty diff)\n",
        rationale=f"candidate branch {proposal_id}",
        grounded_in=(),
        is_control=True,  # exempts the stub from the grounding requirement
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

    merges = [e for e in entries if e.kind is ledger.EventKind.MERGED]
    rolled_back_versions = {
        e.detail.get("archive_version") for e in entries if e.kind is ledger.EventKind.ROLLED_BACK
    }

    lines: list[str] = []
    rolled: list[str] = []
    gated_rollback = False

    for merge in merges:
        version = merge.detail.get("archive_version")
        if version is None or version in rolled_back_versions:
            continue
        result = evaluate_window(
            observations,
            baseline_pass_rate=float(merge.detail.get("baseline_pass_rate", 1.0)),
            merged_at=merge.at,
            now=now,
            policy=config.monitor_policy,
        )
        lines.append(f"{merge.proposal_id} (v{version}): {result.verdict.value} — {result.reason}")

        if result.action is not Action.ROLLBACK:
            continue

        archive.rollback(
            config.paths.archive_dir,
            config.graph_id,
            int(version),
            restore_to or (config.paths.root / "restored"),
            recorded_at=now,
            notes=result.reason,
        )
        ledger.append(
            config.paths.ledger_dir,
            kind=ledger.EventKind.ROLLED_BACK,
            at=now,
            proposal_id=merge.proposal_id,
            summary=result.reason,
            detail={"archive_version": version, "verdict": result.verdict.value},
        )
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


def digest(config: LoopConfig, *, since: datetime, until: datetime, owner_edits: int = 0) -> Digest:
    # Deliberately NOT behind the kill switch: reading the record of why the
    # loop halted is exactly what you want to do while it is halted.
    entries = ledger.read(config.paths.ledger_dir)
    return build_digest(entries, since=since, until=until, owner_edits=owner_edits)


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
