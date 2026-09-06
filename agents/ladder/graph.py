"""A Zone A agent whose better position is reachable ONLY through a rejection.

`agents/demo` was built so that the winning square needs TWO constants raised
coherently, because the control cohort mutates one constant per member and so
cannot match a coherent pair. ADR 0198 then measured what that costs: the
rule-based proposer emits one proposal per constant and `cycle` takes
`proposals[0]`, so from any parent whatsoever it raises `RETRY_BUDGET` and
never `QUALITY_THRESHOLD`. The demo's ladder is on an axis the proposer cannot
walk, and no parent policy can fix that.

**This agent puts the ladder on the axis the proposer DOES walk**, and pays
for it by making the target narrow instead of two-dimensional:

    BATCH_SIZE   task metric on the ladder corpus
    1, 2         WORSE than the baseline  (batches too small for the work)
    3            the blessed baseline
    4            EXACTLY the baseline — a step that gains nothing
    5            BETTER — `hard-5` completes
    6 and above  0.0: every scenario fails (over the transport frame)

`BATCH_SIZE = 4` is a stepping stone by construction. It beats neither the
incumbent nor the cohort, so G3 rejects it; and the proposer's next step from
a parent at 3 is always 4, never 5, so a loop that always proposes from the
kept baseline can reach 4 and nothing further. The only route to 5 is to
propose FROM the rejected 4 — which is what an archive of rejected candidates
exists for, and what `--sample-parents` does.

Why the drop to 0.0 above 5 rather than a plateau: the cohort mutates one
constant by a factor in [0.5, 2.0), so from a parent at 4 it can reach 5, 6
and 7. If 6 and 7 also won, a random member would match the candidate often
enough that the comparison would be measuring luck. Making them catastrophic
is not a trick to help the candidate — it is what gives the null hypothesis
teeth, and it is why `BATCH_SIZE = 5` still loses to a cohort that happens to
contain a 5. The probe prints the whole curve so a reader can check the shape
rather than trust this paragraph.

The three constants below `BATCH_SIZE` are decoys in the sense that the
ladder corpus does not measure them — they are real operational knobs of this
agent and the cohort may mutate any of them, which is exactly their job here:
they are the four-sided die the null hypothesis rolls.

`find_constants` returns module-level constants in SOURCE ORDER, and `cycle`
takes `proposals[0]`, so `BATCH_SIZE` must stay first in this file. Moving it
is not a formatting change; it is a change to which axis the proposer walks.
"""

from __future__ import annotations

from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, Plan, Provenance, StateDelta

# How many items this agent will put in one batch. THE LADDER'S AXIS: first
# module-level constant in the file, so it is what `proposals[0]` moves.
BATCH_SIZE = 3
# How long a batch waits for a slow item before it gives up on it.
RETRY_DELAY_MS = 50
# How often progress is written to the run log.
LOG_EVERY = 10
# How many batches may be in flight at once.
IN_FLIGHT = 2

# The transport carries a fixed 320-byte frame and each item takes a 64-byte
# slot, so a batch of more than five items cannot be sent at all. A literal
# rather than a module constant ON PURPOSE: it is a property of the wire, not
# a knob, and `find_constants` must not offer it to a proposer or a cohort as
# something to tune.
_FRAME_SLOTS = 320 // 64


def work_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    items = int(state.working_memory.get("items", 1))

    prov = Provenance(
        node_id=ctx.node_id,
        graph_version=ctx.graph_version,
        ts=ctx.now,
        trace_id=ctx.trace_id,
        token_cost=items * 10,
    )

    if BATCH_SIZE > _FRAME_SLOTS:
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[
                    {
                        "node_id": ctx.node_id,
                        "error": (
                            f"batch of {BATCH_SIZE} exceeds the {_FRAME_SLOTS}-slot transport "
                            f"frame; nothing was sent"
                        ),
                    }
                ],
                scores={"quality": 0.0},
                provenance=[prov],
            ),
            END,
        )

    if items <= BATCH_SIZE:
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
                        f"gave up: {items} item(s) do not fit a batch of {BATCH_SIZE} "
                        f"(retry delay {RETRY_DELAY_MS}ms, {IN_FLIGHT} in flight)"
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
        id="ladder_agent",
        version="0.1.0",
        nodes={"work": work},
        edges=[],
        entry_node="work",
    )
