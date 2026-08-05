"""Corpus auto-growth — promoting real runs into scenarios.

A static corpus stops binding as behaviour moves. Every gate is measured
against it, so a corpus that never grows quietly becomes a test of what the
agent used to do.

Four decisions, each of which the obvious alternative gets wrong.

**Failures are promoted automatically; successes only on request.** Failures
carry the information. Auto-promoting successes inflates the pass rate the
gates measure against, so the corpus drifts toward "everything passes" — and
a corpus where everything already passes cannot demonstrate an improvement.

**Always TRAIN. Never validation, never holdout, and no flag to override.**
If production could write to validation, the set that gates candidates would
be shaped by the same system being gated. The holdout is the owner's, and
`recorder.py` already refuses it without explicit consent; here there is not
even a way to ask.

**A run that does not re-execute deterministically is REJECTED, not
recorded.** A flaky scenario makes every downstream gate unreliable, and one
admitted flake poisons every future comparison — the cost is not one bad
scenario, it is a corpus nobody can trust.

**Rate-limited.** One bad deploy can produce thousands of failing runs;
without a limit the corpus fills with a single incident and the gates start
measuring that incident instead of the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aef.harness.corpus import (
    Expected,
    Scenario,
    Split,
    load_corpus,
    save_scenario,
)
from aef.harness.corpus import fixed_clock as _fixed_clock
from aef.harness.outcome import is_recovered
from aef.harness.scenario_runner import DEFAULT_RUBRIC
from aef.harness.trace_codec import decode_trace, dumps, encode_trace, loads
from aef.kernel import GraphExecutor, Services
from aef.kernel.executor import NodeExecutionRecord
from aef.kernel.graph import Graph
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.security.tool import PolicyEngine
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

DEFAULT_DAILY_LIMIT = 5


class HarvestError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordedRun:
    """A production run, captured completely enough to become a scenario."""

    run_id: str
    graph_id: str
    graph_version: str
    initial_state: AEFState
    trace: tuple[NodeExecutionRecord, ...]
    at: datetime

    @property
    def failed(self) -> bool:
        """Did this run fail, as opposed to recovering from something?

        Errors the agent explicitly marked recovered do not count. Before
        that distinction existed, harvest promoted every recovered run into
        the corpus as a failure — so the corpus recorded successful recovery
        as the thing the loop should learn to stop doing (ADR 0076).
        """
        final = self.initial_state
        for record in self.trace:
            final = record.delta.apply(final)
        unrecovered = [e for e in final.errors if not is_recovered(e)]
        return bool(unrecovered) or (final.plan is not None and final.plan.status == "failed")

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "initial_state": self.initial_state.model_dump(mode="json"),
            "trace": encode_trace(self.trace),
            "at": self.at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RecordedRun:
        try:
            return cls(
                run_id=payload["run_id"],
                graph_id=payload["graph_id"],
                graph_version=payload["graph_version"],
                initial_state=AEFState.model_validate(payload["initial_state"]),
                trace=decode_trace(payload["trace"]),
                at=datetime.fromisoformat(payload["at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HarvestError(f"malformed recorded run: {exc}") from exc


def save_run(root: Path, run: RecordedRun) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run.run_id}.json"
    path.write_text(dumps(run.to_payload()))
    return path


def load_runs(root: Path) -> tuple[RecordedRun, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        RecordedRun.from_payload(loads(p.read_text())) for p in sorted(root.glob("*.json"))
    )


@dataclass(frozen=True)
class HarvestOutcome:
    promoted: tuple[str, ...] = ()
    skipped_passing: tuple[str, ...] = ()
    skipped_existing: tuple[str, ...] = ()
    rejected_nondeterministic: tuple[str, ...] = ()
    skipped_rate_limited: tuple[str, ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        out: list[str] = [f"promoted {len(self.promoted)} run(s) to the train split"]
        for label, items in (
            ("already in the corpus", self.skipped_existing),
            ("passed, not promoted", self.skipped_passing),
            ("REJECTED, did not re-execute deterministically", self.rejected_nondeterministic),
            ("held back by the daily rate limit", self.skipped_rate_limited),
        ):
            if items:
                out.append(f"  {len(items)} {label}: {', '.join(sorted(items)[:5])}")
        return tuple(out)


def _reexecution_services(scenario: Scenario) -> Services:
    """Mirrors `scenario_runner.run_scenario` — harvest asks the same
    question the gates do, so it has to ask it of the same environment."""
    return Services(
        clock=_fixed_clock(scenario),
        memory=InMemoryMemoryStore(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric=dict(DEFAULT_RUBRIC)),
        policy_engine=PolicyEngine(),
    )


def _reexecutes_identically(run: RecordedRun, graph: Graph) -> bool:
    """Re-run from the recorded initial state with the recorded clock.

    A scenario that does not reproduce is worse than no scenario: every gate
    downstream compares against it, so one admitted flake makes every future
    comparison unreliable.
    """
    scenario = Scenario(
        id=run.run_id,
        split=Split.TRAIN,
        graph_id=run.graph_id,
        graph_version=run.graph_version,
        initial_state=run.initial_state,
        trace=run.trace,
        recorded_at=run.at,
    )
    try:
        # The same services the gate runner supplies. A bare `Services()`
        # here made every reflect-node or policy-gated agent fail the
        # determinism re-check for a missing service rather than for
        # non-determinism, so harvest silently promoted nothing (ADR 0079).
        result = GraphExecutor(graph.compile(), _reexecution_services(scenario)).run(
            run.initial_state, record_trace=True
        )
    except Exception:  # noqa: BLE001 - any failure to reproduce is a rejection
        return False
    if result.trace is None:
        return False
    return dumps(encode_trace(result.trace)) == dumps(encode_trace(run.trace))


def harvest(
    runs_dir: Path,
    corpus_root: Path,
    graph: Graph,
    *,
    now: datetime,
    include_successes: bool = False,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
) -> HarvestOutcome:
    corpus = load_corpus(corpus_root) if corpus_root.is_dir() else None
    existing = {s.id for s in corpus.scenarios} if corpus else set()

    cutoff = now - timedelta(days=1)
    already_today = sum(1 for s in corpus.scenarios if s.recorded_at > cutoff) if corpus else 0
    budget = max(daily_limit - already_today, 0)

    promoted: list[str] = []
    passing: list[str] = []
    duplicate: list[str] = []
    flaky: list[str] = []
    limited: list[str] = []

    for run in load_runs(runs_dir):
        if run.run_id in existing:
            duplicate.append(run.run_id)
            continue
        if not run.failed and not include_successes:
            passing.append(run.run_id)
            continue
        if len(promoted) >= budget:
            limited.append(run.run_id)
            continue
        if not _reexecutes_identically(run, graph):
            flaky.append(run.run_id)
            continue

        save_scenario(
            corpus_root,
            Scenario(
                id=run.run_id,
                split=Split.TRAIN,
                graph_id=run.graph_id,
                graph_version=run.graph_version,
                initial_state=run.initial_state,
                trace=run.trace,
                recorded_at=run.at,
                notes="harvested from a real run; re-execution verified",
                # Harvested runs carry NO owner claim. Only a human can say a
                # task should have failed, and a MUST_FAIL label invented by
                # the system would be a tripwire the system set for itself.
                expected=Expected.UNSPECIFIED,
            ),
        )
        promoted.append(run.run_id)

    return HarvestOutcome(
        promoted=tuple(promoted),
        skipped_passing=tuple(passing),
        skipped_existing=tuple(duplicate),
        rejected_nondeterministic=tuple(flaky),
        skipped_rate_limited=tuple(limited),
    )
