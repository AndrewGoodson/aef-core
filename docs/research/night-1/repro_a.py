"""A: reproduce — the proposer offers several candidates and the turn gates one."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, cycle
from aef.harness.proposer import MemoryEvidence, RuleBasedProposer
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SRC = """RETRY_BUDGET = 3
QUALITY_THRESHOLD = 4
TIMEOUT_S = 8


def run(state, ctx, svc):
    return {}, "END"
"""


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


def make_repo(root: Path) -> GitRepo:
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text(SRC)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def memory() -> InMemoryMemoryStore:
    store = InMemoryMemoryStore()
    for i in range(2):
        store.write(
            MemoryRecord(
                id=f"rec-{i}",
                kind="failure",
                run_id=f"run-{i}",
                content={
                    "verbal_feedback": f"the run failed: budget exhausted ({i})",
                    "failing_nodes": ["answer"],
                },
            )
        )
    return store


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p1-repro-a-"))
    repo = make_repo(tmp / "repo")
    store = memory()

    ev = MemoryEvidence.from_store(store, None, graph_id=None)
    offered = RuleBasedProposer().propose_from_memory(
        ev, proposal_id="repro", path="agents/demo/graph.py", source=SRC
    )
    print(f"the proposer OFFERS {len(offered)} candidate(s) this turn:")
    for p in offered:
        print(f"  - {p.id}: {p.rationale[:76]}")

    gated: list[str] = []

    import aef.harness.loop as loop_module

    real_gate = loop_module.gate

    class _Run:
        def __init__(self) -> None:
            from aef.harness.review import Decision, Disposition

            self.decision = Decision(disposition=Disposition.REJECT, reason="stub")
            self.exit_code = 1
            self.candidate_score = 0.5
            self.incumbent_score = 0.5

    def spy(config, branch, **kw):
        gated.append(branch)
        return _Run()

    loop_module.gate = spy  # type: ignore[assignment]
    try:
        run = cycle(
            LoopConfig(repo=repo, paths=LoopPaths(root=tmp / "state"), base_ref="main"),
            now=NOW,
            workdir=tmp / "work",
            memory=store,
            agent_path="agents/demo/graph.py",
        )
    finally:
        loop_module.gate = real_gate

    print(f"\nthe turn GATED {len(gated)} candidate(s): {gated}")
    print(f"discarded without ever being measured: {len(offered) - len(gated)}")
    for line in run.lines:
        print(f"  cycle> {line}")
    branches = subprocess.run(
        ["git", "-C", str(repo.root), "branch", "--list", "loop/*"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    print(f"candidate branches created: {[b for b in branches if b.startswith('loop/')]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
