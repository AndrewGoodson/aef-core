"""A call the loop spent is a call the loop reports (ADR 0170 defect 3).

Reproduced through the real `cycle()` with a provider that records being
asked: `--proposer llm` against a `.md` agent path spends one live call, the
reply fails `ast.parse`, the rule-based fallback has no numeric constant to
edit, and the cycle printed

    the proposer produced nothing from the available evidence: agents/persona.md
    is not Python, and this proposer edits numeric constants and Python
    structure. A prompt file's proposer is --proposer rule_based_prompt.

with the call nowhere in it — not in the summary, not in the ledger (a cycle
that proposes nothing writes no ledger entry at all), and not in
`cycles.jsonl`, whose verdict is the cycle's last line (ADR 0165).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import Corpus
from aef.harness.git import GitRepo
from aef.harness.llm_proposer import LLMProposer, ProposerSpend
from aef.harness.loop import LoopConfig, LoopPaths, cycle
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
PERSONA = "agents/persona.md"

# Prose and a markdown fence: a well-formed reply to the question the LLM
# proposer asks, and one `ast.parse` refuses.
MARKDOWN_REPLY = (
    "Tell the agent to end with a verdict line.\n\n"
    "```markdown agents/persona.md\n# Persona\n\nAnswer, then emit VERDICT.\n```\n"
)


@dataclass
class RecordingProvider(ModelProvider):
    reply: str = MARKDOWN_REPLY
    error: str = ""
    requests: list[CompletionRequest] = field(default_factory=list)
    name: str = "recording"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.error:
            raise ModelProviderError(self.error)
        return CompletionResult(
            content=self.reply, model=request.model, input_tokens=1, output_tokens=1
        )


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, agent: str = PERSONA, body: str = "# Persona\n\nAnswer.\n") -> GitRepo:
    root = tmp_path / "repo"
    (root / agent).parent.mkdir(parents=True, exist_ok=True)
    (root / agent).write_text(body)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@test")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "incumbent")
    return GitRepo(root=root)


def _memory() -> InMemoryMemoryStore:
    store = InMemoryMemoryStore()
    for run in ("r1", "r2"):
        store.write(
            MemoryRecord(
                kind="failure",
                run_id=run,
                agent_id="a",
                content={
                    "verbal_feedback": "the reply carried no verdict line",
                    "failing_nodes": ["prompt_agent"],
                },
            )
        )
    return store


def _cycle(tmp_path: Path, provider: ModelProvider, *, proposer: str = "llm", agent: str = PERSONA):  # type: ignore[no-untyped-def]
    repo = _repo(tmp_path, agent=agent)
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        corpus=Corpus(root=tmp_path / "corpus", scenarios=()),
        proposer=proposer,
        proposer_provider=provider if proposer == "llm" else None,
        proposer_model="a-model" if proposer == "llm" else None,
    )
    return cycle(config, now=NOW, workdir=tmp_path / "work", memory=_memory(), agent_path=agent)


# --------------------------------------------------------------------------
# the defect
# --------------------------------------------------------------------------


def test_a_spent_call_with_no_proposal_is_still_reported(tmp_path: Path) -> None:
    provider = RecordingProvider()
    run = _cycle(tmp_path, provider)

    assert len(provider.requests) == 1, "the fixture did not spend a call"
    assert run.proposed is None
    assert run.proposer_calls == 1
    assert any("spent 1 live model call" in line for line in run.lines), run.lines


def test_the_rejection_reason_survives_the_empty_fallback(tmp_path: Path) -> None:
    """The rejection used to live only in the fallback proposal's rationale,
    so on a repo where the fallback proposes nothing it was lost with it."""
    run = _cycle(tmp_path, RecordingProvider())
    assert any("LLMProposalRejected" in line for line in run.lines), run.lines
    assert any("does not parse as Python" in line for line in run.lines), run.lines


def test_the_spend_reaches_the_journal_verdict(tmp_path: Path) -> None:
    """`cmd_cycle` journals `lines[-1]` when nothing was proposed (ADR 0165).
    A note appended as its own line would print and never be recorded."""
    run = _cycle(tmp_path, RecordingProvider())
    assert "spent 1 live model call" in run.lines[-1]


def test_a_provider_outage_still_counts_the_attempt(tmp_path: Path) -> None:
    """Counted before the provider answers: a request that errors after it
    left has still been spent, and this number must be a floor on the cost."""
    provider = RecordingProvider(error="rate limited")
    run = _cycle(tmp_path, provider)
    assert run.proposer_calls == 1
    assert any("rate limited" in line for line in run.lines), run.lines


# --------------------------------------------------------------------------
# it does not fire where there was nothing to spend
# --------------------------------------------------------------------------


def test_a_proposer_that_asks_no_model_reports_no_spend(tmp_path: Path) -> None:
    run = _cycle(tmp_path, RecordingProvider(), proposer="rule_based_prompt")
    assert run.proposer_calls == 0
    assert not any("model call" in line for line in run.lines), run.lines


def test_a_spend_note_is_added_when_a_candidate_was_produced(tmp_path: Path) -> None:
    """A fallback that DOES propose still spent the call, and the summary
    says so beside the rationale's own fallback note."""
    tmp = tmp_path / "py"
    provider = RecordingProvider()
    repo = _repo(tmp, agent="agents/graph.py", body="RETRIES = 3\n")
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp / "state"),
        corpus=Corpus(root=tmp / "corpus", scenarios=()),
        proposer="llm",
        proposer_provider=provider,
        proposer_model="a-model",
        entrypoint=None,
    )
    run = cycle(
        config, now=NOW, workdir=tmp / "work", memory=_memory(), agent_path="agents/graph.py"
    )
    assert run.proposed is not None, run.lines
    assert run.proposer_calls == 1
    assert any("spent 1 live model call" in line for line in run.lines), run.lines


# --------------------------------------------------------------------------
# the accounting object itself
# --------------------------------------------------------------------------


def test_an_unasked_proposer_has_nothing_to_say() -> None:
    assert ProposerSpend().note() == ""


def test_only_the_first_rejection_is_rendered() -> None:
    """A cycle asks once. A list of rejections would invite reading a retry
    loop into a single call."""
    spend = ProposerSpend()
    spend.record_attempt()
    spend.record_rejection(ValueError("first"))
    spend.record_rejection(ValueError("second"))
    assert "first" in spend.note() and "second" not in spend.note()


def test_the_spend_holds_no_influence_over_a_proposal() -> None:
    """It is the one piece of mutable state in the proposer; nothing reads it
    back, so clearing it cannot change what is proposed."""
    proposer = LLMProposer(provider=RecordingProvider(), model="m")
    assert isinstance(proposer.spend, ProposerSpend)
    with pytest.raises(AttributeError):
        proposer.spend = ProposerSpend()  # type: ignore[misc] - frozen dataclass
