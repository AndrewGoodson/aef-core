"""`--graph-id` restricts the evidence for EVERY proposer, not one of three.

ADR 0191's F2. `--graph-id`'s help text promises "the graph whose recorded
scenarios are this loop's evidence", and the filter that kept that promise
lived inside `RuleBasedPromptProposer._admissible`. `_build_proposer`
constructs the DEFAULT `RuleBasedProposer()` with no graph id at all, and
`MemoryEvidence.from_store` filtered only validation/holdout run ids — so on
this repo's own two-graph corpus:

    $ aef loop cycle --repo . --state ... --graph-id demo_agent \\
        --agent-path agents/demo/graph.py --corpus corpus --memory ...
      proposed cycle-20260905T085525-0 on local branch loop/cycle-...

and the ledger's `gated` event recorded

    "grounded_in": ["m3 (memory): the summary invented a number",
                    "m2 (memory): the summary dropped the ferry name",
                    "m1 (memory): the summary dropped the reservoir date"]

— three `summary_agent` records grounding a change to `agents/demo/graph.py`,
with the flag on the command line (reproduced).

The evidence a proposer may see is a property of the EVIDENCE, not of which
proposer happens to read it. The filter is now applied once, where the
evidence is assembled.
"""

from __future__ import annotations

import inspect
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.corpus import Scenario, Split, load_corpus, save_scenario
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, cycle
from aef.harness.memory_store import FileMemoryStore
from aef.harness.proposer import MemoryEvidence, RuleBasedProposer
from aef.services.memory.base import MemoryRecord
from aef.state import AEFState

NOW = datetime(2026, 9, 5, tzinfo=UTC)

# A Zone A graph with a numeric constant the rule-based proposer can move, so
# that "it proposed nothing" can only mean the evidence was withheld.
DEMO_SOURCE = """RETRY_BUDGET = 3


def build_graph():  # pragma: no cover - never executed by these tests
    raise NotImplementedError
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text(DEMO_SOURCE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _corpus(tmp_path: Path) -> Path:
    """Two graphs, exactly as aef-core's own corpus has: `demo_agent`
    scenarios and `summary_agent` scenarios, all TRAIN so that nothing here
    turns on the validation/holdout exclusion instead."""
    root = tmp_path / "corpus"
    for sid, gid in (
        ("demo-1", "demo_agent"),
        ("sum-01-kestrel-ferry", "summary_agent"),
        ("sum-02-orchard-blight", "summary_agent"),
        ("sum-03-tidewell-library", "summary_agent"),
    ):
        save_scenario(
            root,
            Scenario(
                id=sid,
                split=Split.TRAIN,
                graph_id=gid,
                graph_version="1",
                initial_state=AEFState(run_id=sid, agent_id="a", objective="o"),
                trace=(),
                recorded_at=NOW,
            ),
        )
    return root


def _store(tmp_path: Path, *run_ids: str) -> FileMemoryStore:
    store = FileMemoryStore(path=tmp_path / "memory.jsonl")
    for index, run_id in enumerate(run_ids, start=1):
        store.write(
            MemoryRecord(
                id=f"m{index}",
                agent_id="summary_agent",
                kind="failure",
                content={
                    "verbal_feedback": f"the summary dropped a fact ({run_id})",
                    "failing_nodes": ["work"],
                },
                run_id=run_id,
                created_at=NOW,
            )
        )
    return store


def _config(repo: Path, tmp_path: Path, corpus: Path, graph_id: str) -> LoopConfig:
    return LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / f"state-{graph_id}"),
        corpus=load_corpus(corpus),
        graph_id=graph_id,
    )


# ---------------------------------------------------------------------------
# THE regression test — the hunt's own reproduction
# ---------------------------------------------------------------------------


def test_the_default_proposer_no_longer_grounds_in_another_graphs_records(
    tmp_path: Path,
) -> None:
    """Memory holding three `summary_agent` failures, `--graph-id
    demo_agent`, and the DEFAULT `rule_based` proposer — the exact shape that
    proposed a change to `agents/demo/graph.py` and journalled all three
    records as its grounds."""
    repo = _repo(tmp_path)
    corpus = _corpus(tmp_path)
    store = _store(
        tmp_path,
        "sum-01-kestrel-ferry",
        "sum-02-orchard-blight",
        "sum-03-tidewell-library",
    )

    run = cycle(
        _config(repo, tmp_path, corpus, "demo_agent"),
        now=NOW,
        workdir=tmp_path / "work",
        memory=store,
        agent_path="agents/demo/graph.py",
    )

    assert run.proposed is None, run.lines
    # And the VERDICT says why, because `cmd_cycle` journals `lines[-1]` and
    # "no admissible failure memory" alone sends an operator to record more
    # failures when the remedy is to point --graph-id at the right graph.
    verdict = run.lines[-1]
    assert "another graph" in verdict, verdict
    assert "demo_agent" in verdict, verdict
    assert "3 record(s)" in verdict, verdict


def test_the_same_records_under_their_OWN_graph_id_are_admitted(tmp_path: Path) -> None:
    """The positive case. The filter must be a filter, not a wall: the same
    store, the same corpus, `--graph-id summary_agent`, and the records are
    evidence again — otherwise this test suite would pass on a `from_store`
    that returned nothing."""
    corpus = load_corpus(_corpus(tmp_path))
    store = _store(
        tmp_path,
        "sum-01-kestrel-ferry",
        "sum-02-orchard-blight",
        "sum-03-tidewell-library",
    )

    admitted = MemoryEvidence.from_store(store, corpus, graph_id="summary_agent")
    assert len(admitted.records) == 3
    assert admitted.foreign == ()

    withheld = MemoryEvidence.from_store(store, corpus, graph_id="demo_agent")
    assert withheld.records == ()
    assert set(withheld.foreign) == {"m1", "m2", "m3"}

    # And the DEFAULT proposer — the one that had no graph id — turns the
    # admitted evidence into a proposal, so the negative above is the filter
    # and not a proposer that cannot propose.
    proposals = RuleBasedProposer().propose_from_memory(
        admitted, proposal_id="p", path="agents/demo/graph.py", source=DEMO_SOURCE
    )
    assert proposals, "the default proposer produced nothing from admitted evidence"


def test_a_run_id_the_corpus_has_never_heard_of_is_still_admitted(tmp_path: Path) -> None:
    """The rule is *deny what is KNOWN to belong to another graph*, and it has
    to stay that way: a production run has an arbitrary `run_id` that appears
    in no scenario, and production experience is what this exists to learn
    from. Widening this to an allowlist would silently switch the loop off for
    every adopter whose runs are not corpus replays."""
    corpus = load_corpus(_corpus(tmp_path))
    store = _store(tmp_path, "prod-2026-09-05-17d3f")

    evidence = MemoryEvidence.from_store(store, corpus, graph_id="demo_agent")
    assert len(evidence.records) == 1
    assert evidence.foreign == ()


def test_the_filter_is_on_the_evidence_and_not_on_any_proposer(tmp_path: Path) -> None:
    """The structural half of the fix, and the reason F2 existed: the default
    proposer takes no graph id and never did. A filter that each proposer has
    to remember to apply is a filter two of three proposers do not have."""
    assert "graph_id" not in inspect.signature(RuleBasedProposer).parameters
    assert "graph_id" in inspect.signature(MemoryEvidence.from_store).parameters
