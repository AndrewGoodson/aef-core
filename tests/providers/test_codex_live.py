"""The Codex path, measured rather than assumed (ADR 0131).

ADR 0112 shipped `CodexProvider` with its output parsing written from
`codex exec --help` and said so in as many words: *"its parsing is a
hypothesis until a run confirms it."* The CLI on the authoring box could
not parse its own server's model catalogue, so no run could confirm it, and
"works with any coding agent" rested on one verified backend and one guess.

This is the run. It is opt-in twice over — the CLI must be installed AND
`AEF_LIVE_HARNESS` set — because it spends the operator's Codex quota and
takes ~20 s, and a network call inside a routine `pytest -q` is a flaky
test waiting to happen. The command that runs it is in ADR 0131.
"""

from __future__ import annotations

import os
import shutil

import pytest

from aef.providers.base import CompletionRequest, ProviderMessage
from aef.providers.harness_provider import CodexProvider

needs_codex = pytest.mark.skipif(
    not shutil.which("codex") or not os.environ.get("AEF_LIVE_HARNESS"),
    reason="needs the codex CLI and AEF_LIVE_HARNESS=1 (spends quota, ~20s)",
)


@needs_codex
def test_codex_answers_through_the_provider() -> None:
    """Every field the adapter derives, against a real run: the reply comes
    from `--output-last-message`, the usage from the `turn.completed` event's
    `usage` object, and nothing raises on the way."""
    result = CodexProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content="Answer with exactly one word."),
                ProviderMessage(role="user", content="Reply with the single word OK"),
            ),
            model="gpt-5.5",
            max_tokens=200,
        )
    )
    assert result.content.strip() == "OK"
    assert result.model == "gpt-5.5"
    assert result.stop_reason == "end_turn"
    # Parsed from the event stream, not defaulted: a zero here would mean the
    # scan found no `usage` object and quietly reported free.
    assert result.input_tokens > 0
    assert result.output_tokens > 0


@needs_codex
def test_a_prompt_agent_run_through_codex_records_the_persona_channel() -> None:
    """The containment fact, end to end, against the real CLI (ADR 0199).

    J0b's dimension-8 deduction was that *"the Codex path is never exercised
    against the real CLI — its only live test is one of the three skips"*. The
    test above answers that for the adapter's parsing. This one answers it for
    the thing an adopter's containment story actually turns on.

    `codex exec` has no system-prompt flag, so `CodexProvider` prepends the
    persona to the USER turn and declares `user_turn_persona` (ADR 0169/0179).
    `PromptAgentNode` must then record that in
    `working_memory["<node>__containment"]` with the
    `prompt_agent.persona_in_user_turn` warning — because on this backend ADR
    0152's sentence, *the file in Zone A IS the system message*, is FALSE, and
    a run that does not say so lets an adopter inherit a containment claim
    that was measured on a different provider.

    Every previous assertion of this was against a `_Declaring` fake whose
    `isolation` was a hard-coded frozenset. This runs the real graph, with the
    real provider, over the real binary: the isolation set is derived from the
    argv the adapter actually builds, the model actually answers, and the
    containment record is read off the final state.
    """
    from aef.kernel import END, Graph
    from aef.kernel.executor import GraphExecutor
    from aef.reasoning.prompt_agent import (
        CONTAINMENT_SUFFIX,
        CONTAINMENT_WARNING_KEY,
        PERSONA_IN_USER_TURN,
        PERSONA_ROLE_USER,
        PromptAgentDefinition,
        make_prompt_agent_node,
    )
    from aef.services.runtime import agent_services
    from aef.state import AEFState

    node = make_prompt_agent_node(
        definition=PromptAgentDefinition(
            name="one-word-answerer",
            description="answers in exactly one word",
            body="You are a terse assistant. Answer with exactly one word and nothing else.",
        ),
        node_id="persona",
        route=END,
    )
    graph = Graph(
        id="codex_live",
        version="0.1.0",
        nodes={"persona": node},
        edges=[],
        entry_node="persona",
    )
    services = agent_services(model_provider=CodexProvider(timeout_s=600))
    result = GraphExecutor(graph.compile(), services).run(
        AEFState(
            agent_id="codex_live",
            run_id="codex-live",
            objective="Reply with the single word OK",
        )
    )

    assert result.final_state.working_memory["persona"].strip() == "OK"
    containment = result.final_state.working_memory["persona" + CONTAINMENT_SUFFIX]
    assert containment["provider"] == "codex"
    assert "user_turn_persona" in containment["isolation"]
    assert "read_only_fs" in containment["isolation"]
    # And NOT the claim `claude_code` earns: `codex exec` is an agentic loop,
    # this argv sends no `--tools` and no `--max-turns`, and a containment
    # record that said otherwise would be the ADR 0169 defect restored.
    assert "no_tools" not in containment["isolation"]
    assert "single_turn" not in containment["isolation"]
    assert containment["persona_role"] == PERSONA_ROLE_USER
    warning = containment[CONTAINMENT_WARNING_KEY]
    assert warning["type"] == PERSONA_IN_USER_TURN
    assert "no system channel" in warning["message"]
    # A property of the provider, never the run's error (ADR 0179, R3).
    assert result.final_state.errors == []
