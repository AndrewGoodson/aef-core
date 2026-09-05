"""A prompt-file agent runs as a graph node (ADR 0152, M1).

Reproduce-first. The defect these tests pin is not a crash: `aef migrate`
scans for functions whose bodies touch a vendor SDK, and every eligible repo
in the 2026-09-04 survey has **zero** of those — its agents are
`.claude/agents/*.md` personas run by a coding harness. On the marlin pilot
clone the command reported

    scanned 38 Python file(s)
    found 0 call site(s): 0 wrapped, 0 skipped

with eight agents sitting in `.claude/agents/`, none of them seen. See
`tests/cli/test_migrate_prompt_agents.py` for the migration half; this file
pins the node that makes a persona executable, and the safety property that
comes with it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.kernel import END, Edge, Graph, GraphExecutor, Services, SideEffect
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
from aef.reasoning.prompt_agent import (
    PromptAgentError,
    make_prompt_agent_node,
    parse_agent_file,
    prompt_agent_idempotency_key,
)
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

PERSONA = """---
name: marlin-accela
description: Accesses the Accela Construct v4 API for permit records.
tools: Read, Write, Bash
model: opus
---

# Marlin Accela agent

Never invent credentials. Keep the connector disabled until Marlin-owned
credentials exist.
"""


class _Recorder(ModelProvider):
    name = "recorder"

    def __init__(self, reply: str = "the answer") -> None:
        self.reply = reply
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            content=self.reply, model="test-model", input_tokens=11, output_tokens=7
        )


def _services(provider: ModelProvider) -> Services:
    return Services(
        model_provider=provider,
        memory=InMemoryMemoryStore(),
        knowledge=InMemoryKnowledgeStore(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        clock=lambda: datetime(2026, 9, 4, tzinfo=UTC),
    )


def _graph(agent_file: str) -> Graph:
    return Graph(
        id="marlin-accela",
        version="0.1.0",
        nodes={
            "prompt_agent": make_prompt_agent_node(
                agent_file=agent_file, agent_name="marlin-accela", route="reflect"
            ),
            "reflect": make_reflect_node(route="consolidate"),
            "consolidate": make_consolidate_node(route=END),
        },
        edges=[
            Edge(from_node="prompt_agent", to_node="reflect"),
            Edge(from_node="reflect", to_node="consolidate"),
        ],
        entry_node="prompt_agent",
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_frontmatter_gives_the_name_and_the_body_is_the_system_prompt() -> None:
    definition = parse_agent_file(PERSONA)
    assert definition.name == "marlin-accela"
    assert definition.description.startswith("Accesses the Accela")
    assert definition.body.startswith("# Marlin Accela agent")
    assert "---" not in definition.body


def test_capability_frontmatter_is_reported_and_never_acted_on() -> None:
    """`tools:` and `model:` are read so the report can name them, and they
    reach no request. Honouring a markdown file's capability grant is exactly
    what `PolicyEngine`'s deny-by-default exists to refuse."""
    definition = parse_agent_file(PERSONA)
    assert definition.unhonoured_keys == ("model", "tools")
    assert "tools" not in definition.body.lower().split("\n")[0]


def test_a_file_with_no_frontmatter_is_still_an_agent() -> None:
    definition = parse_agent_file("You are a reviewer.\n", fallback_name="reviewer-agent")
    assert definition.name == "reviewer-agent"
    assert definition.body == "You are a reviewer."


def test_a_horizontal_rule_further_down_is_not_frontmatter() -> None:
    text = "# Heading\n\nsome prose\n\n---\n\nname: not-a-name\n"
    definition = parse_agent_file(text, fallback_name="stem")
    assert definition.name == "stem"
    assert definition.body.startswith("# Heading")


def test_an_unclosed_fence_is_read_as_a_body_not_lost_as_metadata() -> None:
    definition = parse_agent_file("---\nname: x\n\nYou are x.\n", fallback_name="stem")
    assert definition.name == "stem"
    assert "You are x." in definition.body


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------
def test_the_persona_is_the_system_message_and_the_objective_is_the_user_turn(
    tmp_path: Path,
) -> None:
    (tmp_path / "persona.md").write_text(PERSONA, encoding="utf-8")
    provider = _Recorder()
    node = make_prompt_agent_node(
        agent_file=str(tmp_path / "persona.md"), agent_name="marlin-accela"
    )
    state = AEFState(run_id="r1", agent_id="a1", objective="Reconcile the Sarasota cap counts.")
    delta, route = node.fn(state, _ctx(), _services(provider))

    assert route == "reflect"
    request = provider.requests[0]
    roles = [m.role for m in request.messages]
    assert roles == ["system", "user"]
    assert request.messages[0].content.startswith("# Marlin Accela agent")
    assert request.messages[1].content == "Reconcile the Sarasota cap counts."
    # The reply, plus the run's own record of what contained it (ADR 0169).
    # `_Recorder` declares nothing, so the containment is honestly unknown —
    # never defaulted to the guarantee `ClaudeCodeProvider` happens to give.
    assert delta.working_memory["prompt_agent"] == "the answer"
    assert delta.working_memory["prompt_agent__containment"] == {
        "provider": "recorder",
        "isolation": [],
        "persona_role": "unknown",
    }
    assert set(delta.working_memory) == {"prompt_agent", "prompt_agent__containment"}


def test_the_request_carries_no_tools_and_no_capability_from_the_frontmatter(
    tmp_path: Path,
) -> None:
    """THE SAFETY PROPERTY: the prompt runs, the agent's tools do not.

    `CompletionRequest` has five fields and none of them is a tool list, so
    the persona's `tools: Read, Write, Bash` cannot reach the provider even in
    principle — and this test fails the day someone adds a field and wires the
    frontmatter into it."""
    (tmp_path / "persona.md").write_text(PERSONA, encoding="utf-8")
    provider = _Recorder()
    node = make_prompt_agent_node(
        agent_file=str(tmp_path / "persona.md"), agent_name="marlin-accela"
    )
    node.fn(AEFState(run_id="r1", agent_id="a1", objective="go"), _ctx(), _services(provider))

    request = provider.requests[0]
    assert not hasattr(request, "tools")
    rendered = " ".join(m.content for m in request.messages)
    # The persona body is sent verbatim, so the WORD "Bash" may appear in it;
    # what must not appear is the frontmatter block that granted it.
    assert "tools: Read, Write, Bash" not in rendered
    assert request.model == "", "the provider's configured default must answer (ADR 0123)"


def test_the_node_declares_what_a_model_call_is() -> None:
    node = make_prompt_agent_node(agent_file="x.md", agent_name="a")
    assert node.deterministic is False
    assert node.side_effects is SideEffect.EXTERNAL_CALL
    assert node.idempotency_key_fn is not None


def test_the_idempotency_key_is_the_agent_name_and_the_objective() -> None:
    node = make_prompt_agent_node(agent_file="x.md", agent_name="marlin-accela")
    assert node.idempotency_key_fn is not None
    key = node.idempotency_key_fn(AEFState(run_id="r1", agent_id="a1", objective="count caps"))
    assert key == prompt_agent_idempotency_key("marlin-accela", "count caps")
    # Same persona, same question, same key — across runs, which is what makes
    # a repeat traceable to its cause.
    other = node.idempotency_key_fn(AEFState(run_id="r2", agent_id="a1", objective="count caps"))
    assert other == key
    # A different question is a different call.
    changed = node.idempotency_key_fn(
        AEFState(run_id="r1", agent_id="a1", objective="count parcels")
    )
    assert changed != key
    # And a different persona is too.
    assert prompt_agent_idempotency_key("marlin-azure", "count caps") != key


def test_the_persona_is_read_at_execution_time_so_an_edit_takes_effect(
    tmp_path: Path,
) -> None:
    """The reason ADR 0152 puts the `.md` in Zone A at all: a proposer that
    appends a lesson to the prompt changes the next run with no regeneration
    step in between. Baking the body into the generated module would have made
    the Zone A widening buy nothing."""
    persona = tmp_path / "persona.md"
    persona.write_text(PERSONA, encoding="utf-8")
    provider = _Recorder()
    node = make_prompt_agent_node(agent_file=str(persona), agent_name="marlin-accela")
    state = AEFState(run_id="r1", agent_id="a1", objective="go")

    node.fn(state, _ctx(), _services(provider))
    persona.write_text(PERSONA + "\n## Lessons (aef)\n- Always name the county.\n", "utf-8")
    node.fn(state, _ctx(), _services(provider))

    assert "Always name the county" not in provider.requests[0].messages[0].content
    assert "Always name the county" in provider.requests[1].messages[0].content


def test_a_missing_persona_is_a_named_refusal_listing_what_was_tried(tmp_path: Path) -> None:
    """Never an empty system prompt. A node that silently ran with no persona
    would return a plausible answer from no agent at all, and the run would be
    scored as if the agent had been consulted."""
    node = make_prompt_agent_node(agent_file="nowhere/persona.md", agent_name="a")
    with pytest.raises(PromptAgentError, match="Tried:"):
        node.fn(AEFState(run_id="r", agent_id="a1", objective="go"), _ctx(), _services(_Recorder()))


def test_make_prompt_agent_node_refuses_to_be_built_with_neither_source() -> None:
    with pytest.raises(PromptAgentError, match="neither"):
        make_prompt_agent_node()


def test_a_repo_relative_path_resolves_by_walking_up_from_the_module(tmp_path: Path) -> None:
    """What lets the gates run a migrated graph out of a materialised
    candidate workspace, where the working directory is not the repo root."""
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "persona.md").write_text(PERSONA, encoding="utf-8")
    generated = tmp_path / "agents" / "migrated" / "marlin_accela" / "graph.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("", encoding="utf-8")

    provider = _Recorder()
    node = make_prompt_agent_node(
        agent_file=".claude/agents/persona.md",
        agent_name="marlin-accela",
        module_file=str(generated),
    )
    node.fn(AEFState(run_id="r", agent_id="a1", objective="go"), _ctx(), _services(provider))
    assert provider.requests[0].messages[0].content.startswith("# Marlin Accela agent")


# ---------------------------------------------------------------------------
# Through the real executor, wired the way `aef migrate` wires it
# ---------------------------------------------------------------------------
def test_the_migrated_shape_runs_and_reflection_writes_memory(tmp_path: Path) -> None:
    """`prompt_agent -> reflect -> consolidate -> END`. The tail is the point:
    the reflect node is the only thing that writes the failure memory the
    loop's proposer reads (ADR 0139/0143)."""
    persona = tmp_path / "persona.md"
    persona.write_text(PERSONA, encoding="utf-8")
    services = _services(_Recorder("Sarasota caps reconcile to 412."))
    result = GraphExecutor(_graph(str(persona)).compile(), services).run(
        AEFState(run_id="r1", agent_id="a1", objective="Reconcile the Sarasota cap counts.")
    )
    final = result.final_state
    assert final.working_memory["prompt_agent"] == "Sarasota caps reconcile to 412."
    assert final.reflections, "reflect wrote nothing: the loop would have no evidence"
    assert services.require_memory().query("success", agent_id="a1")
    assert final.provenance and final.provenance[0].model == "test-model"


def _ctx():  # type: ignore[no-untyped-def]
    from aef.kernel import Context

    return Context(
        run_id="r1",
        node_id="prompt_agent",
        graph_version="0.1.0",
        trace_id="t1",
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Containment is recorded per run, not stamped at migrate time (ADR 0169, F4)
# ---------------------------------------------------------------------------
class _Declaring(ModelProvider):
    """A provider that declares an isolation set, like the real ones do."""

    def __init__(self, name: str, isolation: frozenset[str]) -> None:
        self.name = name
        self._isolation = isolation

    @property
    def isolation(self) -> frozenset[str]:
        return self._isolation

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            content="the answer",
            model="m",
            input_tokens=2,
            output_tokens=4,
            cache_read_input_tokens=4_600,
            cache_creation_input_tokens=82,
        )


def _run(
    provider: ModelProvider, tmp_path: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    (tmp_path / "persona.md").write_text(PERSONA, encoding="utf-8")
    node = make_prompt_agent_node(
        agent_file=str(tmp_path / "persona.md"), agent_name="marlin-accela"
    )
    state = AEFState(run_id="r1", agent_id="a1", objective="go")
    delta, _ = node.fn(state, _ctx(), _services(provider))
    return delta.working_memory["prompt_agent__containment"], list(delta.errors)


def test_the_run_records_the_containment_it_actually_got(tmp_path: Path) -> None:
    """The fix for F4. `aef migrate` stamped "THE PROMPT RUNS; THE AGENT'S
    TOOLS DO NOT ... `--tools ''` with `--max-turns 1`" into every generated
    module as a fact about the path, while `CommandProvider` sends whatever an
    owner's template says and `CodexProvider` sends neither flag. A claim that
    varies per provider belongs in the trace, per run."""
    containment, errors = _run(
        _Declaring("claude_code", frozenset({"no_tools", "single_turn", "system_role"})),
        tmp_path,
    )
    assert containment == {
        "provider": "claude_code",
        "isolation": ["no_tools", "single_turn", "system_role"],
        "persona_role": "system",
    }
    assert errors == []


def test_a_persona_sent_in_the_user_turn_is_warned_about_and_not_refused(
    tmp_path: Path,
) -> None:
    """`codex exec` has no system-prompt flag, and a `command:` template with
    no `{system}` slot prepends the persona to the prompt. ADR 0152's safety
    story is that the persona IS the system message; here it is
    untrusted-channel text, so the run says so.

    Not a refusal: some CLIs genuinely have no system flag, and a node that
    refused would be unusable on them."""
    containment, errors = _run(
        _Declaring("codex", frozenset({"read_only_fs", "user_turn_persona"})), tmp_path
    )
    assert containment["persona_role"] == "user"
    assert len(errors) == 1
    assert errors[0]["type"] == "prompt_agent.persona_in_user_turn"
    assert errors[0]["node_id"] == "prompt_agent"
    assert errors[0]["provider"] == "codex"
    assert "USER turn" in str(errors[0]["message"])


def test_a_provider_that_claims_nothing_is_recorded_as_claiming_nothing(
    tmp_path: Path,
) -> None:
    """Three states, not two. A replay-only `CassetteProvider` and any
    hand-built double declare nothing, and manufacturing a channel claim out
    of that absence is the failure this ADR exists to close — so the run
    records `unknown` and does NOT warn."""
    containment, errors = _run(_Declaring("mystery", frozenset()), tmp_path)
    assert containment == {"provider": "mystery", "isolation": [], "persona_role": "unknown"}
    assert errors == []


def test_token_cost_counts_the_cached_context_too(tmp_path: Path) -> None:
    """`input_tokens` is the uncached remainder and was 2 on the calls ADR
    0126's figures came from. A provenance `token_cost` of 6 for a 4,684-token
    call is not a cheap run, it is an unrecorded one (ADR 0169)."""
    (tmp_path / "persona.md").write_text(PERSONA, encoding="utf-8")
    node = make_prompt_agent_node(
        agent_file=str(tmp_path / "persona.md"), agent_name="marlin-accela"
    )
    delta, _ = node.fn(
        AEFState(run_id="r1", agent_id="a1", objective="go"),
        _ctx(),
        _services(_Declaring("claude_code", frozenset({"system_role"}))),
    )
    assert delta.provenance[0].token_cost == 4_688  # 2 + 4600 + 82 uncached/cached + 4 out
