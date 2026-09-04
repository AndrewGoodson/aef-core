"""Executing one recorded scenario, in this process.

**This is no longer how the gates score a candidate.** It was, and the
contract was "run the corpus in a subprocess and print the results" — which
made the candidate the author of the evidence judging it. Three attempts to
secure that channel were each defeated (ADR 0085, 0088, 0093), because the
candidate's code and the reporting code shared an interpreter.

The gates now use `isolated_suite.run_corpus_isolated`: the candidate answers
one node at a time in a worker that never learns what a scenario is, and the
parent concludes (ADR 0094). The stdout marker protocol that used to live
here has been REMOVED rather than left behind, so it cannot be wired back by
someone who reads only its docstring.

What remains is the in-process helper: given a scenario and a graph you
already trust — the incumbent's, a test's — run it and classify. It executes
agent code in the calling process and must not be used to score a candidate.
"""

from __future__ import annotations

import importlib
import time
from typing import Any

from aef.harness.corpus import Scenario, fixed_clock
from aef.harness.evaluation import score_of, score_scenario
from aef.harness.outcome import classify
from aef.kernel import GraphExecutor, HumanApprovalRequiredError
from aef.kernel.graph import Graph
from aef.security.tool import PolicyConfig
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services

# The same rubric `aef run` and `aef loop record` default to. A gate that
# re-executed a recorded scenario under a different rubric would be comparing
# two different measurements and calling the difference a regression.
DEFAULT_RUBRIC: dict[str, float] = {"quality": 1.0}


class EntrypointError(RuntimeError):
    pass


def load_graph(entrypoint: str) -> Graph:
    """`package.module:factory` -> the `Graph` that factory returns."""
    module_name, _, attribute = entrypoint.partition(":")
    if not module_name or not attribute:
        raise EntrypointError(f"entrypoint must be 'module:factory', got {entrypoint!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EntrypointError(f"cannot import {module_name!r}: {exc}") from exc
    try:
        factory = getattr(module, attribute)
    except AttributeError as exc:
        raise EntrypointError(f"{module_name!r} has no attribute {attribute!r}") from exc

    try:
        graph = factory()
    except BaseException as exc:  # noqa: BLE001 - see below
        # BaseException, not Exception. `SystemExit` is a BaseException, so
        # `raise SystemExit(0)` sailed through this handler and exited the
        # process CLEANLY — and a candidate that had already printed forged
        # JSON then owned the runner's entire output. Two added lines scored
        # a broken agent 1.0 instead of 0.0 and passed all six gates
        # (ADR 0085). Agent-authored code does not get to decide that this
        # process is finished.
        raise EntrypointError(f"{entrypoint} raised {type(exc).__name__}: {exc}") from exc
    if not isinstance(graph, Graph):
        raise EntrypointError(f"{entrypoint} returned {type(graph).__name__}, expected a Graph")
    return graph


def policy_config_from_payload(payload: dict[str, Any] | None) -> PolicyConfig:
    """The policy the HARNESS supplies, never one the candidate provides.

    Passed in as data, read by the caller from the BASE REF. Reading
    `aef.yaml` from the workspace here would let a candidate widen its own
    policy by editing a Zone C file — the gate would then be judging it under
    rules it wrote (ADR 0082). An absent payload means deny-by-default, which
    is what an unconfigured production run also gets.
    """
    if not payload:
        return PolicyConfig()
    return PolicyConfig(
        allowed_scopes=frozenset(payload.get("allowed_scopes", ())),
        forbidden_tool_names=frozenset(payload.get("forbidden_tool_names", ())),
        require_hitl_above_risk=float(payload.get("require_hitl_above_risk", 0.0)),
    )


def run_scenario(
    scenario: Scenario, graph: Graph, policy: PolicyConfig | None = None
) -> dict[str, Any]:
    """One scenario, answering both gates' questions from one execution.

    `critic` and `judge` are wired here for the same reason `aef run` and
    `aef loop record` wire them (ADR 0073): **every reflect node requires
    them**, and LOOP.md obligation 2 tells every adopter to add one. This was
    the third construction site and the only one that was missed — and it is
    the one the gates use, so an adopter who satisfied obligation 2 made every
    scenario crash with `ServiceNotConfiguredError`, scoring the candidate,
    the incumbent and all five cohort members 0.0. G3 rejected every candidate
    forever, and `doctor` reported the obligation green (ADR 0075).

    Memory is in-process and thrown away: the gate re-executes recorded
    scenarios to compare behaviour, and writing to the adopter's durable store
    would let a gate run mutate the evidence a later proposal is built from.
    Both services are rule-based and deterministic, which the sandbox requires.
    """
    # One list, shared with `aef run` — see aef/services/runtime.py. Four
    # separate defects were "the gate path lacks a service the node needs"
    # (ADR 0073/0075/0079/0089); the cause each time was drift between two
    # lists nobody compared (ADR 0091).
    services = agent_services(
        clock=fixed_clock(scenario),
        policy=policy,
        # Memory is in-process and thrown away: writing to the adopter's
        # durable store would let a gate run mutate the evidence a later
        # proposal is built from.
        memory=InMemoryMemoryStore(),
        agent_id=scenario.initial_state.agent_id,
    )
    started = time.monotonic()
    try:
        result = GraphExecutor(graph.compile(), services).run(
            scenario.initial_state, record_trace=True
        )
    except HumanApprovalRequiredError as exc:
        # A PAUSE, not a failure — and deliberately NOT an approval.
        #
        # `Services.hitl_approvals` is left empty on purpose. Supplying it
        # here would mean the gate approves things on the owner's behalf so
        # that the corpus can execute, which is the harness granting itself
        # the permission the edge exists to withhold. The cost is that a
        # HITL-gated scenario cannot be scored on behaviour; the benefit is
        # that the gate is never bypassed to make measurement convenient.
        #
        # This is the only place `hitl_paused` is set, and it is set from a
        # caught kernel exception rather than from anything the candidate
        # wrote (ADR 0081).
        return {
            "outcome": {
                "terminated": False,
                "plan_status": None,
                "error_count": 0,
                "policy_denials": 0,
                "node_path": [],
                "hitl_paused": True,
            },
            "score": 0.0,
            "cost_tokens": 0,
            "paused": f"{exc}",
        }
    except Exception as exc:  # noqa: BLE001 - any failure is an outcome, not a crash
        return {
            "outcome": {
                "terminated": False,
                "plan_status": None,
                "error_count": 1,
                "policy_denials": 0,
                "node_path": [],
            },
            "score": 0.0,
            "cost_tokens": 0,
            "failure": f"{type(exc).__name__}: {exc}",
        }

    elapsed_ms = (time.monotonic() - started) * 1000.0
    record = score_scenario(scenario, result.final_state, elapsed_ms=elapsed_ms)
    payload: dict[str, Any] = {
        "outcome": classify(result.final_state, result.trace, terminated=True).to_payload(),
        "score": score_of(record),
        "cost_tokens": record.cost_tokens,
        "elapsed_ms": elapsed_ms,
    }
    if "checks" in record.metadata:
        payload["checks"] = record.metadata["checks"]
    if record.metadata.get("budget_exceeded"):
        payload["budget_exceeded"] = True
    return payload
