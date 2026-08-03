"""A three-node graph demonstrating the full Phase 0/1 DI wiring: a model
call, a policy-gated tool call, and a summarize step, all writing to
working memory and being scored by an Evaluator afterward.

Every backend used here is in-memory (report §4's `examples/` constraint):
`InMemoryMemoryStore`, `InMemoryTracer`, `InMemoryDurabilityBackend`, and
`EchoModelProvider` below, which is NOT a real vendor adapter — it exists
only so this example runs with no API key and no network call, while still
exercising the real `ModelProvider` interface and DI path a real adapter
(e.g. `AnthropicProvider`) would use identically.
"""

from __future__ import annotations

from aef.kernel import END, Context, Edge, Graph, Node, Route, Services, SideEffect
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider, ProviderMessage
from aef.security.tool import PolicyDecision, Tool, ToolCall
from aef.services.memory.base import MemoryRecord
from aef.state import AEFState, Message, Plan, Provenance, StateDelta


class EchoModelProvider(ModelProvider):
    """Demo-only stand-in for a real model. Deterministic in practice, but
    the node that calls it is still declared `deterministic=False` — by
    convention, every LLM-calling node is non-deterministic, regardless of
    what today's stub happens to do."""

    name = "echo"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        return CompletionResult(
            content=f"[echo] {last_user}",
            model=request.model,
            input_tokens=len(last_user.split()),
            output_tokens=4,
        )


class WebSearchTool(Tool):
    name = "web_search_ro"
    required_scopes = ("web_search_ro",)

    def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
        return {"query": arguments.get("query"), "results": ["result one", "result two"]}


def _complete(services: Services, text: str) -> CompletionResult:
    provider = services.require_model_provider()
    request = CompletionRequest(
        messages=(ProviderMessage(role="user", content=text),), model="echo-model"
    )
    return provider.complete(request)


def _provenance(ctx: Context, result: CompletionResult) -> Provenance:
    return Provenance(
        node_id=ctx.node_id,
        graph_version=ctx.graph_version,
        model=result.model,
        ts=ctx.now,
        trace_id=ctx.trace_id,
        token_cost=result.input_tokens + result.output_tokens,
    )


def draft_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    result = _complete(services, state.objective)
    prov = _provenance(ctx, result)

    services.require_memory().write(
        MemoryRecord(
            kind="working",
            content={"text": result.content},
            run_id=state.run_id,
            agent_id=state.agent_id,
        )
    )

    delta = StateDelta(
        messages=[Message(role="assistant", content=result.content, prov=prov)],
        provenance=[prov],
        plan=Plan(goal=state.objective, status="active"),
    )
    return delta, "search"


def search_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    tool = WebSearchTool()
    call = ToolCall(tool_name=tool.name, arguments={"query": state.objective}, risk=0.0)
    decision = services.require_policy_engine().evaluate(tool, call)

    if decision.decision is not PolicyDecision.ALLOW:
        error_delta = StateDelta(errors=[{"node_id": ctx.node_id, "error": decision.reason}])
        return error_delta, "summarize"

    result = tool.invoke(call.arguments)
    return StateDelta(tool_results=[result]), "summarize"


def summarize_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    result = _complete(services, f"summarize: {state.tool_results}")
    prov = _provenance(ctx, result)

    prior_goal = state.plan.goal if state.plan is not None else state.objective
    plan = Plan(goal=prior_goal, status="done")

    delta = StateDelta(
        messages=[Message(role="assistant", content=result.content, prov=prov)],
        provenance=[prov],
        plan=plan,
    )
    return delta, END


def build_graph() -> Graph:
    draft = Node(id="draft", version="0.1.0", fn=draft_node, deterministic=False)
    search = Node(
        id="search",
        version="0.1.0",
        fn=search_node,
        deterministic=False,
        side_effects=SideEffect.EXTERNAL_CALL,
        idempotency_key_fn=lambda state: state.run_id,
    )
    summarize = Node(id="summarize", version="0.1.0", fn=summarize_node, deterministic=False)

    return Graph(
        id="hello_agent",
        version="0.1.0",
        nodes={"draft": draft, "search": search, "summarize": summarize},
        edges=[
            Edge(from_node="draft", to_node="search"),
            Edge(from_node="search", to_node="summarize"),
        ],
        entry_node="draft",
    )
