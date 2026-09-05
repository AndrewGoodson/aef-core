"""The containment warning reaches a human (ADR 0182, K3-4; ADR 0179's open item).

ADR 0179's R3 moved `prompt_agent.persona_in_user_turn` out of `state.errors`
— where it zeroed the task metric, became failure memory, and was pasted into
the persona by `RuleBasedPromptProposer` — and into the containment record the
node writes on every run, with `containment_warnings(state)` as THE reader. It
closed by naming what it had not done:

    **Open and named:** surfacing the containment warning in `aef loop doctor`
    and the cycle summary. `containment_warnings()` is the reader, written and
    tested; `aef/cli/loop.py` … belong to another worker in this wave and were
    not touched. Until that lands, the fact lives in the trace and in
    `working_memory` and nothing prints it.

REPRODUCED before the fix, end to end through the real CLI: a real `aef
migrate`d prompt agent bootstrapped through a real `model_provider.impl:
command` whose argv template has no `{system}` slot (ADR 0169's `codex` row),
with the fact demonstrably on the recorded scenario —

    scenario q-1: containment_warnings -> [('prompt_agent', {'isolation':
      ['single_turn', 'user_turn_persona'], 'message': "provider … declares no
      system channel…

— and `aef loop doctor` printing six obligations and `aef loop cycle` a
verdict, neither mentioning it.

The states here are built by the REAL `make_prompt_agent_node` against a
provider that declares `user_turn_persona`, so the warning under test is the
one the node writes rather than a dict this file invented.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.loop import _containment_lines, _corpus_states, _latest_run_state
from aef.cli.main import main
from aef.harness.corpus import Scenario, Split, save_scenario
from aef.harness.harvest import RecordedRun, save_run
from aef.kernel import END, Context, Graph, GraphExecutor, Services
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider
from aef.reasoning.prompt_agent import containment_warnings, make_prompt_agent_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
PERSONA = "---\nname: answerer\ndescription: answers.\n---\n\nAnswer in one word.\n"


class _Declaring(ModelProvider):
    """A real provider object with a declared isolation set and no network."""

    def __init__(self, name: str, isolation: frozenset[str]) -> None:
        self.name = name
        self._isolation = isolation

    @property
    def isolation(self) -> frozenset[str]:
        return self._isolation

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="PARIS", model="stub", input_tokens=1, output_tokens=1)


def _services(provider: ModelProvider) -> Services:
    return Services(
        model_provider=provider,
        memory=InMemoryMemoryStore(),
        knowledge=InMemoryKnowledgeStore(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        clock=lambda: NOW,
    )


def _run(tmp_path: Path, provider: ModelProvider) -> tuple[AEFState, tuple[object, ...]]:
    """One real execution of a real prompt-agent graph. Returns the final
    state and the trace, so a caller can save either shape of record."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    persona = tmp_path / "persona.md"
    persona.write_text(PERSONA, encoding="utf-8")
    graph = Graph(
        id="answerer",
        version="0.1.0",
        nodes={
            "prompt_agent": make_prompt_agent_node(
                agent_file=str(persona), agent_name="answerer", route=END
            )
        },
        edges=[],
        entry_node="prompt_agent",
    )
    initial = AEFState(run_id="r1", agent_id="a1", objective="Capital of France?")
    result = GraphExecutor(graph.compile(), _services(provider)).run(initial, record_trace=True)
    assert result.trace is not None
    return result.final_state, tuple(result.trace)


def _user_turn(tmp_path: Path) -> tuple[AEFState, tuple[object, ...]]:
    return _run(tmp_path, _Declaring("codex", frozenset({"read_only_fs", "user_turn_persona"})))


def _system_role(tmp_path: Path) -> tuple[AEFState, tuple[object, ...]]:
    return _run(tmp_path, _Declaring("claude_code", frozenset({"system_role"})))


# ---------------------------------------------------------------------------
# The line itself
# ---------------------------------------------------------------------------


def test_the_fixture_really_carries_the_warning(tmp_path: Path) -> None:
    """Verify the detector against the thing it detects before trusting any
    silence below: a test whose fixture never produced a warning would pass
    every "silent" assertion for the wrong reason."""
    state, _ = _user_turn(tmp_path)

    assert [node_id for node_id, _ in containment_warnings(state)] == ["prompt_agent"]


def test_one_line_per_warning_naming_the_node_provider_and_isolation(tmp_path: Path) -> None:
    state, _ = _user_turn(tmp_path)

    lines = _containment_lines([state])

    assert lines == [
        "prompt_agent: persona sent in the USER turn by provider 'codex' "
        "(isolation: read_only_fs, user_turn_persona) — see ADR 0179"
    ]


def test_a_system_channel_run_says_nothing(tmp_path: Path) -> None:
    """Silent, not "[OK] persona channel". The line is a WARNING about a
    provider property; a green tick for its absence would make it look like an
    obligation the owner satisfied."""
    state, _ = _system_role(tmp_path)

    assert _containment_lines([state]) == []


def test_one_line_per_DISTINCT_provider_not_per_run(tmp_path: Path) -> None:
    """A corpus of two hundred scenarios recorded against one CLI is one
    sentence, not two hundred."""
    first, _ = _user_turn(tmp_path)
    again, _ = _user_turn(tmp_path / "second")
    other, _ = _run(tmp_path / "third", _Declaring("grok", frozenset({"user_turn_persona"})))

    lines = _containment_lines([first, again, other])

    assert len(lines) == 2, lines
    assert "'codex'" in lines[0] and "'grok'" in lines[1], "sorted by provider"


# ---------------------------------------------------------------------------
# The two sources, and the one that deliberately is not read
# ---------------------------------------------------------------------------


def _corpus_with(root: Path, state: AEFState, trace: tuple[object, ...]) -> Path:
    save_scenario(
        root,
        Scenario(
            id="q-1",
            split=Split.TRAIN,
            graph_id="answerer",
            graph_version="1",
            initial_state=AEFState(run_id="r1", agent_id="a1", objective="Capital of France?"),
            trace=trace,  # type: ignore[arg-type]
            recorded_at=NOW,
        ),
    )
    assert state is not None
    return root


def test_a_corpus_scenario_is_a_source(tmp_path: Path) -> None:
    """These ARE the runs the gates re-execute, so a warning on one is a
    warning about the evidence a turn is judging against."""
    state, trace = _user_turn(tmp_path)
    corpus = _corpus_with(tmp_path / "corpus", state, trace)

    found = _corpus_states(argparse.Namespace(corpus=str(corpus)))

    assert _containment_lines(found), "the corpus was not read"


def test_only_the_most_recent_recorded_run_is_read(tmp_path: Path) -> None:
    """The question is "what does the provider you are running NOW do". An
    answer assembled from a year of runs would name a CLI replaced in March."""
    old_state, old_trace = _user_turn(tmp_path / "old")
    new_state, new_trace = _system_role(tmp_path / "new")
    runs = tmp_path / "runs"
    initial = AEFState(run_id="r0", agent_id="a1", objective="Capital of France?")
    save_run(
        runs,
        RecordedRun(
            run_id="old",
            graph_id="answerer",
            graph_version="1",
            initial_state=initial,
            trace=old_trace,  # type: ignore[arg-type]
            at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    save_run(
        runs,
        RecordedRun(
            run_id="new",
            graph_id="answerer",
            graph_version="1",
            initial_state=initial,
            trace=new_trace,  # type: ignore[arg-type]
            at=NOW,
        ),
    )
    assert old_state is not None and new_state is not None

    found = _latest_run_state(argparse.Namespace(runs=str(runs)))

    assert len(found) == 1
    assert _containment_lines(found) == [], "the SUPERSEDED provider was reported"


def test_no_runs_and_no_corpus_read_nothing(tmp_path: Path) -> None:
    assert _latest_run_state(argparse.Namespace(runs=None)) == []
    assert _latest_run_state(argparse.Namespace(runs=str(tmp_path / "nope"))) == []
    assert _corpus_states(argparse.Namespace(corpus=None)) == []
    assert _corpus_states(argparse.Namespace(corpus=str(tmp_path / "nope"))) == []


def test_the_memory_store_is_not_a_source_and_that_is_deliberate(tmp_path: Path) -> None:
    """ADR 0179's whole finding is that this fact is not a failure, so
    `make_reflect_node` never writes it into a `MemoryRecord` — a reader that
    went looking in `--memory` would find nothing on every repo. Asserted here
    rather than left as a comment, because "we checked and it is not there" is
    a claim that can go stale.
    """
    state, _ = _user_turn(tmp_path)
    services = _services(_Declaring("codex", frozenset({"user_turn_persona"})))
    from aef.reasoning.nodes import make_reflect_node

    node = make_reflect_node()
    node.fn(
        state,
        Context(run_id="r1", node_id="reflect", graph_version="1", trace_id="t", now=NOW),
        services,
    )

    records = [
        *services.require_memory().query("failure", agent_id="a1"),
        *services.require_memory().query("success", agent_id="a1"),
    ]
    assert records, "the reflect node wrote nothing at all — this test proves nothing"
    assert not any("user_turn_persona" in str(record.content) for record in records)


# ---------------------------------------------------------------------------
# The two CLI surfaces
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    import subprocess

    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text("x = 1\n")
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "-A"],
        ["commit", "-qm", "base"],
    ):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)
    return root


def _doctor(repo: Path, tmp_path: Path, corpus: Path) -> int:
    return main(
        [
            "loop",
            "doctor",
            "--repo",
            str(repo),
            "--state",
            str(tmp_path / "state"),
            "--corpus",
            str(corpus),
        ]
    )


def test_doctor_prints_the_warning_beside_the_obligations(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    state, trace = _user_turn(tmp_path)
    corpus = _corpus_with(tmp_path / "corpus", state, trace)
    capsys.readouterr()

    code = _doctor(repo, tmp_path, corpus)
    out = capsys.readouterr().out

    assert "[!!] persona channel" in out, out
    assert "persona sent in the USER turn by provider 'codex'" in out, out
    assert "see ADR 0179" in out, out
    assert "Not an obligation and not a fix" in out, out
    # And it is NOT one of the six: the count is unchanged and so is the code.
    assert "Loop readiness — 6 things you must supply" in out, out
    assert code == 1, "an unmet obligation, not the warning, is what sets the code"


def test_doctor_is_silent_when_the_persona_was_the_system_message(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    state, trace = _system_role(tmp_path)
    corpus = _corpus_with(tmp_path / "corpus", state, trace)
    capsys.readouterr()

    _doctor(repo, tmp_path, corpus)
    out = capsys.readouterr().out

    assert "persona channel" not in out, out
    assert "USER turn" not in out, out


def test_the_cycle_summary_prints_one_line_per_provider(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    state, trace = _user_turn(tmp_path)
    corpus = _corpus_with(tmp_path / "corpus", state, trace)
    capsys.readouterr()

    code = main(
        [
            "loop",
            "cycle",
            "--repo",
            str(repo),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "work"),
            "--corpus",
            str(corpus),
            "--no-memory",
        ]
    )
    out = capsys.readouterr().out

    assert code == 0, out
    assert (
        "prompt_agent: persona sent in the USER turn by provider 'codex' "
        "(isolation: read_only_fs, user_turn_persona) — see ADR 0179" in out
    ), out
    # Beside the verdict, which is the line a workflow tees into its summary.
    assert out.index("USER turn") < out.index("cycle verdict:"), out


def test_the_cycle_summary_is_silent_without_one(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    state, trace = _system_role(tmp_path)
    corpus = _corpus_with(tmp_path / "corpus", state, trace)
    capsys.readouterr()

    main(
        [
            "loop",
            "cycle",
            "--repo",
            str(repo),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "work"),
            "--corpus",
            str(corpus),
            "--no-memory",
        ]
    )

    assert "USER turn" not in capsys.readouterr().out
