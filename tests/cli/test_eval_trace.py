from pathlib import Path

import pytest

from aef.cli.eval import eval_run
from aef.cli.trace import trace_run
from aef.kernel import END, FileDurabilityBackend, Graph, GraphExecutor, Node, Services
from aef.state import AEFState, Message, Plan, Provenance, StateDelta


def _seed_checkpoints(checkpoints_dir: Path, run_id: str) -> None:
    def _llm_fn(state, ctx, services):
        prov = Provenance(
            node_id=ctx.node_id,
            graph_version=ctx.graph_version,
            ts=ctx.now,
            trace_id=ctx.trace_id,
            model="claude-x",
            token_cost=7,
        )
        delta = StateDelta(
            messages=[Message(role="assistant", content="hi", prov=prov)],
            provenance=[prov],
            plan=Plan(goal="g", status="done"),
        )
        return delta, END

    node = Node(id="llm", version="1.0.0", fn=_llm_fn, deterministic=False)
    graph = Graph(id="g", version="1.0.0", nodes={"llm": node}, edges=[], entry_node="llm")
    executor = GraphExecutor(
        graph.compile(), Services(durability=FileDurabilityBackend(checkpoints_dir))
    )
    executor.run(AEFState(run_id=run_id, agent_id="a1", objective="test"))


def test_eval_run_scores_a_checkpointed_run(tmp_path: Path) -> None:
    _seed_checkpoints(tmp_path, "run-eval-1")
    record = eval_run(tmp_path, "run-eval-1")
    assert record.task_completion == 1.0
    assert record.cost_tokens == 7


def test_eval_run_missing_run_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no checkpoints"):
        eval_run(tmp_path, "does-not-exist")


def test_trace_run_returns_provenance_in_order(tmp_path: Path) -> None:
    _seed_checkpoints(tmp_path, "run-trace-1")
    provenance = trace_run(tmp_path, "run-trace-1")
    assert len(provenance) == 1
    assert provenance[0].node_id == "llm"
    assert provenance[0].model == "claude-x"
    assert provenance[0].token_cost == 7


def test_trace_run_missing_run_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no checkpoints"):
        trace_run(tmp_path, "does-not-exist")
