"""`aef loop cycle` derives `--graph-id` from the corpus it already loaded
(ADR 0176, F2).

THE DEFECT, reproduced at the CLI on a scratch repo before anything changed.
Bootstrap two inputs whose owner checks the graph fails, with `--memory`, then
cycle with the prompt proposer and no `--graph-id`:

    $ aef loop cycle --repo … --corpus … --memory … \\
        --proposer rule_based_prompt --agent-path agents/demo/persona.md
      ledger verified: 0 entr(ies)
      the proposer produced nothing from the available evidence: 2 record(s)
      dropped as another graph's scenario; no admissible failure record for
      this graph
    exit=0

while the same command with `--graph-id demo_agent` proposed a candidate and
gated it. Both records were in the file; the graph id was in the corpus the
command had already read.

THE COMPLICATION this file also pins: `--graph-id` is TWO things — the archive
key G5 reads a blessed baseline under, and the `Graph.id` the prompt proposer
matches scenarios against (ADR 0125 separated those namespaces on purpose).
Deriving unconditionally moved the archive key out from under an
already-blessed baseline, and
`test_an_adopted_repo_gates_a_candidate_end_to_end` went red with `not built:
G5 rejected the candidate first`. So derivation happens when there is nothing
to orphan, and says so loudly when there is.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.loop import (
    DEFAULT_GRAPH_ID,
    GraphIdError,
    graph_id,
    resolve_graph_id_from_corpus,
)
from aef.cli.main import main
from aef.harness.corpus import Corpus, Scenario, Split, save_scenario
from aef.state import AEFState

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
MODULE = "agents.demo.graph"
PERSONA = "agents/demo/persona.md"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / PERSONA).write_text("---\nname: demo_agent\n---\n\n# Demo agent\n\nDo the work.\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _bootstrap(tmp_path: Path, corpus: Path, memory: Path) -> None:
    """Two runs that SUCCEED and fail the owner's check, so the check-derived
    failure records of ADR 0174 land in the durable store."""
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            [
                {
                    "id": "wrong-one",
                    "objective": "an easy task",
                    "working_memory": {"difficulty": 1, "quality_needed": 1},
                    "checks": [{"path": "scores.quality", "op": "equals", "value": 0.5}],
                },
                {
                    "id": "wrong-two",
                    "objective": "another easy task",
                    "working_memory": {"difficulty": 1, "quality_needed": 1},
                    "checks": [{"path": "scores.quality", "op": "equals", "value": 0.25}],
                },
            ]
        )
    )
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(corpus),
                "--inputs",
                str(inputs),
                "--memory",
                str(memory),
                "--no-loop-state",
            ]
        )
        == 0
    )


def _cycle(repo: Path, tmp_path: Path, corpus: Path, memory: Path, *extra: str) -> int:
    return main(
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
            "--memory",
            str(memory),
            "--proposer",
            "rule_based_prompt",
            "--agent-path",
            PERSONA,
            *extra,
        ]
    )


# ---------------------------------------------------------------------------
# THE regression test
# ---------------------------------------------------------------------------


def test_a_cycle_without_graph_id_no_longer_drops_the_evidence(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    corpus, memory = tmp_path / "corpus", tmp_path / "memory.jsonl"
    _bootstrap(tmp_path, corpus, memory)
    capsys.readouterr()

    _cycle(repo, tmp_path, corpus, memory)
    out = capsys.readouterr().out

    assert "dropped as another graph's scenario" not in out, out
    assert "no admissible failure record" not in out, out
    assert "proposed cycle-" in out, out
    # And it SAYS what it derived — twice, because the verdict line is the one
    # a workflow tees into its step summary and three lines up is not a place
    # anyone reads.
    assert "derived 'demo_agent'" in out, out
    assert "[--graph-id derived from --corpus: 'demo_agent']" in out, out


def test_the_explicit_flag_still_works_and_says_nothing_about_deriving(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    corpus, memory = tmp_path / "corpus", tmp_path / "memory.jsonl"
    _bootstrap(tmp_path, corpus, memory)
    capsys.readouterr()

    _cycle(repo, tmp_path, corpus, memory, "--graph-id", "demo_agent")
    out = capsys.readouterr().out

    assert "proposed cycle-" in out, out
    assert "derived" not in out, out


# ---------------------------------------------------------------------------
# The three cases of the rule, at the function
# ---------------------------------------------------------------------------


def _corpus_of(root: Path, *graph_ids: str) -> Path:
    for index, gid in enumerate(graph_ids):
        save_scenario(
            root,
            Scenario(
                id=f"s-{index}",
                split=Split.TRAIN,
                graph_id=gid,
                graph_version="1",
                initial_state=AEFState(run_id=f"s-{index}", agent_id="a", objective="o"),
                trace=(),
                recorded_at=NOW,
            ),
        )
    return root


def _bless(state: Path, key: str) -> None:
    """One archived baseline under `key` — enough for `_blessed_under`."""
    from aef.harness import archive

    archive.record(
        state / "archive",
        key,
        files={"agents/demo/graph.py": b"x = 1\n"},
        base_sha="0" * 40,
        head_sha="1" * 40,
        recorded_at=NOW,
    )


def _args(tmp_path: Path, corpus: Path, given: str | None) -> object:
    import argparse

    return argparse.Namespace(corpus=str(corpus), graph_id=given, state=str(tmp_path / "state"))


def test_one_graph_and_no_flag_derives_and_says_so(tmp_path: Path) -> None:
    corpus = _corpus_of(tmp_path / "corpus", "marlin-accela")
    args = _args(tmp_path, corpus, None)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert resolution.derived == "marlin-accela"
    assert args.graph_id == "marlin-accela"  # type: ignore[attr-defined]
    assert "derived 'marlin-accela'" in (resolution.note or "")


def test_several_graphs_and_no_flag_refuses_with_the_list(tmp_path: Path) -> None:
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent", "summary_agent")

    with pytest.raises(GraphIdError) as exc:
        resolve_graph_id_from_corpus(_args(tmp_path, corpus, None))  # type: ignore[arg-type]

    assert "'demo_agent'" in str(exc.value) and "'summary_agent'" in str(exc.value)
    assert "not guessable" in str(exc.value)


def test_a_flag_naming_no_graph_and_nothing_blessed_is_refused(tmp_path: Path) -> None:
    """A typo. Nothing in the corpus carries it and no baseline sits under it,
    so it is neither namespace."""
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent")

    with pytest.raises(GraphIdError) as exc:
        resolve_graph_id_from_corpus(_args(tmp_path, corpus, "typo"))  # type: ignore[arg-type]

    assert "'demo_agent'" in str(exc.value)
    assert "no blessed baseline sits under it" in str(exc.value)


def test_a_flag_naming_no_graph_but_holding_a_baseline_is_a_warning(tmp_path: Path) -> None:
    """ADR 0125's namespace, kept: a live archive key is not a typo. It is
    warned about by name, because the prompt proposer will still drop the
    records — refusing here would break the documented adoption sequence, in
    which `aef loop bless` takes no corpus at all.
    """
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent")
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)

    resolution = resolve_graph_id_from_corpus(  # type: ignore[arg-type]
        _args(tmp_path, corpus, DEFAULT_GRAPH_ID)
    )

    assert resolution.derived is None
    assert "WARNING" in (resolution.note or "")
    assert "archive key" in (resolution.note or "")


def test_derivation_does_not_move_the_key_out_from_under_a_baseline(tmp_path: Path) -> None:
    """The measured regression this branch exists for: deriving
    unconditionally left G5 with no baseline and rejected every candidate for
    having nothing to compare to."""
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent")
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)
    args = _args(tmp_path, corpus, None)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert resolution.derived is None, "the key must not move"
    assert args.graph_id is None  # type: ignore[attr-defined]
    assert graph_id(args) == DEFAULT_GRAPH_ID  # type: ignore[arg-type]
    note = resolution.note or ""
    assert "aef loop bless --graph-id demo_agent" in note, note


def test_no_corpus_derives_nothing_and_still_means_default(tmp_path: Path) -> None:
    import argparse

    args = argparse.Namespace(corpus=None, graph_id=None, state=str(tmp_path / "state"))

    assert resolve_graph_id_from_corpus(args) == (None, None)
    assert graph_id(args) == DEFAULT_GRAPH_ID


def test_an_empty_corpus_derives_nothing(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    assert resolve_graph_id_from_corpus(_args(tmp_path, root, None)) == (None, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The refusal at the CLI, journalled like every other way `cycle` can die
# ---------------------------------------------------------------------------


def test_the_ambiguous_corpus_refusal_is_a_rejection_and_is_journalled(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent", "summary_agent")

    code = _cycle(repo, tmp_path, corpus, tmp_path / "memory.jsonl")

    assert code == 1, "a configuration refusal, not a halt"
    assert "records 2 graphs" in capsys.readouterr().err
    journal = tmp_path / "state" / "cycles.jsonl"
    assert journal.is_file(), "the turn must still be journalled (ADR 0167)"
    assert "GraphIdError" in journal.read_text()


def test_the_corpus_is_not_read_twice_into_two_different_answers(tmp_path: Path) -> None:
    """The derived id and the id the gates filter scenarios by come from the
    same read of the same corpus — the seam this whole finding lived in."""
    corpus = _corpus_of(tmp_path / "corpus", "marlin-accela")
    args = _args(tmp_path, corpus, None)
    resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    from aef.harness.corpus import load_corpus

    loaded: Corpus = load_corpus(corpus)
    assert {s.graph_id for s in loaded.scenarios} == {graph_id(args)}  # type: ignore[arg-type]
    assert loaded.split(Split.TRAIN)
