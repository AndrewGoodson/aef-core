"""Re-executes corpus scenarios against a candidate graph, inside the sandbox.

Invoked as `python -m aef.harness.scenario_runner <scenarios.json> <entrypoint>`
with the post-merge workspace as cwd. **The `aef` package it runs from is the
base ref's** (`workspace.py`), so the code loading and running agent-authored
code is the harness's own, not the candidate's. The candidate supplies only
the graph.

Emits `{scenario_id: {"outcome": ..., "score": ...}}` on stdout. A scenario
that raises is recorded as a non-terminating, zero-scoring result rather than
aborting the batch: one broken scenario is a result about that scenario, and
losing the other ninety-nine to it would hide more than it reveals.

The **score** is emitted alongside the outcome deliberately. G2 (outcome
non-regression) and G3 (improvement) both need a full pass over the corpus,
and a variant is expensive to materialise and load. Running the graph twice
to answer two questions about the same execution would double the cost of
the most expensive gate in the pipeline for nothing.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

from aef.harness.corpus import Scenario, fixed_clock
from aef.harness.evaluation import score_of
from aef.harness.outcome import classify
from aef.kernel import GraphExecutor, Services
from aef.kernel.graph import Graph
from aef.services.eval.rule_based import RuleBasedEvaluator


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
    except Exception as exc:  # noqa: BLE001 - agent-authored factory; any raise is a bad entrypoint
        raise EntrypointError(f"{entrypoint} raised {type(exc).__name__}: {exc}") from exc
    if not isinstance(graph, Graph):
        raise EntrypointError(f"{entrypoint} returned {type(graph).__name__}, expected a Graph")
    return graph


def run_scenario(scenario: Scenario, graph: Graph) -> dict[str, Any]:
    """One scenario, answering both gates' questions from one execution."""
    services = Services(clock=fixed_clock(scenario))
    try:
        result = GraphExecutor(graph.compile(), services).run(
            scenario.initial_state, record_trace=True
        )
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

    record = RuleBasedEvaluator().evaluate(result.final_state)
    return {
        "outcome": classify(result.final_state, result.trace, terminated=True).to_payload(),
        "score": score_of(record),
        "cost_tokens": record.cost_tokens,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            f"usage: python -m {__package__}.scenario_runner <scenarios.json> <entrypoint>",
            file=sys.stderr,
        )
        return 2

    scenarios = [Scenario.from_payload(p) for p in json.loads(open(argv[1]).read())]
    graph = load_graph(argv[2])
    outcomes = {s.id: run_scenario(s, graph) for s in scenarios}
    print(json.dumps(outcomes))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main(sys.argv))
