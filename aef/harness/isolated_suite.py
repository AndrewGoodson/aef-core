"""Scoring a variant with the candidate's code in a process of its own.

This replaces the arrangement where a subprocess ran the corpus and PRINTED
the results. That contract made the candidate the author of the evidence
judging it, and three attempts to secure the channel were each defeated
(ADR 0085, 0088, 0093) — because the candidate's code and the reporting code
shared an interpreter.

Here the parent owns everything except the node bodies: it drives the graph,
applies the deltas, counts the steps, records the trace, classifies the
outcome and computes the score. The candidate's process is asked one question
at a time and never learns what a scenario is (ADR 0094).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aef.harness.corpus import Scenario, fixed_clock
from aef.harness.evaluation import score_of, score_scenario
from aef.harness.isolated import IsolationError, NodeWorkerSession, graph_from
from aef.harness.outcome import Outcome, classify
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.harness.scenario_runner import policy_payload
from aef.kernel import GraphExecutor
from aef.security.tool import PolicyConfig
from aef.services.runtime import agent_services


@dataclass(frozen=True)
class ScenarioResult:
    """What the PARENT concluded. The candidate contributed node bodies."""

    outcome: Outcome
    score: float
    cost_tokens: int
    failure: str | None = None


def _worker_env(workspace: Path) -> dict[str, str]:
    """The only thing the worker needs beyond the sandbox's own allowlist.

    Previously this hand-rolled the whole environment, which meant the
    sandbox's `env_allowlist` — the thing that decides what a candidate can
    read a credential out of — did not apply to the process running candidate
    code (ADR 0095). `SandboxPolicy` supplies the environment now; this adds
    the import path and nothing else.

    The workspace first, then the directory THIS `aef` was imported from.
    The parent and the worker speak a framed protocol, and both ends have to
    be the same version of it: with only the workspace on the path, a
    checkout whose venv resolves `aef` to a different tree (an editable
    install pointing at another worktree, found while adding the cassette
    frame in ADR 0123) ran the parent's protocol against a worker that had
    never heard of it, and every scenario failed as "previously passing, no
    longer passes". The workspace still wins when it carries its own `aef`.
    """
    import aef

    harness_root = Path(aef.__file__).resolve().parent.parent
    return {"PYTHONPATH": os.pathsep.join((str(workspace), str(harness_root)))}


def run_corpus_isolated(
    workspace: Path,
    scenarios: list[Scenario] | tuple[Scenario, ...],
    *,
    entrypoint: str,
    policy: PolicyConfig | None = None,
    sandbox: SandboxPolicy | None = None,
    step_timeout_s: float | None = None,
    cassette_miss: str = "fail",
    live_provider: dict[str, str] | None = None,
) -> dict[str, ScenarioResult]:
    """Execute every scenario, concluding in this process.

    Each scenario's recorded model calls are handed to the worker before its
    nodes run (ADR 0123). `cassette_miss="fail"` — the default — makes a
    request the recording never saw a failed node, so the gate is
    deterministic and holds no credential. `"live"` sends misses to a
    provider the worker builds from `live_provider` (`{"impl", "model"}`,
    read by the caller from the BASE REF's config, never the workspace's).

    One worker for the whole corpus: a fresh process per scenario would make
    module-level agent state behave differently under the gate than it does
    in production, and the gate is meant to re-execute what was recorded.

    A worker that dies takes the rest of the corpus with it, and every
    remaining scenario is recorded as a failure with the reason. That is the
    honest answer — a run that stopped is not a run that passed — and it is
    the behaviour a candidate gets for calling `os._exit`.
    """
    results: dict[str, ScenarioResult] = {}
    session: NodeWorkerSession | None = None
    try:
        session = NodeWorkerSession(
            entrypoint,
            workdir=workspace,
            sandbox=sandbox or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED),
            extra_env=_worker_env(workspace),
            step_timeout_s=step_timeout_s,
        )
        graph = graph_from(session)
        compiled = graph.compile()
    except (IsolationError, Exception) as exc:  # noqa: BLE001 - a bad graph fails every scenario
        if session is not None:
            session.close()
        reason = f"{type(exc).__name__}: {exc}"
        return {s.id: _failed(reason) for s in scenarios}

    try:
        for index, scenario in enumerate(scenarios):
            results[scenario.id] = _run_one(
                compiled,
                scenario,
                policy,
                session=session,
                cassette_miss=cassette_miss,
                live_provider=live_provider,
            )
            if results[scenario.id].failure and _worker_is_dead(session):
                # The worker died. Every remaining scenario is unrun, and
                # unrun is not passed — recorded explicitly rather than left
                # absent, because a missing scenario is what G2's `missing`
                # check exists to catch and this is more specific than that.
                reason = "worker exited mid-corpus; this scenario never ran"
                for later in scenarios[index + 1 :]:
                    results[later.id] = _failed(reason)
                break
    finally:
        session.close()
    return results


def _worker_is_dead(session: NodeWorkerSession) -> bool:
    return session.returncode is not None


def _run_one(
    compiled: Any,
    scenario: Scenario,
    policy: PolicyConfig | None,
    *,
    session: NodeWorkerSession,
    cassette_miss: str = "fail",
    live_provider: dict[str, str] | None = None,
) -> ScenarioResult:
    # The node bodies run in the worker, so everything a node may `require_*`
    # has to be there too: a provider — or a POLICY ENGINE — on the parent's
    # `Services` answers nothing, because the parent's copy is handed to a
    # proxy that immediately serialises the call away. The policy was missing
    # here from ADR 0094 until ADR 0125: the worker's `agent_services()` took
    # no arguments, so every node consulting the engine was judged
    # deny-by-default and candidate, incumbent and cohort all scored 0.0.
    #
    # One frame, not two: a second channel is a second list to drift (ADR
    # 0091). Sent BEFORE the stopwatch starts — shipping the recording and
    # the harness's own configuration is the harness's cost, not the
    # candidate's.
    try:
        session.configure(
            {
                "model_calls": [c.to_payload() for c in scenario.model_calls],
                "on_miss": cassette_miss,
                "live": live_provider if cassette_miss == "live" else None,
                "policy": policy_payload(policy),
                "agent_id": scenario.initial_state.agent_id,
                "clock_values": [v.isoformat() for v in scenario.clock_values],
            }
        )
    except IsolationError as exc:
        return _failed(f"{type(exc).__name__}: {exc}")

    services = agent_services(
        clock=fixed_clock(scenario), policy=policy, agent_id=scenario.initial_state.agent_id
    )
    started = time.monotonic()
    try:
        result = GraphExecutor(compiled, services).run(scenario.initial_state, record_trace=True)
    except Exception as exc:  # noqa: BLE001 - any failure is an outcome, not a crash
        return _failed(f"{type(exc).__name__}: {exc}")

    # Same function as the in-process runner (ADR 0113): two scorers drift.
    record = score_scenario(
        scenario, result.final_state, elapsed_ms=(time.monotonic() - started) * 1000.0
    )
    return ScenarioResult(
        outcome=classify(result.final_state, result.trace, terminated=True),
        score=score_of(record),
        cost_tokens=record.cost_tokens,
    )


def _failed(reason: str) -> ScenarioResult:
    return ScenarioResult(
        outcome=Outcome(
            terminated=False,
            plan_status=None,
            error_count=1,
            policy_denials=0,
            node_path=(),
        ),
        score=0.0,
        cost_tokens=0,
        failure=reason,
    )
