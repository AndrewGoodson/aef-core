"""Three integrity properties this layer claimed and did not have.

All three were found in the first sweep of `aef/kernel` + `aef/state` and
recorded as OPEN in ADR 0086. Each was reproduced by running before being
fixed (ADR 0087).

The pattern worth naming: every one of them had a test that read as if it
pinned the property and asserted something weaker.
"""

import dataclasses

import pydantic
import pytest

from aef.kernel import END, Edge, Graph, GraphExecutor, Node, ReplayEngine, Services
from aef.kernel.replay import MalformedTraceError
from aef.state import AEFState, StateDelta


def _a(state, ctx, services):  # type: ignore[no-untyped-def]
    return StateDelta(working_memory={"x": 1}), "b"


def _b(state, ctx, services):  # type: ignore[no-untyped-def]
    return StateDelta(working_memory={"y": 1}), END


def _graph() -> Graph:
    return Graph(
        id="g",
        version="1",
        nodes={
            "a": Node(id="a", version="1", fn=_a, deterministic=True),
            "b": Node(id="b", version="1", fn=_b, deterministic=True),
        },
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )


@pytest.fixture
def honest_run():  # type: ignore[no-untyped-def]
    return GraphExecutor(_graph().compile(), Services()).run(
        AEFState(run_id="r", agent_id="ag", objective="ship the trade"), record_trace=True
    )


# --------------------------------------------------------------------------
# The state chain
# --------------------------------------------------------------------------


def test_an_honest_trace_still_replays(honest_run) -> None:  # type: ignore[no-untyped-def]
    """The control. Every refusal below is worthless if the happy path also
    refuses."""
    replayed = ReplayEngine(_graph().compile(), Services()).replay(honest_run.trace)
    assert replayed.objective == "ship the trade"
    assert replayed.working_memory == {"x": 1, "y": 1}


@pytest.mark.parametrize(
    ("name", "forgery"),
    [
        ("objective", {"objective": "ship the trade (approved)"}),
        ("scores", {"scores": {"sharpe": 3.4}}),
        ("errors", {"errors": [{"e": "risk limit breached"}]}),
        ("checkpoint_seq", {"checkpoint_seq": 4243}),
    ],
)
def test_a_forged_input_state_is_refused(honest_run, name, forgery) -> None:  # type: ignore[no-untyped-def]
    """`state` was reassigned from each record's OWN `input_state`, so the
    final state was decided entirely by the last record. A trace whose node
    ids chained perfectly and whose deterministic nodes re-executed to
    matching deltas replayed CLEAN with forged fields — because no
    deterministic node reads them.

    ADR 0023's stated goal was "instead of silently producing a wrong final
    state with no error". Reordering by node id was caught; state forgery
    was not, and the existing test only permuted node ids.
    """
    trace = list(honest_run.trace)
    last = trace[-1]
    trace[-1] = dataclasses.replace(last, input_state=last.input_state.model_copy(update=forgery))
    with pytest.raises(MalformedTraceError, match="describes a run that never happened"):
        ReplayEngine(_graph().compile(), Services()).replay(tuple(trace))


# --------------------------------------------------------------------------
# apply() is pure, deeply
# --------------------------------------------------------------------------


def test_mutating_the_result_does_not_reach_the_input() -> None:
    """`model_copy(update=...)` rebuilds the top-level containers and shares
    every nested object. `NodeExecutionRecord.input_state` aliases the live
    state, so a node mutating a nested dict rewrote trace records that are
    supposed to be history."""
    state = AEFState(run_id="r", agent_id="a", objective="o", working_memory={"cfg": {"deep": 1}})
    result = StateDelta(working_memory={"other": 2}).apply(state)

    assert result.working_memory["cfg"] is not state.working_memory["cfg"]
    result.working_memory["cfg"]["deep"] = 999
    assert state.working_memory["cfg"] == {"deep": 1}


def test_one_delta_applied_twice_does_not_leak_between_results() -> None:
    """A `StateDelta` applied to two states shared nested containers between
    the two results *and back into the delta itself*."""
    delta = StateDelta(working_memory={"a": {"deep": 1}})
    first = delta.apply(AEFState(run_id="r1", agent_id="a", objective="o"))
    first.working_memory["a"]["deep"] = 999

    second = delta.apply(AEFState(run_id="r2", agent_id="a", objective="o"))
    assert second.working_memory["a"] == {"deep": 1}
    assert delta.working_memory["a"] == {"deep": 1}


def test_a_node_cannot_rewrite_its_own_trace_record() -> None:
    """The consequence that matters: history must not be editable by the
    thing being recorded."""

    def mutating(state, ctx, services):  # type: ignore[no-untyped-def]
        state.working_memory.setdefault("audit", []).append("was-here")
        return StateDelta(working_memory={"done": True}), END

    graph = Graph(
        id="g",
        version="1",
        nodes={"n": Node(id="n", version="1", fn=mutating, deterministic=False)},
        edges=[],
        entry_node="n",
    )
    entry = AEFState(run_id="r", agent_id="a", objective="o", working_memory={"audit": []})
    result = GraphExecutor(graph.compile(), Services()).run(entry, record_trace=True)

    assert result.trace is not None
    assert result.trace[0].input_state.working_memory["audit"] == [], (
        "the recorded input state was rewritten after the fact"
    )


# --------------------------------------------------------------------------
# The ADR 0022 guard, on the fields it did not cover
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("working_memory", {"working_memory": {"sharpe": float("nan")}}),
        ("nested in working_memory", {"working_memory": {"m": {"pf": float("inf")}}}),
        ("inside a list", {"working_memory": {"xs": [1.0, float("-inf")]}}),
        ("errors", {"errors": [{"v": float("nan")}]}),
        ("tool_results", {"tool_results": [{"v": float("nan")}]}),
    ],
)
def test_a_non_finite_float_is_rejected_wherever_it_hides(name, kwargs) -> None:  # type: ignore[no-untyped-def]
    """ADR 0022 rejected a non-finite `scores` value and left
    `working_memory` alone — the field `AEFState`'s own docstring names as
    where per-agent data belongs. JSON has no literal for NaN, so the first
    checkpoint write rewrites it to `null` and the corruption becomes
    indistinguishable from an absent value."""
    with pytest.raises(pydantic.ValidationError, match="non-finite float"):
        StateDelta(**kwargs)


def test_ordinary_floats_still_pass() -> None:
    delta = StateDelta(working_memory={"ok": 1.5, "nested": {"also": [0.0, -2.5]}})
    assert delta.working_memory["ok"] == 1.5


def test_the_error_names_where_the_value_is() -> None:
    """A guard that says "something is non-finite" sends you looking."""
    with pytest.raises(pydantic.ValidationError, match=r"m\.pf"):
        StateDelta(working_memory={"m": {"pf": float("inf")}})
