"""A Zone A agent whose task a model can fail (ADR 0123).

`agents/demo` fails only by raising: its one node either completes or
records an error, so the task metric could not see content until the demo's
`scores.quality` check, and that check is written by the node that is being
judged. This agent is the corpus's first *content* task — summarise a short
text in at most N words, mentioning every required term — and the answer is
judged by owner-declared `checks` on `working_memory.summary` (ADR 0113),
never by anything the agent writes about itself.

Shape: retrieve → draft → reflect → consolidate. The draft node is the only
one that calls a model, through `services.require_model_provider()`, with
the request's model left to the provider's default so the same recording
replays under any configured default (`CassetteProvider`, ADR 0123). It is
`deterministic=False` and `EXTERNAL_CALL`, as the node contract requires of
anything that asks a model.

Working memory in: `text` (the passage), `max_words` (the cap), and
`must_mention` (terms the summary has to carry). Out: `summary`. The node
computes nothing about its own quality — `scores` stays empty here on
purpose, so the rule-based judge and the LLM judge can be compared against
the checks without a self-report in the middle (I3's A/B, re-run on this
corpus).
"""

from __future__ import annotations

from aef.kernel import END, Context, Edge, Graph, Node, Route, Services, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node, make_retrieve_node
from aef.state import AEFState, Plan, Provenance, StateDelta

DEFAULT_MAX_WORDS = 40

SYSTEM_PROMPT = (
    "You write one-paragraph summaries. Reply with the summary only: no preamble, no "
    "heading, no quotation marks, no bullet points, no closing remark."
)


def _terms(state: AEFState) -> list[str]:
    raw = state.working_memory.get("must_mention", [])
    return [str(t) for t in raw] if isinstance(raw, list) else []


def draft_prompt(text: str, max_words: int, must_mention: list[str]) -> str:
    """The user turn. A function rather than an f-string in the node so the
    prompt is one place a proposer (or a planted regression) can change."""
    lines = [
        f"Summarise the passage below in at most {max_words} words.",
    ]
    if must_mention:
        # The instruction a planted regression drops (ADR 0123's
        # measurement): without it the model summarises freely and the
        # `contains` checks start failing.
        lines.append(
            "The summary must mention each of these terms, spelled exactly as given: "
            + ", ".join(must_mention)
            + "."
        )
    lines += ["", "Passage:", text]
    return "\n".join(lines)


def draft_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    text = str(state.working_memory.get("text", ""))
    max_words = int(state.working_memory.get("max_words", DEFAULT_MAX_WORDS))
    must_mention = _terms(state)

    request = CompletionRequest(
        messages=(
            ProviderMessage(role="system", content=SYSTEM_PROMPT),
            ProviderMessage(role="user", content=draft_prompt(text, max_words, must_mention)),
        ),
        # Empty: the provider's configured default answers. The cassette key
        # includes this string, so a recording made under one default replays
        # under another (ADR 0123).
        model="",
    )
    result = services.require_model_provider().complete(request)
    summary = result.content.strip()

    prov = Provenance(
        node_id=ctx.node_id,
        graph_version=ctx.graph_version,
        model=result.model or None,
        ts=ctx.now,
        trace_id=ctx.trace_id,
        token_cost=result.input_tokens + result.output_tokens,
    )
    return (
        StateDelta(
            working_memory={"summary": summary},
            plan=Plan(goal=state.objective, status="done"),
            provenance=[prov],
        ),
        "reflect",
    )


def build_graph() -> Graph:
    retrieve = make_retrieve_node(route="draft")
    draft = Node(
        id="draft",
        version="0.1.0",
        fn=draft_node,
        deterministic=False,
        side_effects=SideEffect.EXTERNAL_CALL,
        idempotency_key_fn=lambda s: f"{s.run_id}:draft:{s.checkpoint_seq}",
    )
    reflect = make_reflect_node(route="consolidate", memory_tags=("summary",))
    consolidate = make_consolidate_node(route=END)
    return Graph(
        id="summary_agent",
        version="0.1.0",
        nodes={
            "retrieve": retrieve,
            "draft": draft,
            "reflect": reflect,
            "consolidate": consolidate,
        },
        edges=[
            Edge(from_node="retrieve", to_node="draft"),
            Edge(from_node="draft", to_node="reflect"),
            Edge(from_node="reflect", to_node="consolidate"),
        ],
        entry_node="retrieve",
    )
