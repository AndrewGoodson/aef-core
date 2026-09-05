"""`--proposer rule_based_prompt` through `LoopConfig`, `cycle` and the CLI
(ADR 0157).

The proposer's own behaviour is pinned in `test_prompt_proposer.py`. What is
pinned here is the join: that the switch reaches it, that the config it is
built from is the one the gates read, that it is nobody's default, and that a
cycle which proposes nothing now says which of the several reasons applied.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import Corpus
from aef.harness.git import GitRepo
from aef.harness.loop import PROPOSERS, LoopConfig, LoopPaths, _build_proposer, cycle
from aef.harness.prompt_proposer import RuleBasedPromptProposer
from aef.harness.proposer import RuleBasedProposer
from aef.harness.zones import ZonePolicy
from aef.services.memory.base import MemoryRecord

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
AGENT_ROOT = ".claude/agents"
PERSONA = f"{AGENT_ROOT}/accela-agent.md"
BODY = """---
name: marlin-accela
---

# Marlin Accela agent

Purpose: operate the Accela connector.
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    (root / AGENT_ROOT).mkdir(parents=True)
    (root / PERSONA).write_text(BODY)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _record(run_id: str, record_id: str) -> MemoryRecord:
    return MemoryRecord(
        kind="failure",
        content={
            "verbal_feedback": "1 failure signal: errors[0] node 'prompt_agent' raised",
            "failing_nodes": ["prompt_agent"],
        },
        run_id=run_id,
        agent_id="marlin-accela",
        id=record_id,
        created_at=NOW,
    )


class _Store:
    """The one `MemoryStore` call `MemoryEvidence.from_store` makes."""

    def __init__(self, *records: MemoryRecord) -> None:
        self._records = list(records)

    def query(self, kind: str, *, agent_id: str | None = None, limit: int = 50):  # type: ignore[no-untyped-def]
        return list(self._records)


def _config(repo: GitRepo, tmp_path: Path, **kwargs: object) -> LoopConfig:
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        zone_policy=ZonePolicy(agent_root=AGENT_ROOT),
        graph_id="marlin-accela",
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_switch_builds_the_prompt_proposer_from_the_gates_own_config(
    repo: GitRepo, tmp_path: Path
) -> None:
    corpus = Corpus(root=tmp_path / "corpus")
    config = _config(repo, tmp_path, proposer="rule_based_prompt", corpus=corpus)
    built = _build_proposer(config)
    assert isinstance(built, RuleBasedPromptProposer)
    # The same zone policy, graph id and corpus the gates are given — a
    # proposer judged by one policy and built from another is ADR 0084's
    # defect, and G5 measured drift against the wrong tree because of it.
    assert built.zone_policy == config.zone_policy
    assert built.graph_id == "marlin-accela"
    assert built.corpus is corpus


def test_it_is_nobody_s_default(repo: GitRepo, tmp_path: Path) -> None:
    assert PROPOSERS == ("rule_based", "rule_based_prompt", "llm")
    # Not even for a markdown agent path: the default is the default.
    config = _config(repo, tmp_path)
    assert config.proposer == "rule_based"
    assert isinstance(_build_proposer(config), RuleBasedProposer)


def test_an_unknown_proposer_is_still_refused_at_construction(
    repo: GitRepo, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="must be one of"):
        _config(repo, tmp_path, proposer="rule_based_prompts")


def test_a_cycle_proposes_a_bullet_and_never_touches_main(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path, proposer="rule_based_prompt")
    run = cycle(
        config,
        now=NOW,
        workdir=tmp_path / "work",
        memory=_Store(_record("r1", "m1"), _record("r2", "m2")),
        agent_path=PERSONA,
    )
    assert run.proposed is not None and run.proposed.endswith("-prompt")
    candidate = repo.show(f"loop/{run.proposed}", PERSONA)
    assert "## Lessons (aef)" in candidate
    assert "sig=failure:prompt_agent" in candidate
    assert repo.show("main", PERSONA) == BODY
    assert any("proposer=rule_based_prompt" in line for line in run.lines)


def test_a_cycle_that_proposes_nothing_says_which_reason_applied(
    repo: GitRepo, tmp_path: Path
) -> None:
    config = _config(repo, tmp_path, proposer="rule_based_prompt")
    run = cycle(
        config,
        now=NOW,
        workdir=tmp_path / "work",
        # One run: an episode, not a lesson.
        memory=_Store(_record("r1", "m1")),
        agent_path=PERSONA,
    )
    assert run.proposed is None
    assert any("the most recurrent seen in 1 distinct run(s)" in line for line in run.lines)


def test_the_default_proposer_on_a_prompt_file_names_the_one_that_fits(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The silence ADR 0157 reproduced: `rule_based` has no operation on a
    `.md`, said nothing about why, and the cycle read as 'no candidate'."""
    config = _config(repo, tmp_path)
    run = cycle(
        config,
        now=NOW,
        workdir=tmp_path / "work",
        memory=_Store(_record("r1", "m1"), _record("r2", "m2")),
        agent_path=PERSONA,
    )
    assert run.proposed is None
    assert any("--proposer rule_based_prompt" in line for line in run.lines)


def test_the_cli_offers_the_choice_and_explains_it(capsys: pytest.CaptureFixture[str]) -> None:
    from aef.cli.main import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["loop", "cycle", "--help"])
    help_text = capsys.readouterr().out
    assert "rule_based_prompt" in help_text
    assert "Lessons (aef)" in help_text
