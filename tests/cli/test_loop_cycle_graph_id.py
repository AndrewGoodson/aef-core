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

THE COMPLICATION this file also pins: `--graph-id` WAS TWO things — the
archive key G5 reads a blessed baseline under, and the `Graph.id` the prompt
proposer matches scenarios against (ADR 0125 separated those namespaces on
purpose). Deriving unconditionally moved the archive key out from under an
already-blessed baseline, and
`test_an_adopted_repo_gates_a_candidate_end_to_end` went red with `not built:
G5 rejected the candidate first`. So ADR 0176 derived only when there was
nothing to orphan, and printed a WARNING when there was.

**Updated deliberately in ADR 0182.** `LoopConfig` has two fields now —
`graph_id` (the archive key) and `evidence_graph_id` (the `Graph.id` the
proposer admits records under) — so deriving the evidence id cannot orphan a
baseline and the archive key is never moved by this function at all. Four
tests below pinned the one-field behaviour and are rewritten here with that
history; the fifth, the regression test at the top, keeps its subject and
gains the assertion that the baseline stays where it was blessed. The rule
that survives unchanged is the refusal: a corpus recording several graphs and
no `--graph-id` is still not guessable.
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
    # anyone reads. The wording moved from "--graph-id derived" to "evidence
    # graph id derived" in ADR 0182, because the archive key is no longer what
    # changed and a summary naming the flag sends the reader to the wrong
    # place.
    assert "derived as 'demo_agent'" in out, out
    assert "[evidence graph id derived from --corpus: 'demo_agent']" in out, out
    assert "The archive key is unchanged ('default')" in out, out


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

    return argparse.Namespace(
        corpus=str(corpus),
        graph_id=given,
        evidence_graph_id=None,
        state=str(tmp_path / "state"),
    )


def test_one_graph_and_no_flag_derives_the_evidence_id_only(tmp_path: Path) -> None:
    """Was `test_one_graph_and_no_flag_derives_and_says_so`, which asserted
    `args.graph_id == "marlin-accela"` — the ARCHIVE key moving. It does not
    move any more (ADR 0182): the derived value lands on the second field, and
    the key is what it always was."""
    corpus = _corpus_of(tmp_path / "corpus", "marlin-accela")
    args = _args(tmp_path, corpus, None)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert resolution.derived == "marlin-accela"
    assert args.evidence_graph_id == "marlin-accela"  # type: ignore[attr-defined]
    assert args.graph_id is None, "the ARCHIVE key must not move"  # type: ignore[attr-defined]
    assert graph_id(args) == DEFAULT_GRAPH_ID  # type: ignore[arg-type]
    assert "derived as 'marlin-accela'" in (resolution.note or "")


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


def test_a_flag_naming_no_graph_but_holding_a_baseline_keeps_the_key_and_derives(
    tmp_path: Path,
) -> None:
    """Was `..._is_a_warning`. ADR 0125's namespace is still kept — a live
    archive key is not a typo — but the WARNING it printed described a fix it
    could not perform: "--proposer rule_based_prompt drops every failure
    record tied to those scenarios". With two fields it performs it (ADR
    0182): the key stays, the evidence id comes from the corpus.
    """
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent")
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)
    args = _args(tmp_path, corpus, DEFAULT_GRAPH_ID)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert resolution.derived == "demo_agent"
    assert args.evidence_graph_id == "demo_agent"  # type: ignore[attr-defined]
    assert args.graph_id == DEFAULT_GRAPH_ID  # type: ignore[attr-defined]
    note = resolution.note or ""
    assert "ARCHIVE key" in note, note
    assert "WARNING" not in note, "there is nothing left to warn about"


def test_an_ambiguous_corpus_under_a_live_archive_key_is_still_warned_about(
    tmp_path: Path,
) -> None:
    """The one warning that survives, and why: the key is not a typo, so it is
    kept — but with several graphs in the corpus the evidence id is still not
    derivable, and this function refuses to guess it (ADR 0176's rule, intact).
    """
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent", "summary_agent")
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)
    args = _args(tmp_path, corpus, DEFAULT_GRAPH_ID)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert resolution.derived is None
    assert args.evidence_graph_id is None  # type: ignore[attr-defined]
    assert "WARNING" in (resolution.note or "")


def test_derivation_does_not_move_the_key_out_from_under_a_baseline(tmp_path: Path) -> None:
    """The measured regression the old warn branch existed for: deriving
    unconditionally left G5 with no baseline and rejected every candidate for
    having nothing to compare to.

    The property is unchanged and the mechanism is not: derivation happens
    now — it just happens on the OTHER field, so there is nothing to orphan.
    """
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent")
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)
    args = _args(tmp_path, corpus, None)

    resolution = resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    assert args.graph_id is None, "the ARCHIVE key must not move"  # type: ignore[attr-defined]
    assert graph_id(args) == DEFAULT_GRAPH_ID  # type: ignore[arg-type]
    assert resolution.derived == "demo_agent", "and the EVIDENCE id must be derived anyway"
    assert args.evidence_graph_id == "demo_agent"  # type: ignore[attr-defined]


def test_no_corpus_derives_nothing_and_still_means_default(tmp_path: Path) -> None:
    import argparse

    args = argparse.Namespace(
        corpus=None, graph_id=None, evidence_graph_id=None, state=str(tmp_path / "state")
    )

    assert resolve_graph_id_from_corpus(args) == (None, None)
    assert graph_id(args) == DEFAULT_GRAPH_ID


def test_an_empty_corpus_derives_nothing(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    assert resolve_graph_id_from_corpus(_args(tmp_path, root, None)) == (None, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The refusal at the CLI, journalled like every other way `cycle` can die
# ---------------------------------------------------------------------------


def test_the_ambiguous_corpus_refusal_is_an_error_not_a_rejection_and_is_journalled(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    corpus = _corpus_of(tmp_path / "corpus", "demo_agent", "summary_agent")

    code = _cycle(repo, tmp_path, corpus, tmp_path / "memory.jsonl")

    # Was pinned as exit 1 (a rejection) until ADR 0188: the nightly workflow
    # reads 1 as the loop working, and this is the loop misconfigured.
    assert code == 3, "a configuration refusal is an ERROR: not a halt, not a verdict"
    assert "records 2 graphs" in capsys.readouterr().err
    journal = tmp_path / "state" / "cycles.jsonl"
    assert journal.is_file(), "the turn must still be journalled (ADR 0167)"
    assert "GraphIdError" in journal.read_text()


def test_the_corpus_is_not_read_twice_into_two_different_answers(tmp_path: Path) -> None:
    """The derived id and the id the PROPOSER admits records under come from
    the same read of the same corpus — the seam this whole finding lived in.

    It used to compare against `graph_id(args)`, which was the same field.
    Since ADR 0182 the derived value is `evidence_graph_id`, and the archive
    key deliberately does NOT track the corpus — so comparing against
    `graph_id` here would now pin the defect rather than the fix.
    """
    corpus = _corpus_of(tmp_path / "corpus", "marlin-accela")
    args = _args(tmp_path, corpus, None)
    resolve_graph_id_from_corpus(args)  # type: ignore[arg-type]

    from aef.harness.corpus import load_corpus

    loaded: Corpus = load_corpus(corpus)
    assert {s.graph_id for s in loaded.scenarios} == {args.evidence_graph_id}  # type: ignore[attr-defined]
    assert loaded.split(Split.TRAIN)


# ---------------------------------------------------------------------------
# The two fields, together, on the configuration ADR 0176 could only warn about
# ---------------------------------------------------------------------------


def test_a_blessed_default_and_a_demo_agent_corpus_get_both_answers(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """THE K3-3 case (ADR 0182), and it is exactly the one ADR 0176 warned
    about instead of fixing: `aef loop bless` takes no `--corpus`, so the
    documented first-week sequence blesses under `'default'` while the corpus
    the loop bootstraps records `'demo_agent'`.

    Before, the cycle printed `WARNING: --proposer rule_based_prompt will drop
    this corpus's failure records as another graph's` and then did exactly
    that. Now both answers are right at once: the proposer grounds in
    `demo_agent`'s evidence AND G5 still finds the `default` baseline.
    """
    corpus, memory = tmp_path / "corpus", tmp_path / "memory.jsonl"
    _bootstrap(tmp_path, corpus, memory)
    _bless(tmp_path / "state", DEFAULT_GRAPH_ID)
    capsys.readouterr()

    _cycle(repo, tmp_path, corpus, memory)
    out = capsys.readouterr().out

    # The evidence half.
    assert "dropped as another graph's scenario" not in out, out
    assert "proposed cycle-" in out, out
    assert "derived as 'demo_agent'" in out, out
    # The archive half: the baseline is still where `bless` put it, so G5 has
    # something to compare against.
    from aef.harness import archive

    assert archive.versions(tmp_path / "state" / "archive", DEFAULT_GRAPH_ID), (
        "the blessed baseline was orphaned — the archive key moved"
    )
    assert not archive.versions(tmp_path / "state" / "archive", "demo_agent")
    assert "no baseline" not in out, out


def test_the_two_fields_are_two_and_collapsing_them_orphans_the_baseline(tmp_path: Path) -> None:
    """The mutation, as an assertion about the config rather than a comment.

    `LoopConfig.evidence_graph_id` defaults to None and `evidence_id` falls
    back to `graph_id`, so a caller that never heard of the split is
    unchanged; set it, and the two answers differ. Collapse them — make
    `evidence_id` return `graph_id` unconditionally — and the CLI's derivation
    would have to move the key again, which is what orphaned the baseline.
    """
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths

    unsplit = LoopConfig(
        repo=GitRepo(root=tmp_path), paths=LoopPaths(root=tmp_path / "s"), graph_id="default"
    )
    assert unsplit.evidence_id == "default", "None must mean 'the same as the archive key'"

    split = LoopConfig(
        repo=GitRepo(root=tmp_path),
        paths=LoopPaths(root=tmp_path / "s"),
        graph_id="default",
        evidence_graph_id="demo_agent",
    )
    assert split.graph_id == "default", "the archive key"
    assert split.evidence_id == "demo_agent", "the Graph.id the proposer admits records under"


# ---------------------------------------------------------------------------
# The OTHER turn-running command (ADR 0200, found by the unattended night)
# ---------------------------------------------------------------------------


def _run(repo: Path, tmp_path: Path, corpus: Path, memory: Path, *extra: str) -> int:
    return main(
        [
            "loop",
            "run",
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
            "--turns",
            "1",
            *extra,
        ]
    )


def test_a_run_without_graph_id_no_longer_drops_the_evidence(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """The regression test above, for `run` instead of `cycle`.

    ADR 0176 fixed one of the two commands that run a turn. `cmd_run` never
    called `resolve_graph_id_from_corpus` at all, and nothing noticed for two
    waves because the only thing that would notice is a `loop run` against a
    corpus whose graph id is not the literal `"default"` — which is every
    migrated prompt-agent repo, and which nothing had run unattended until
    ADR 0200's night. It reported `no admissible failure memory … no candidate
    this cycle` and exited 0, on the very same repo, corpus and memory file
    where `cycle` proposed.

    That is ADR 0165's shape, third occurrence: one of a pair fixed, the other
    left, and the difference invisible because the broken one exits 0.
    """
    corpus, memory = tmp_path / "corpus", tmp_path / "memory.jsonl"
    _bootstrap(tmp_path, corpus, memory)
    capsys.readouterr()

    _run(repo, tmp_path, corpus, memory)
    out = capsys.readouterr().out

    assert "belonging to a graph other than 'default'" not in out, out
    assert "no admissible failure memory" not in out, out
    assert "derived as 'demo_agent'" in out, out
    assert "turn 1: proposed cycle-" in out, out


def test_both_turn_commands_settle_the_evidence_id_the_same_way() -> None:
    """One resolver, called by both — pinned so a third command cannot be
    added with the question left unasked."""
    import inspect

    from aef.cli.loop import cmd_cycle, cmd_run

    for handler in (cmd_cycle, cmd_run):
        assert "resolve_graph_id_from_corpus(args)" in inspect.getsource(handler), handler.__name__
