"""The LLM proposer (ADR 0122), against a fake provider — no process, no
network. What is pinned is what the model is NOT trusted with: the
citations, the path, the parse, the size, the imports, the owner-only
declarations, and the fallback. The four mutations named in
`ABOVE_90_LOOP.md` each have a test here that fails when the corresponding
check is removed from `aef/harness/llm_proposer.py`."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import ledger
from aef.harness.corpus import Split
from aef.harness.gates.g0_static_safety import DEFAULT_IMPORT_ALLOWLIST, DEFAULT_MAX_CHANGED_LINES
from aef.harness.git import GitRepo
from aef.harness.llm_proposer import LLMProposer
from aef.harness.loop import PROPOSERS, LoopConfig, LoopPaths, cycle
from aef.harness.proposer import (
    Citation,
    CitationKind,
    MemoryEvidence,
    ProposalError,
    RuleBasedProposer,
)
from aef.harness.transformations import RETRY_CONSTANT
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)
from aef.services.memory.base import MemoryRecord

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
PATH = "agents/flaky/graph.py"

SOURCE = '''"""A tiny agent."""

from aef.kernel import END, Edge, Graph, Node
from aef.kernel.contracts import SideEffect
from aef.state import StateDelta

QUALITY_THRESHOLD = 3


def fetch(state, ctx, services):
    raise RuntimeError("flaky upstream refused the first attempt")


def finish(state, ctx, services):
    return StateDelta(working_memory={"done": True}), END


def build_graph():
    return Graph(
        id="flaky_agent",
        version="0.1.0",
        nodes={
            "fetch": Node(
                id="fetch",
                version="0.1.0",
                fn=fetch,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:fetch",
            ),
            "finish": Node(id="finish", version="0.1.0", fn=finish, deterministic=True),
        },
        edges=[Edge(from_node="fetch", to_node="finish")],
        entry_node="fetch",
    )
'''

# A change the model might plausibly make: the fetch node stops raising.
GOOD_BODY = SOURCE.replace(
    '    raise RuntimeError("flaky upstream refused the first attempt")\n',
    '    return StateDelta(working_memory={"fetched": True}), "finish"\n',
)
assert GOOD_BODY != SOURCE


def _reply(
    body: str, *, prose: str = "Stop raising; return the fetched flag.", info: str = ""
) -> str:
    fence = f"```python {info or PATH}"
    return f"{prose}\n\n{fence}\n{body}```\n"


@dataclass
class FakeProvider(ModelProvider):
    name = "fake"
    replies: list[str] = field(default_factory=list)
    requests: list[CompletionRequest] = field(default_factory=list)
    fail: bool = False

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.fail:
            raise ModelProviderError("fake outage")
        reply = self.replies.pop(0) if self.replies else ""
        return CompletionResult(content=reply, model="fake-model", input_tokens=1, output_tokens=1)


def _record(record_id: str = "mem-1") -> MemoryRecord:
    return MemoryRecord(
        kind="failure",
        content={"failing_nodes": ["fetch"], "verbal_feedback": "fetch raised: flaky upstream"},
        run_id="r1",
        agent_id="flaky",
        id=record_id,
    )


def _evidence() -> MemoryEvidence:
    return MemoryEvidence(records=(_record(),))


def _proposer(provider: FakeProvider) -> LLMProposer:
    return LLMProposer(provider=provider, model="m")


def _propose(provider: FakeProvider, source: str = SOURCE):
    return _proposer(provider).propose_from_memory(
        _evidence(), proposal_id="p", path=PATH, source=source
    )


# ---------------------------------------------------------------------------
# The happy path: prose from the model, everything else from code
# ---------------------------------------------------------------------------
def test_a_valid_reply_becomes_a_grounded_proposal_at_the_same_path() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    (proposal,) = _propose(provider)
    assert proposal.path == PATH
    assert proposal.original == SOURCE
    assert proposal.proposed == GOOD_BODY
    assert proposal.id == "p-llm"
    assert not proposal.is_control
    # Citations are COMPUTED from the evidence, never claimed by the model.
    assert proposal.grounded_in == _evidence().citations()
    assert proposal.grounded_in[0].kind is CitationKind.MEMORY
    assert proposal.grounded_in[0].source == "mem-1"
    # Rationale = model prose + the computed citation list (added, not substituted).
    assert proposal.rationale.startswith("Stop raising; return the fetched flag.")
    assert "Evidence: mem-1 (memory): fetch raised: flaky upstream" in proposal.rationale
    assert "fell back" not in proposal.rationale
    assert len(provider.requests) == 1


def test_the_prompt_carries_the_source_the_failures_and_the_gate_rules() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    _propose(provider)
    request = provider.requests[0]
    assert request.model == "m"
    system, user = request.messages
    assert system.role == "system" and user.role == "user"
    assert SOURCE in user.content
    assert f"File: {PATH}" in user.content
    assert "mem-1: fetch raised: flaky upstream" in user.content
    assert "Nodes the failures blame: fetch" in user.content
    # The rules the model is told are the gates' own, not a paraphrase.
    for module in ("dataclasses", "json", "aef"):
        assert module in system.content
    assert "aef.harness" in system.content
    assert "fallback_node_id" in system.content
    assert str(DEFAULT_MAX_CHANGED_LINES) in system.content


def test_no_evidence_means_no_proposal_and_no_model_call() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    result = _proposer(provider).propose_from_memory(
        MemoryEvidence(), proposal_id="p", path=PATH, source=SOURCE
    )
    assert result == ()
    assert provider.requests == []


# ---------------------------------------------------------------------------
# Mutation 1 — citations from train only, refused before any call
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("split", [Split.VALIDATION, Split.HOLDOUT])
def test_a_validation_or_holdout_citation_is_refused_not_emitted(split: Split) -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    with pytest.raises(ProposalError, match="train split only"):
        _proposer(provider).propose(
            proposal_id="p",
            path=PATH,
            source=SOURCE,
            citations=(Citation(source="s-9", split=split),),
        )
    # Refused BEFORE the model was asked: no call, no fallback, no proposal.
    assert provider.requests == []


def test_a_train_citation_is_admissible() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    proposal = _proposer(provider).propose(
        proposal_id="p",
        path=PATH,
        source=SOURCE,
        citations=(Citation(source="s-1", split=Split.TRAIN),),
    )
    assert proposal.grounded_in == (Citation(source="s-1", split=Split.TRAIN),)


def test_no_citations_at_all_is_ungrounded_and_refused() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    with pytest.raises(ProposalError, match="no evidence"):
        _proposer(provider).propose(proposal_id="p", path=PATH, source=SOURCE, citations=())
    assert provider.requests == []


# ---------------------------------------------------------------------------
# Mutation 2 — a reply that does not parse falls back
# ---------------------------------------------------------------------------
def test_a_reply_that_does_not_parse_falls_back_to_rule_based_and_says_so() -> None:
    provider = FakeProvider(replies=[_reply("def fetch(:\n    pass\n")])
    proposals = _propose(provider)
    assert len(provider.requests) == 1
    # Exactly the rule-based output, with the reason appended.
    expected = RuleBasedProposer().propose_from_memory(
        _evidence(), proposal_id="p", path=PATH, source=SOURCE
    )
    assert [p.proposed for p in proposals] == [p.proposed for p in expected]
    assert all("[llm proposer fell back to rule-based: " in p.rationale for p in proposals)
    assert "does not parse as Python" in proposals[0].rationale
    # The garbage never became a candidate.
    assert all("def fetch(:" not in p.proposed for p in proposals)


# ---------------------------------------------------------------------------
# Mutation 3 — a path outside Zone A is refused before any call
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    ["aef/harness/proposer.py", "tests/harness/test_x.py", "src/agent.py", "corpus/x.py"],
)
def test_a_path_outside_zone_a_is_refused_before_the_model_is_asked(path: str) -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY, info=path)])
    with pytest.raises(ProposalError, match="Only Zone A"):
        _proposer(provider).propose(
            proposal_id="p",
            path=path,
            source=SOURCE,
            citations=_evidence().citations(),
        )
    assert provider.requests == []


def test_a_reply_addressed_to_another_file_falls_back() -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY, info="agents/other/graph.py")])
    proposals = _propose(provider)
    assert "addressed to 'agents/other/graph.py'" in proposals[0].rationale
    assert all(p.path == PATH and p.proposed != GOOD_BODY for p in proposals)


def test_a_fence_that_names_no_path_is_accepted_and_the_path_stays_ours() -> None:
    provider = FakeProvider(replies=["prose\n\n```python\n" + GOOD_BODY + "```\n"])
    (proposal,) = _propose(provider)
    assert proposal.path == PATH and proposal.proposed == GOOD_BODY


# ---------------------------------------------------------------------------
# Mutation 4 — provider error falls back
# ---------------------------------------------------------------------------
def test_a_provider_error_falls_back_to_rule_based_and_says_so() -> None:
    proposals = _propose(FakeProvider(fail=True))
    assert proposals, "the fallback produced nothing"
    assert "fell back to rule-based: fake outage" in proposals[0].rationale
    expected = RuleBasedProposer().propose_from_memory(
        _evidence(), proposal_id="p", path=PATH, source=SOURCE
    )
    assert [p.proposed for p in proposals] == [p.proposed for p in expected]
    assert RETRY_CONSTANT not in proposals[0].proposed  # nothing invented on the way down


def test_an_empty_reply_falls_back() -> None:
    proposals = _propose(FakeProvider(replies=[""]))
    assert "returned nothing" in proposals[0].rationale


# ---------------------------------------------------------------------------
# The rest of the validation, each pinned on its own
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    ["import os\n", "import subprocess\n", "from aef.harness import ledger\n", "import socket\n"],
)
def test_an_import_g0_would_reject_falls_back(line: str) -> None:
    body = GOOD_BODY.replace(
        "from aef.state import StateDelta\n", f"from aef.state import StateDelta\n{line}"
    )
    assert line in body
    proposals = _propose(FakeProvider(replies=[_reply(body)]))
    assert "G0 would reject the reply" in proposals[0].rationale
    assert all(line not in p.proposed for p in proposals)


def test_a_forbidden_call_falls_back_too() -> None:
    body = GOOD_BODY.replace("QUALITY_THRESHOLD = 3\n", 'QUALITY_THRESHOLD = eval("3")\n')
    proposals = _propose(FakeProvider(replies=[_reply(body)]))
    assert "G0 would reject" in proposals[0].rationale and "eval" in proposals[0].rationale


def test_a_finding_the_incumbent_already_had_is_not_charged_to_the_reply() -> None:
    """Refuses what G0 would refuse and nothing else: a pre-existing finding
    is the incumbent's, and the reply must not be blamed for it."""
    tainted = SOURCE.replace(
        "from aef.state import StateDelta\n", "from aef.state import StateDelta\nimport os\n"
    )
    body = tainted.replace("QUALITY_THRESHOLD = 3", "QUALITY_THRESHOLD = 4")
    (proposal,) = _propose(FakeProvider(replies=[_reply(body)]), source=tainted)
    assert proposal.proposed == body and "fell back" not in proposal.rationale


def test_the_allowlist_is_g0s_own_object_not_a_copy() -> None:
    provider = FakeProvider()
    assert _proposer(provider).import_allowlist is DEFAULT_IMPORT_ALLOWLIST
    assert _proposer(provider).max_changed_lines == DEFAULT_MAX_CHANGED_LINES
    # And the module holds no second list: every module name that appears in
    # a set/frozenset literal of the proposer's source is a test fixture, not
    # an allowlist. Checked by AST so a future "just add os here" fails.
    tree = ast.parse(Path("aef/harness/llm_proposer.py").read_text())
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Set)]
    assert literals == [], "llm_proposer.py declares a set literal; the allowlist is G0's"


def test_over_the_line_budget_falls_back() -> None:
    body = GOOD_BODY + "".join(f"X{i} = {i}\n" for i in range(DEFAULT_MAX_CHANGED_LINES + 1))
    proposals = _propose(FakeProvider(replies=[_reply(body)]))
    assert f"exceeds G0's budget of {DEFAULT_MAX_CHANGED_LINES}" in proposals[0].rationale


def test_a_budget_override_reaches_the_proposer() -> None:
    body = GOOD_BODY + "X1 = 1\nX2 = 2\nX3 = 3\n"
    proposer = LLMProposer(
        provider=FakeProvider(replies=[_reply(body)]), model="m", max_changed_lines=2
    )
    proposals = proposer.propose_from_memory(_evidence(), proposal_id="p", path=PATH, source=SOURCE)
    assert "exceeds G0's budget of 2" in proposals[0].rationale


def test_an_identical_file_is_an_empty_diff_and_falls_back() -> None:
    proposals = _propose(FakeProvider(replies=[_reply(SOURCE)]))
    assert "empty diff" in proposals[0].rationale


@pytest.mark.parametrize("count", [0, 2])
def test_anything_but_one_fenced_block_falls_back(count: int) -> None:
    text = "no code here" if count == 0 else _reply(GOOD_BODY) + _reply(GOOD_BODY)
    proposals = _propose(FakeProvider(replies=[text]))
    assert f"expected exactly one fenced code block in the reply, found {count}" in (
        proposals[0].rationale
    )


def test_touching_an_owner_only_declaration_falls_back() -> None:
    """G4's list, through the catalogue's own check: a reply that adds
    `fallback_node_id` would be a security event at the gate and halt the
    loop. The proposer refuses it first."""
    body = GOOD_BODY.replace(
        "                deterministic=False,\n",
        '                deterministic=False,\n                fallback_node_id="finish",\n',
    )
    assert "fallback_node_id" in body
    proposals = _propose(FakeProvider(replies=[_reply(body)]))
    assert "owner-only safety declaration" in proposals[0].rationale
    assert all("fallback_node_id" not in p.proposed for p in proposals)


def test_the_prose_is_capped_so_the_ledger_stays_readable() -> None:
    proposals = _propose(FakeProvider(replies=[_reply(GOOD_BODY, prose="x" * 5000)]))
    head, _, _ = proposals[0].rationale.partition("\n\nEvidence:")
    assert len(head) == 600


# ---------------------------------------------------------------------------
# Wiring: LoopConfig.proposer, cycle, the CLI
# ---------------------------------------------------------------------------
def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    (root / "agents" / "flaky").mkdir(parents=True)
    (root / "agents" / "flaky" / "graph.py").write_text(SOURCE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


class _Store:
    """The two MemoryStore calls the evidence builder makes."""

    def query(self, kind: str, *, agent_id: str | None = None, limit: int = 50):  # type: ignore[no-untyped-def]
        return [_record()]


def test_the_default_proposer_is_rule_based_and_never_calls_the_model() -> None:
    # `rule_based_prompt` (ADR 0157) joined the list and did NOT become a
    # default for anything — see `tests/harness/test_prompt_proposer_wiring.py`.
    assert PROPOSERS == ("rule_based", "rule_based_prompt", "llm")
    provider = FakeProvider(fail=True)
    config = LoopConfig(
        repo=GitRepo(root=Path(".")),
        paths=LoopPaths(root=Path("/nonexistent")),
        proposer_provider=provider,
        proposer_model="m",
    )
    assert config.proposer == "rule_based"


def test_llm_without_a_provider_or_model_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="proposer='llm' needs"):
        LoopConfig(repo=GitRepo(root=Path(".")), paths=LoopPaths(root=Path("/x")), proposer="llm")
    with pytest.raises(ValueError, match="proposer='llm' needs"):
        LoopConfig(
            repo=GitRepo(root=Path(".")),
            paths=LoopPaths(root=Path("/x")),
            proposer="llm",
            proposer_provider=FakeProvider(),
        )
    with pytest.raises(ValueError, match="must be one of"):
        LoopConfig(repo=GitRepo(root=Path(".")), paths=LoopPaths(root=Path("/x")), proposer="gpt")


def test_cycle_with_the_llm_proposer_materialises_the_models_file(
    repo: GitRepo, tmp_path: Path
) -> None:
    provider = FakeProvider(replies=[_reply(GOOD_BODY)])
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        proposer="llm",
        proposer_provider=provider,
        proposer_model="m",
    )
    run = cycle(config, now=NOW, workdir=tmp_path / "work", memory=_Store(), agent_path=PATH)
    assert run.proposed is not None and run.proposed.endswith("-llm")
    assert repo.show(f"loop/{run.proposed}", PATH) == GOOD_BODY
    assert repo.show("main", PATH) == SOURCE
    assert len(provider.requests) == 1
    assert any("proposer=llm" in line for line in run.lines)
    gated = [e for e in ledger.read(config.paths.ledger_dir) if e.kind is ledger.EventKind.GATED]
    assert gated and gated[0].detail["proposer"] == "llm"
    assert gated[0].detail["grounded_in"] == ["mem-1 (memory): fetch raised: flaky upstream"]


def test_cycle_with_the_default_proposer_never_touches_the_provider(
    repo: GitRepo, tmp_path: Path
) -> None:
    provider = FakeProvider(fail=True)
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        proposer_provider=provider,
        proposer_model="m",
    )
    run = cycle(config, now=NOW, workdir=tmp_path / "work", memory=_Store(), agent_path=PATH)
    assert run.proposed is not None and not run.proposed.endswith("-llm")
    assert provider.requests == []
    gated = [e for e in ledger.read(config.paths.ledger_dir) if e.kind is ledger.EventKind.GATED]
    assert gated[0].detail["proposer"] == "rule_based"


def test_cycle_reports_the_fallback_reason(repo: GitRepo, tmp_path: Path) -> None:
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        proposer="llm",
        proposer_provider=FakeProvider(fail=True),
        proposer_model="m",
    )
    run = cycle(config, now=NOW, workdir=tmp_path / "work", memory=_Store(), agent_path=PATH)
    assert any("fell back to rule-based: fake outage" in line for line in run.lines)


def test_the_cli_flag_exists_defaults_off_and_builds_the_harness_provider() -> None:
    import aef.cli.loop as loop_cli
    from aef.cli.main import build_parser
    from aef.providers.harness_provider import ClaudeCodeProvider

    parser = build_parser()
    base = ["loop", "run", "--state", "/tmp/s", "--workdir", "/tmp/w"]
    assert loop_cli._config(parser.parse_args(base)).proposer == "rule_based"
    args = parser.parse_args([*base, "--proposer", "llm", "--proposer-model", "claude-x-1"])
    config = loop_cli._config(args)
    assert config.proposer == "llm" and config.proposer_model == "claude-x-1"
    assert isinstance(config.proposer_provider, ClaudeCodeProvider)
    assert config.proposer_provider.default_model == "claude-x-1"
    with pytest.raises(ValueError, match="--proposer-model"):
        loop_cli._config(parser.parse_args([*base, "--proposer", "llm"]))
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--proposer", "gpt"])
    # `cycle` takes the same flags.
    cyc = parser.parse_args(["loop", "cycle", "--state", "/tmp/s", "--workdir", "/tmp/w"])
    assert cyc.proposer == "rule_based"


def test_the_proposer_imports_no_vendor_sdk() -> None:
    """Constraint #3, for the one harness module that talks to a model:
    `aef.providers.base` only, never a vendor SDK or a concrete adapter."""
    tree = ast.parse(Path("aef/harness/llm_proposer.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    providers = {m for m in imported if m.startswith("aef.providers")}
    assert providers == {"aef.providers.base"}
    assert not {m for m in imported if m.split(".")[0] in {"anthropic", "openai", "mem0", "neo4j"}}
