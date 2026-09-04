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

**Rate-limited, and the limit counts HARVEST's own promotions only.** One bad
deploy can produce thousands of failing runs; without a limit the corpus fills
with a single incident and the gates start measuring that incident instead of
the agent. That is a statement about what *this* command writes — and the
first version counted every scenario recorded in the last 24 hours, whoever
wrote it. `aef loop bootstrap` stamps `recorded_at = now` on every scenario it
records, so the K5 pilot sequence (adopt, bootstrap, run for real, harvest)
silently dropped every real production failure: bootstrap 12 inputs, harvest 3
real runs, `promoted 0 run(s)`, `3 held back by the daily rate limit`, exit 0
(reproduced, ADR 0141). `Scenario.source` now says who wrote each one and only
`Source.HARVEST` is charged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aef.harness.corpus import (
    Expected,
    Scenario,
    Source,
    Split,
    load_corpus,
    save_scenario,
)
from aef.harness.corpus import fixed_clock as _fixed_clock
from aef.harness.outcome import is_recovered
from aef.harness.redaction import RedactionPolicy
from aef.harness.trace_codec import decode_trace, dumps, encode_trace, loads
from aef.kernel import GraphExecutor, Services
from aef.kernel.executor import NodeExecutionRecord
from aef.kernel.graph import Graph
from aef.providers.cassette_provider import CassetteProvider, RecordedCall
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState

DEFAULT_DAILY_LIMIT = 5
# On by default: the corpus lives in git (ADR 0119). `redaction=None` turns it off.
DEFAULT_REDACTION = RedactionPolicy()


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
    # Every model completion the run made (ADR 0123's cassette, ADR 0126).
    # Without these a run whose graph calls a model cannot re-execute at all:
    # the determinism re-check runs with no credential, the call fails, and
    # the run is rejected as non-deterministic — a correct-looking rejection
    # for the wrong reason. Empty for a legacy recorded run and for any graph
    # that never asked a model anything, exactly as `Scenario.model_calls` is.
    model_calls: tuple[RecordedCall, ...] = ()

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
            "model_calls": [call.to_payload() for call in self.model_calls],
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
                # Legacy runs recorded before the cassette existed load with
                # none, and behave exactly as they did.
                model_calls=tuple(
                    RecordedCall.from_payload(c) for c in payload.get("model_calls", ())
                ),
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
    # Redaction (ADR 0119): the run's behaviour depended on something the
    # redactor removed, or a secret survived into the scenario that would
    # have been written. Neither is recorded.
    rejected_redaction_changed_behaviour: tuple[str, ...] = ()
    rejected_unredactable: tuple[str, ...] = ()
    redactions: int = 0
    # What the rate limit was and what had already spent it. "held back by the
    # daily rate limit" named a rule and no arithmetic, so a run held back by a
    # budget something ELSE had consumed read exactly like one held back by
    # harvest's own volume (ADR 0141).
    daily_limit: int = DEFAULT_DAILY_LIMIT
    harvested_today: int = 0
    other_sources_today: tuple[tuple[str, int], ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        out: list[str] = [f"promoted {len(self.promoted)} run(s) to the train split"]
        for label, items in (
            ("already in the corpus", self.skipped_existing),
            ("passed, not promoted", self.skipped_passing),
            ("REJECTED, did not re-execute deterministically", self.rejected_nondeterministic),
            ("held back by the daily rate limit", self.skipped_rate_limited),
            (
                "REJECTED, behaviour changed under redaction",
                self.rejected_redaction_changed_behaviour,
            ),
            ("REJECTED, a secret survived redaction", self.rejected_unredactable),
        ):
            if items:
                out.append(f"  {len(items)} {label}: {', '.join(sorted(items)[:5])}")
            if items and label.startswith("held back"):
                out.append(
                    f"      the limit is {self.daily_limit} HARVESTED scenario(s) per 24h; "
                    f"{self.harvested_today} had been harvested before this run and "
                    f"{len(self.promoted)} were promoted by it"
                )
                if self.other_sources_today:
                    spent = ", ".join(
                        f"{count} from {name}" for name, count in self.other_sources_today
                    )
                    out.append(
                        f"      ({spent} today, which do NOT count against it — "
                        f"the limit is on this command's own promotions, ADR 0141)"
                    )
        if self.redactions:
            out.append(f"  {self.redactions} substitution(s) made by the redaction policy")
        return tuple(out)


def _reexecution_services(scenario: Scenario) -> Services:
    """Mirrors `scenario_runner.run_scenario` — harvest asks the same
    question the gates do, so it has to ask it of the same environment.

    That includes the cassette (ADR 0126). The clock was pinned here and the
    model was not, so a harvested run whose graph calls a model re-executed
    against no provider at all, failed, and was rejected as
    "non-deterministic" — the rejection a flaky run gets, for a run that was
    perfectly reproducible. `on_miss="fail"` and no live provider, because a
    harvest that reaches the network to decide whether a run is deterministic
    has already lost the property it is checking.
    """
    cassette = CassetteProvider(None, scenario.model_calls, on_miss="fail")
    return agent_services(
        clock=_fixed_clock(scenario),
        memory=InMemoryMemoryStore(),
        model_provider=cassette,
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
        model_calls=run.model_calls,
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


def _reexecute(
    state: AEFState, run: RecordedRun, graph: Graph
) -> tuple[NodeExecutionRecord, ...] | None:
    """Trace of re-running `graph` on `state` under the run's recorded clock,
    or None if it failed to run at all."""
    scenario = Scenario(
        id=run.run_id,
        split=Split.TRAIN,
        graph_id=run.graph_id,
        graph_version=run.graph_version,
        initial_state=state,
        trace=run.trace,
        recorded_at=run.at,
        model_calls=run.model_calls,
    )
    try:
        result = GraphExecutor(graph.compile(), _reexecution_services(scenario)).run(
            state, record_trace=True
        )
    except Exception:  # noqa: BLE001 - any failure to reproduce is a rejection
        return None
    return result.trace


def _scannable(scenario: Scenario) -> dict[str, Any]:
    """The scenario payload the output scan reads: everything except the
    cassette's own request digests.

    A `RecordedCall.key` is a 64-character SHA-256 hex string the harness
    computes from the request — it is not tenant text, it is recomputed on
    load rather than trusted, and it matches `opaque_secret` every single
    time. Left in, it rejected EVERY model-calling run as
    "a secret survived redaction" (found while fixing ADR 0126's F12; the
    twenty summary scenarios ADR 0123 recorded all match it too). Everything
    a model was actually asked and answered is still scanned.
    """
    payload = scenario.to_payload()
    calls = payload.get("model_calls")
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict):
                call.pop("key", None)
    return payload


def _behaviour(initial: AEFState, trace: tuple[NodeExecutionRecord, ...]) -> tuple[Any, ...]:
    """What must survive redaction for the scenario to still be the same
    failure: the node path, which nodes errored, and the plan's status.
    Text is allowed to differ — that is what redaction changes."""
    final = initial
    for record in trace:
        final = record.delta.apply(final)
    failing = tuple(e.get("node_id") for e in final.errors if not is_recovered(e))
    status = final.plan.status if final.plan is not None else None
    return (tuple(r.node_id for r in trace), failing, status)


def harvest(
    runs_dir: Path,
    corpus_root: Path,
    graph: Graph,
    *,
    now: datetime,
    include_successes: bool = False,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
    redaction: RedactionPolicy | None = DEFAULT_REDACTION,
) -> HarvestOutcome:
    """`redaction` is ON by default and `None` turns it off explicitly — the
    corpus lives in git, and a harvest that writes tenant text unless told
    not to is the wrong default (ADR 0119)."""
    corpus = load_corpus(corpus_root) if corpus_root.is_dir() else None
    existing = {s.id for s in corpus.scenarios} if corpus else set()

    cutoff = now - timedelta(days=1)
    # HARVEST's own promotions only. A scenario `bootstrap` or `record`
    # wrote today is not this command filling the corpus with one incident,
    # and charging it here dropped every real run of the K5 pilot sequence
    # (ADR 0141).
    recent = tuple(s for s in corpus.scenarios if s.recorded_at > cutoff) if corpus else ()
    already_today = sum(1 for s in recent if s.source is Source.HARVEST)
    others_today = {
        source: sum(1 for s in recent if s.source is source)
        for source in (Source.BOOTSTRAP, Source.RECORD, Source.UNSPECIFIED)
    }
    budget = max(daily_limit - already_today, 0)

    promoted: list[str] = []
    passing: list[str] = []
    duplicate: list[str] = []
    flaky: list[str] = []
    limited: list[str] = []
    changed: list[str] = []
    unredactable: list[str] = []
    substitutions = 0

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

        initial_state, trace = run.initial_state, run.trace
        notes = "harvested from a real run; re-execution verified"
        if redaction is not None:
            redacted_state, count = redaction.redact_state(run.initial_state)
            if count:
                # Redact the input, re-execute, keep THAT trace — never patch
                # the recorded one. Admit only if the failure is the same
                # failure; text may differ, behaviour may not.
                redacted_trace = _reexecute(redacted_state, run, graph)
                if redacted_trace is None or _behaviour(
                    redacted_state, redacted_trace
                ) != _behaviour(run.initial_state, run.trace):
                    changed.append(run.run_id)
                    continue
                initial_state, trace = redacted_state, redacted_trace
                notes += f"; {count} redaction(s) applied to the input before re-execution"
                substitutions += count
        scenario = Scenario(
            id=run.run_id,
            split=Split.TRAIN,
            graph_id=run.graph_id,
            graph_version=run.graph_version,
            initial_state=initial_state,
            trace=trace,
            recorded_at=run.at,
            notes=notes,
            # The cassette travels with the scenario, or the gates that
            # re-execute it hit the same wall harvest just cleared.
            model_calls=run.model_calls,
            # Harvested runs carry NO owner claim. Only a human can say a
            # task should have failed, and a MUST_FAIL label invented by
            # the system would be a tripwire the system set for itself.
            expected=Expected.UNSPECIFIED,
            # Provenance, so this command's rate limit charges this command
            # and nothing else (ADR 0141).
            source=Source.HARVEST,
        )
        # The output scan: a secret that survived the input redaction came
        # from somewhere the redactor cannot reach. Rejected, not written.
        if redaction is not None and redaction.find(_scannable(scenario)):
            unredactable.append(run.run_id)
            continue
        save_scenario(corpus_root, scenario)
        promoted.append(run.run_id)

    return HarvestOutcome(
        daily_limit=daily_limit,
        harvested_today=already_today,
        other_sources_today=tuple(
            (source.value, count) for source, count in others_today.items() if count
        ),
        promoted=tuple(promoted),
        skipped_passing=tuple(passing),
        skipped_existing=tuple(duplicate),
        rejected_nondeterministic=tuple(flaky),
        skipped_rate_limited=tuple(limited),
        rejected_redaction_changed_behaviour=tuple(changed),
        rejected_unredactable=tuple(unredactable),
        redactions=substitutions,
    )
