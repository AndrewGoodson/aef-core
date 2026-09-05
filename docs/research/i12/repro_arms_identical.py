"""Reproduce-first, offline, zero live calls: do the four I12 arms differ in
what actually reaches the model?

Runs arms a/b/c/d over the 6 summary validation scenarios with a FAKE
provider that records every prompt it is handed. If the recorded draft
prompts are byte-identical across arms, the arms cannot differ on the task
metric except by model sampling noise, and the four-arm design measures
nothing about the knowledge layer.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/Users/raptor/aef-core/.claude/worktrees/agent-aa1d8e789950812d0")
sys.path.insert(0, str(ROOT))

import agents.summary.graph as summary  # noqa: E402
from aef.harness.corpus import Split, fixed_clock, load_corpus  # noqa: E402
from aef.kernel import END, Edge, Graph, GraphExecutor  # noqa: E402
from aef.providers.base import CompletionResult, ModelProvider  # noqa: E402
from aef.reasoning.nodes import (  # noqa: E402
    make_consolidate_node,
    make_reflect_node,
    make_retrieve_node,
)
from aef.services.context.memory_retriever import MemoryRetriever  # noqa: E402
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore  # noqa: E402
from aef.services.memory.in_memory import InMemoryMemoryStore  # noqa: E402
from aef.services.runtime import agent_services  # noqa: E402


class Recorder(ModelProvider):
    name = "recorder"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def default_model(self) -> str | None:
        return "fake"

    def complete(self, request):  # type: ignore[no-untyped-def]
        rendered = "\n---\n".join(f"{m.role}: {m.content}" for m in request.messages)
        self.prompts.append(rendered)
        # A deliberately wrong answer so reflection records failures and the
        # knowledge layer actually has something to consolidate.
        return CompletionResult(
            content="A short summary.", model="fake", input_tokens=1, output_tokens=1
        )


def build(arm, memory, knowledge, provider):
    draft = summary.build_graph().nodes["draft"]
    retriever = None
    if arm in ("b", "c", "d"):
        retriever = MemoryRetriever(
            memory=memory,
            agent_id="summary_agent",
            knowledge=knowledge if arm in ("c", "d") else None,
        )
    services = agent_services(
        model_provider=provider,
        memory=memory,
        knowledge=knowledge,
        retriever=retriever,
        agent_id="summary_agent",
        reflection="rule_based",  # arm d's LLM reflection is not the question here
    )
    nodes, edges, entry = [], [], "draft"
    if arm != "a":
        nodes.append(make_retrieve_node(route="draft"))
        edges.append(Edge(from_node="retrieve", to_node="draft"))
        entry = "retrieve"
    nodes += [draft, make_reflect_node(route="consolidate"), make_consolidate_node(route=END)]
    edges += [
        Edge(from_node="draft", to_node="reflect"),
        Edge(from_node="reflect", to_node="consolidate"),
    ]
    graph = Graph(
        id="summary", version="1.0.0", nodes={n.id: n for n in nodes}, edges=edges, entry_node=entry
    )
    return graph, services


def main() -> None:
    corpus = load_corpus(ROOT / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == "summary_agent"]
    out: dict[str, object] = {}
    here = Path(__file__).parent
    for arm in ("a", "b", "c", "d"):
        memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
        provider = Recorder()
        retrieved_counts = []
        for scenario in scenarios:
            graph, services = build(arm, memory, knowledge, provider)
            services = services.__class__(**{**services.__dict__, "clock": fixed_clock(scenario)})
            final = GraphExecutor(graph.compile(), services).run(scenario.initial_state).final_state
            retrieved_counts.append(len(final.retrieved_context))
        joined = "\n\n====\n\n".join(provider.prompts)
        digest = hashlib.sha256(joined.encode()).hexdigest()
        out[arm] = {
            "prompt_sha256": digest,
            "n_prompts": len(provider.prompts),
            "retrieved_chunks_per_scenario": retrieved_counts,
        }
        (here / f"arm_{arm}_prompts.txt").write_text(joined)
    print(json.dumps(out, indent=2, sort_keys=True))
    hashes = {k: v["prompt_sha256"] for k, v in out.items()}  # type: ignore[index]
    print("\nIDENTICAL ACROSS ARMS:", len(set(hashes.values())) == 1)
    (here / "repro_arms_identical.json").write_text(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
