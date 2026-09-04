"""`aef loop bootstrap` — a corpus on day one (ADR 0138).

Four rules, each inherited from a component that learned it the hard way, and
each with its own test because their opposites break the corpus in four
different ways: harvest's train-only rule, ADR 0060's owner-only `expected`,
recorder's no-overwrite rule, and the failure count without which a corpus
cannot demonstrate an improvement.
"""

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.bootstrap import (
    BootstrapError,
    BootstrapInput,
    bootstrap,
    load_inputs,
)
from aef.harness.checks import TaskCheck
from aef.harness.corpus import Expected, Split, load_corpus
from aef.harness.recorder import RecorderError
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _graph() -> Graph:
    """Fails when `difficulty` exceeds the budget — the demo agent's shape,
    small enough that the failure is unambiguous."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        if int(state.working_memory.get("difficulty", 1)) > 3:
            return (
                StateDelta(
                    plan=Plan(goal=state.objective, status="failed"),
                    errors=[{"node_id": ctx.node_id, "error": "too hard"}],
                    scores={"quality": 0.0},
                ),
                END,
            )
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            END,
        )

    return Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )


def _services() -> Services:
    return agent_services(memory=InMemoryMemoryStore())


def _inputs(*specs: tuple[str, int]) -> tuple[BootstrapInput, ...]:
    return tuple(
        BootstrapInput(id=sid, objective=f"task {sid}", working_memory={"difficulty": difficulty})
        for sid, difficulty in specs
    )


def _run(root: Path, *specs: tuple[str, int]):  # type: ignore[no-untyped-def]
    return bootstrap(
        root,
        _graph(),
        _services,
        inputs=_inputs(*specs),
        now=NOW,
        agent_id="fixture",
    )


# --- rule 1: always TRAIN, and no way to ask for anything else ---------------


def test_bootstrap_writes_only_the_train_split(tmp_path: Path) -> None:
    """Harvest's rule: if the system could fill the set that gates it, the
    gate would measure the system's own choices."""
    root = tmp_path / "corpus"
    _run(root, ("easy", 1), ("hard", 9))

    corpus = load_corpus(root)
    assert len(corpus.scenarios) == 2
    assert {s.split for s in corpus.scenarios} == {Split.TRAIN}
    assert not (root / Split.VALIDATION.value).exists()
    assert not (root / Split.HOLDOUT.value).exists()


def test_bootstrap_offers_no_flag_to_write_another_split() -> None:
    """As in `harvest`, there is not even a way to ask. A keyword argument
    for a rule is a default, and a default is something a caller changes."""
    assert "split" not in inspect.signature(bootstrap).parameters

    from aef.cli.main import build_parser

    for action in _bootstrap_parser(build_parser())._actions:
        assert action.dest not in {"split", "allow_holdout", "i_am_spending_the_holdout"}


def _bootstrap_parser(parser):  # type: ignore[no-untyped-def]
    loop = next(a for a in parser._actions if getattr(a, "choices", None) and "loop" in a.choices)
    return loop.choices["loop"]._actions[-1].choices["bootstrap"]  # type: ignore[union-attr]


# --- rule 2: never labels `expected` -----------------------------------------


def test_bootstrap_never_labels_expected(tmp_path: Path) -> None:
    """Only an owner can say a task SHOULD have failed (ADR 0060). The
    corpus includes a run that DID fail, so a label derived from the outcome
    would show up here."""
    root = tmp_path / "corpus"
    outcome = _run(root, ("easy", 1), ("hard", 9))
    assert outcome.failed == ("hard",)

    for scenario in load_corpus(root).scenarios:
        assert scenario.expected is Expected.UNSPECIFIED, (
            f"{scenario.id} carries a claim bootstrap invented"
        )


def test_bootstrap_prints_the_ids_the_owner_should_consider(tmp_path: Path) -> None:
    outcome = _run(tmp_path / "corpus", ("easy", 1), ("hard", 9))
    text = "\n".join(outcome.lines)
    assert "hard" in text
    assert "ADR 0060" in text
    assert "labels nothing" in text


def test_the_suggested_tripwire_command_carries_the_input_back(tmp_path: Path) -> None:
    """Generated, never executed — and `record_run` still refuses must_fail
    on a task the agent completes, so the suggestion is checked by the
    command that acts on it."""
    inputs = _inputs(("easy", 1), ("hard", 9))
    outcome = bootstrap(
        tmp_path / "corpus", _graph(), _services, inputs=inputs, now=NOW, agent_id="fixture"
    )
    commands = outcome.tripwire_commands("agents.mine.graph", "corpus", inputs)
    assert len(commands) == 1
    assert "--scenario-id hard-tripwire" in commands[0]
    assert "--expected must_fail" in commands[0]
    assert "--split validation" in commands[0]
    # Shell-quoted: the JSON blob survives one round of shell unquoting.
    assert '--working-memory "{\\"difficulty\\": 9}"' in commands[0]


def test_an_expected_key_in_the_inputs_file_is_refused_not_ignored(tmp_path: Path) -> None:
    """Silently dropping an owner's claim is worse than refusing it: they
    would believe the corpus carries a tripwire it does not."""
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps([{"objective": "t", "expected": "must_fail"}]))
    with pytest.raises(BootstrapError, match="ADR 0060"):
        load_inputs(path)


def test_a_split_key_in_the_inputs_file_is_refused_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps([{"objective": "t", "split": "validation"}]))
    with pytest.raises(BootstrapError, match="train split only"):
        load_inputs(path)


# --- rule 3: refuses to overwrite --------------------------------------------


def test_bootstrap_refuses_an_existing_id_and_writes_nothing_first(tmp_path: Path) -> None:
    """Refused for the WHOLE batch, before anything runs. A collision found
    halfway through would leave the earlier inputs written, so re-running the
    file could never be safe."""
    root = tmp_path / "corpus"
    _run(root, ("taken", 1))
    before = sorted(p.name for p in (root / "train").glob("*.json"))

    with pytest.raises(RecorderError, match="already exist"):
        _run(root, ("fresh", 1), ("taken", 9))

    assert sorted(p.name for p in (root / "train").glob("*.json")) == before
    assert "fresh" not in load_corpus(root).ids


def test_bootstrap_refuses_a_duplicate_id_within_one_batch(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="more than once"):
        _run(tmp_path / "corpus", ("same", 1), ("same", 9))


# --- rule 4: reports the failure count ---------------------------------------


def test_bootstrap_reports_how_many_runs_failed(tmp_path: Path) -> None:
    outcome = _run(tmp_path / "corpus", ("a", 1), ("b", 9), ("c", 9))
    assert outcome.failed == ("b", "c")
    assert "2 of 3 recorded run(s) FAILED." in outcome.lines


def test_bootstrap_says_so_when_nothing_failed(tmp_path: Path) -> None:
    """A corpus where everything passes cannot demonstrate an improvement.
    That is a finding about the inputs, printed as one."""
    outcome = _run(tmp_path / "corpus", ("a", 1), ("b", 2))
    assert outcome.failed == ()
    text = "\n".join(outcome.lines)
    assert "0 of 2 recorded run(s) failed" in text
    assert "cannot demonstrate an improvement" in text


# --- the seam: one set of services per input ---------------------------------


def test_each_input_gets_its_own_services(tmp_path: Path) -> None:
    """The gates re-execute each scenario in isolation with a fresh
    `InMemoryMemoryStore` (`harvest._reexecution_services`). A bootstrap that
    shared one store would record later runs that depended on what earlier
    ones remembered — scenarios that cannot reproduce alone."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        memory = services.require_memory()
        seen = len(memory.query("episodic", limit=100))
        memory.write(MemoryRecord(kind="episodic", content={"objective": state.objective}))
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"), working_memory={"seen": seen}
            ),
            END,
        )

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )
    root = tmp_path / "corpus"
    bootstrap(
        root,
        graph,
        _services,
        inputs=_inputs(("first", 1), ("second", 1)),
        now=NOW,
        agent_id="fixture",
    )

    seen = {s.id: s.trace[0].delta.working_memory["seen"] for s in load_corpus(root).scenarios}
    assert seen == {"first": 0, "second": 0}, (
        "the second run saw the first run's memory — the scenarios do not reproduce alone"
    )


# --- owner claims that ARE accepted per input (ADR 0113) ---------------------


def test_owner_checks_and_budget_travel_with_the_scenario(tmp_path: Path) -> None:
    """`checks` and `budget_ms` are a specification of the task written
    BEFORE the run, not a judgement about what the run turned out to do —
    which is exactly why they are accepted and `expected` is not."""
    root = tmp_path / "corpus"
    bootstrap(
        root,
        _graph(),
        _services,
        inputs=(
            BootstrapInput(
                id="checked",
                objective="t",
                working_memory={"difficulty": 1},
                checks=(TaskCheck(path="scores.quality", op="equals", value=1.0),),
                budget_ms=250.0,
            ),
        ),
        now=NOW,
        agent_id="fixture",
    )
    scenario = load_corpus(root).scenarios[0]
    assert scenario.checks == (TaskCheck(path="scores.quality", op="equals", value=1.0),)
    assert scenario.budget_ms == 250.0


# --- a run that raises -------------------------------------------------------


def test_a_run_that_raises_is_reported_and_records_nothing(tmp_path: Path) -> None:
    """The adoptee case: the migrated node builds its own vendor client and
    there is no credential, so the node raises before producing a trace. A
    scenario with an empty trace pins nothing and would pass every gate
    vacuously, so nothing is written."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        raise RuntimeError("no credential")

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=False)},
        edges=[],
        entry_node="work",
    )
    root = tmp_path / "corpus"
    outcome = bootstrap(
        root, graph, _services, inputs=_inputs(("boom", 1)), now=NOW, agent_id="fixture"
    )

    assert outcome.recorded == ()
    assert outcome.errored[0][0] == "boom"
    assert "no credential" in outcome.errored[0][1]
    assert not load_corpus(root).scenarios if root.is_dir() else True

    text = "\n".join(outcome.lines)
    assert "NOTHING was recorded" in text
    # "everything passed" and "nothing ran" are different facts.
    assert "cannot demonstrate an improvement" not in text


# --- the inputs file ---------------------------------------------------------


def test_inputs_accept_a_bare_list_or_an_object(tmp_path: Path) -> None:
    listed = tmp_path / "a.json"
    listed.write_text(json.dumps([{"objective": "one"}]))
    wrapped = tmp_path / "b.json"
    wrapped.write_text(json.dumps({"inputs": [{"objective": "one"}]}))
    assert load_inputs(listed) == load_inputs(wrapped)


def test_ids_default_to_the_prefix_and_position(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a"}, {"id": "named", "objective": "b"}]))
    assert [i.id for i in load_inputs(path, prefix="seed")] == ["seed-1", "named"]


def test_an_input_without_an_objective_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"working_memory": {"difficulty": 9}}]))
    with pytest.raises(BootstrapError, match="objective"):
        load_inputs(path)


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a", "working_memroy": {}}]))
    with pytest.raises(BootstrapError, match="unknown key"):
        load_inputs(path)


def test_a_malformed_check_fails_before_anything_runs(tmp_path: Path) -> None:
    """A check that loaded wrong would score its scenario 0 forever and read
    as a regression (ADR 0113)."""
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a", "checks": [{"path": "x", "op": "nope"}]}]))
    with pytest.raises(BootstrapError, match="nope"):
        load_inputs(path)


def test_an_empty_inputs_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text("[]")
    with pytest.raises(BootstrapError, match="no inputs"):
        load_inputs(path)
