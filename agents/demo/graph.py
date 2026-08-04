"""A Zone A demo agent the self-rewiring loop can actually operate on.

Deliberately small, deterministic, and **tunable**: its behaviour depends on
two module-level constants, which is the shape `RuleBasedProposer` and
`ControlCohortGenerator` both work in (ADR 0054).

Why two constants rather than one: it makes the null hypothesis meaningful.
The control cohort mutates a single constant per member, so a candidate that
raises one budget can be matched by a random change that happens to raise the
same one. A candidate that raises *both coherently* cannot — which is the
actual claim being tested, that reasoned change beats random change because
it is coherent, not because it is larger.
"""

from __future__ import annotations

from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, Plan, Provenance, StateDelta

# How much difficulty this agent will absorb before giving up.
RETRY_BUDGET = 3
# How much quality it can deliver.
QUALITY_THRESHOLD = 3


def work_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    difficulty = int(state.working_memory.get("difficulty", 1))
    quality_needed = int(state.working_memory.get("quality_needed", 1))

    prov = Provenance(
        node_id=ctx.node_id,
        graph_version=ctx.graph_version,
        ts=ctx.now,
        trace_id=ctx.trace_id,
        token_cost=difficulty * 10,
    )

    if difficulty <= RETRY_BUDGET and quality_needed <= QUALITY_THRESHOLD:
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"),
                scores={"quality": 1.0},
                provenance=[prov],
            ),
            END,
        )

    return (
        StateDelta(
            plan=Plan(goal=state.objective, status="failed"),
            errors=[
                {
                    "node_id": ctx.node_id,
                    "error": (
                        f"gave up: difficulty {difficulty} vs budget {RETRY_BUDGET}, "
                        f"quality {quality_needed} vs threshold {QUALITY_THRESHOLD}"
                    ),
                }
            ],
            scores={"quality": 0.0},
            provenance=[prov],
        ),
        END,
    )


def build_graph() -> Graph:
    work = Node(id="work", version="0.1.0", fn=work_node, deterministic=True)
    return Graph(
        id="demo_agent",
        version="0.1.0",
        nodes={"work": work},
        edges=[],
        entry_node="work",
    )
