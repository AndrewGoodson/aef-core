"""The ladder fixture's staircase, as a tripwire (ADR 0203).

`agents/ladder` exists for one measured claim: the rung above the baseline is
reachable ONLY by proposing from a candidate the gates rejected. Four
properties carry that claim, and each of them is a property a later edit could
undo without touching a test:

* `BATCH_SIZE` is the FIRST module-level constant `find_constants` returns, so
  it is what `cycle`'s `proposals[0]` moves. Reordering the file changes which
  axis the proposer walks — a formatting change with a semantic effect.
* the proposer's own step lands on 4 from 3 and on 5 from 4.
* rung 4 is EXACTLY the baseline (so G3 rejects it and it becomes a stone),
  rung 5 is strictly better, and rung 6 collapses (so the null cohort cannot
  win by overshooting).
* the committed run data says a keeper's parent was rejected — checked
  against the raw JSONL rather than against the report that summarises it.

The last one is the increment's result; the first three are the reasons it is
not luck.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aef.harness.proposer import RuleBasedProposer, coerce_value, find_constants
from aef.kernel import GraphExecutor
from aef.services.runtime import agent_services
from aef.state import AEFState

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SOURCE = REPO_ROOT / "agents" / "ladder" / "graph.py"
RESULTS = REPO_ROOT / "docs" / "research" / "j2c" / "results.jsonl"
CORPUS = REPO_ROOT / "docs" / "research" / "j2c" / "corpus"

# What `--probe` published, before the arms ran. Pinned here so the fixture and
# the ADR cannot drift apart silently.
STAIRCASE: dict[int, float] = {
    1: 1 / 9,
    2: 3 / 9,
    3: 5 / 9,
    4: 5 / 9,
    5: 7 / 9,
    6: 0.0,
    7: 0.0,
}


def _metric(monkeypatch: pytest.MonkeyPatch, batch_size: int) -> float:
    """The task metric at one rung, by RUNNING the graph over every scenario's
    own initial state — not by re-implementing the predicate here, which would
    make this test agree with a copy of the agent rather than with the agent."""
    import agents.ladder.graph as ladder

    monkeypatch.setattr(ladder, "BATCH_SIZE", batch_size)
    services = agent_services()
    passed = total = 0
    for split in ("train", "validation"):
        for path in sorted((CORPUS / split).glob("*.json")):
            payload = json.loads(path.read_text())
            state = AEFState.model_validate(payload["initial_state"])
            result = GraphExecutor(ladder.build_graph().compile(), services).run(state)
            total += 1
            if result.final_state.scores.get("quality") == 1.0:
                passed += 1
    return passed / total


def test_batch_size_is_the_first_constant_the_proposer_sees() -> None:
    """`proposals[0]` walks the first constant in source order. If this moves,
    the ladder is on an axis the rule-based proposer never touches — which is
    exactly the ceiling ADR 0198 measured on `agents/demo`."""
    constants = find_constants(GRAPH_SOURCE.read_text())
    assert [c.name for c in constants][0] == "BATCH_SIZE"
    assert len(constants) >= 2, "the null cohort needs more than one constant to choose between"


def test_the_proposers_own_step_lands_on_the_next_rung() -> None:
    """From 3 it must propose 4 (the stone) and from 4 it must propose 5 (the
    rung).

    `step` is read off `RuleBasedProposer` rather than written here as `0.25`.
    The first version of this test DID write it here, and the mutation that
    changed the shipped default sailed through — a test that pins a constant to
    a copy of itself asserts nothing about the code it names (ADR 0203).
    """
    constants = {c.name: c for c in find_constants(GRAPH_SOURCE.read_text())}
    batch = constants["BATCH_SIZE"]
    assert batch.value == 3.0, "the fixture's baseline rung moved"
    step = RuleBasedProposer().step
    assert coerce_value(batch, batch.value * (1.0 + step)) == 4.0
    at_four = type(batch)(name=batch.name, value=4.0, line=batch.line, is_int=True)
    assert coerce_value(at_four, 4.0 * (1.0 + step)) == 5.0


@pytest.mark.parametrize("rung", sorted(STAIRCASE))
def test_the_staircase_is_the_shape_the_probe_published(
    monkeypatch: pytest.MonkeyPatch, rung: int
) -> None:
    assert _metric(monkeypatch, rung) == pytest.approx(STAIRCASE[rung])


def test_rung_four_gains_nothing_and_rung_five_gains_something(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stepping stone's defining property, in one assertion.

    If rung 4 were better than 3, G3 would keep it and greedy would climb; if
    rung 5 were not better than 4, there would be nothing above the stone to
    reach. Both halves are needed and neither is implied by the other.
    """
    three = _metric(monkeypatch, 3)
    four = _metric(monkeypatch, 4)
    five = _metric(monkeypatch, 5)
    assert four == three, "rung 4 is not neutral; it would be kept, not rejected"
    assert five > four, "rung 5 is not better than the stone; there is no ladder"


def test_overshooting_the_rung_collapses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The null hypothesis keeps its teeth.

    The cohort mutates one constant by a factor in [0.5, 2.0), so from a parent
    at 4 it reaches 5, 6 and 7. If 6 and 7 also won, a random member would
    match the candidate often enough that the comparison would measure luck.
    """
    assert _metric(monkeypatch, 6) == 0.0
    assert _metric(monkeypatch, 7) == 0.0


def _summaries() -> list[dict[str, object]]:
    rows = [json.loads(line) for line in RESULTS.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == "summary"]


def test_the_committed_runs_say_a_keeper_descended_from_a_rejection() -> None:
    """ADR 0203's headline, read off the raw JSONL rather than the report.

    Every keeper must (a) be counted as a stepping-stone keep, (b) name a
    parent, and (c) that parent must be recorded as a REJECT — a keeper whose
    parent was itself kept is an ordinary greedy advance and must not be
    counted here.
    """
    by_arm: dict[str, int] = {}
    for row in _summaries():
        lineage = row["lineage"]
        assert isinstance(lineage, dict)
        arm = str(row["arm"])
        by_arm[arm] = by_arm.get(arm, 0) + int(lineage["stepping_stone_keeps"])
        for stone in lineage["stepping_stones"]:
            assert stone["parent_disposition"] == "reject", stone
            assert stone["parent_score"] is not None, "an unscored reject is never a parent"
            assert stone["score"] > stone["parent_score"], stone
    assert by_arm.get("greedy", 0) == 0, "greedy proposed from a rejection; it cannot"
    assert by_arm.get("sampling", 0) >= 1, "the increment's whole result is missing"


def test_every_greedy_run_stopped_on_the_duplicate_it_had_to_stop_on() -> None:
    """Greedy's zero is a proof, not an observation: its parent is the kept ref,
    the kept ref never moves, so `proposals[0]` is the same tree every turn."""
    greedy = [r for r in _summaries() if r["arm"] == "greedy"]
    assert greedy, "no greedy runs recorded"
    for row in greedy:
        assert row["kept"] == 0
        assert "already rejected" in str(row["stopped_because"])
        assert set(row["batch_sizes"]) == {4}, row["batch_sizes"]
