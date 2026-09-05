"""`--agent-path` naming a file the ref does not hold is an ERROR, not "no
candidate" at exit 0.

ADR 0191's F6, and it is ADR 0139's signature failure one line further down
than ADR 0188 looked. `DEFAULT_AGENT_PATH` is `agents/migrated/graph.py` —
what `aef migrate` writes into an ADOPTING repo (ADR 0149) — and aef-core has
`agents/demo/` and `agents/summary/`. `.github/workflows/loop-monitor.yml`
passed no `--agent-path`. So the moment this repo's nightly memory file
stopped being empty, the cycle printed

    $ aef loop cycle --repo . --state ... --graph-id demo_agent \\
        --corpus corpus --memory <two failure records>
      ledger verified: 0 entr(ies)
      no agent source at agents/migrated/graph.py in main
      (the ref exists; the file is not in it): no candidate
    EXIT=0

— the loop could not propose, and the workflow's own case statement reads 0
as "escalated, or nothing to propose", which is the healthy answer
(reproduced).

ADR 0189 got the SENTENCE right — it distinguishes an absent file from an
absent ref — and left the DISPOSITION wrong. A ref that exists without the
file in it is not a judgement about a candidate; it is `--agent-path` naming
something that is not there.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.main import main
from aef.harness.git import GitRepo
from aef.harness.loop import EXIT_ERROR, AgentSourceMissingError, LoopConfig, LoopPaths, cycle
from aef.harness.memory_store import FileMemoryStore
from aef.harness.zones import DEFAULT_AGENT_PATH
from aef.services.memory.base import MemoryRecord

NOW = datetime(2026, 9, 5, tzinfo=UTC)

DEMO_SOURCE = """RETRY_BUDGET = 3


def build_graph():  # pragma: no cover - never executed by these tests
    raise NotImplementedError
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """aef-core's own shape: a graph under `agents/demo/`, and nothing at all
    at `agents/migrated/graph.py`."""
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text(DEMO_SOURCE)
    (root / "agents" / "summary").mkdir()
    (root / "agents" / "summary" / "graph.py").write_text(DEMO_SOURCE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _store(tmp_path: Path) -> FileMemoryStore:
    """Two admissible failure records — a production `run_id`, so neither the
    split exclusion nor the graph filter is what this test measures."""
    store = FileMemoryStore(path=tmp_path / "memory.jsonl")
    for index in (1, 2):
        store.write(
            MemoryRecord(
                id=f"m{index}",
                agent_id="demo_agent",
                kind="failure",
                content={
                    "verbal_feedback": "the summary omitted the deadline",
                    "failing_nodes": ["work"],
                },
                run_id=f"prod-{index}",
                created_at=NOW,
            )
        )
    return store


def test_the_default_path_missing_from_the_ref_refuses_instead_of_exiting_zero(
    repo: Path, tmp_path: Path
) -> None:
    """The harness, so that every caller gets it and not only the CLI."""
    config = LoopConfig(repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"))

    with pytest.raises(AgentSourceMissingError) as excinfo:
        cycle(config, now=NOW, workdir=tmp_path / "work", memory=_store(tmp_path))

    message = str(excinfo.value)
    # It names the path it looked for and the ref it looked in ...
    assert DEFAULT_AGENT_PATH in message, message
    assert "main" in message, message
    # ... says which of the two questions failed, which is ADR 0189's wording,
    # kept ...
    assert "the ref exists; the file is not in it" in message, message
    # ... and lists what IS there, read from the ref rather than the worktree,
    # so the remedy is in the message instead of in another command.
    assert "agents/demo/graph.py" in message, message
    assert "agents/summary/graph.py" in message, message


def test_the_cli_reports_it_as_EXIT_ERROR(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 3. The workflow's case statement gives 0 to "nothing to propose",
    1 to "the candidate was rejected", 2 to a halt and 3 to "fix the
    invocation" — and this is the fourth. `>= 2` is what CI fails on, so an
    inert nightly loop now fails the job instead of showing a green tick."""
    _store(tmp_path)  # written before the run, as a scheduled job's would be

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
            "--memory",
            str(tmp_path / "memory.jsonl"),
        ]
    )
    assert code == EXIT_ERROR, code
    err = capsys.readouterr().err
    assert "AgentSourceMissingError" in err, err
    assert DEFAULT_AGENT_PATH in err, err


def test_naming_a_path_that_IS_in_the_ref_proposes(repo: Path, tmp_path: Path) -> None:
    """The control, and the fix's other half: with `--agent-path
    agents/demo/graph.py` — what the workflow now passes — the same repo,
    the same memory and the same corpus produce a candidate. A refusal that
    fired either way would have replaced a silent no-op with a loud one."""
    config = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state2"),
        # G1's default runs the repo's build command; this test is about the
        # proposal, not the verdict, so the build is a no-op that passes.
        build_commands=(("true",),),
    )

    run = cycle(
        config,
        now=NOW,
        workdir=tmp_path / "work2",
        memory=_store(tmp_path),
        agent_path="agents/demo/graph.py",
    )
    assert run.proposed is not None, run.lines
