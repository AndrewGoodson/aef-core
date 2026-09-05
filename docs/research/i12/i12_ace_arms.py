"""I12 / S1 — the ACE measurement on the task metric, one arm-repeat per run.

Adapted from `<scratchpad>/i12_ace_arms.py` (the dry-run-verified original) in
exactly three ways, each because of a rule this loop states:

1. `REPO` points at THIS worker's worktree, not `/Users/raptor/aef-core`.
2. `--model` defaults to EMPTY, which means no `--model` flag reaches
   `claude -p` and the session default answers. The owner authorised Opus
   after `claude-fable-5-1`'s quota was exhausted; the model that actually
   answers is read back from `modelUsage` and recorded, never assumed.
3. One `(arm, repeat)` per process, writing its JSON to `--out` as it
   completes. Earlier attempts in this programme lost three runs to
   all-or-nothing invocations.

Four arms over the summary corpus's validation split, scored by the SAME
`score_scenario` the gates use (ADR 0113), cassette off so every arm makes
its own live calls:

  a) no retrieve node                  — the control
  b) retrieve, raw records only        — memory without the wiki
  c) retrieve, records + knowledge     — ADR 0110's layer
  d) (c) + reflection.impl: llm        — ADR 0115's judge/critic

Usage:
  PYTHONPATH=<worktree> <venv>/bin/python i12_ace_arms.py --arm c --repeat 0 \
      --out results/c_r0.json [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

REPO = Path("/Users/raptor/aef-core/.claude/worktrees/agent-aa1d8e789950812d0")


def build(arm: str, model: str, memory, knowledge, provider):
    """The graph and services for one arm. Imported lazily so --help works
    without the package."""
    import agents.summary.graph as summary
    from aef.kernel import END, Edge, Graph
    from aef.reasoning.nodes import make_consolidate_node, make_reflect_node, make_retrieve_node
    from aef.services.context.memory_retriever import MemoryRetriever
    from aef.services.runtime import agent_services

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
        reflection="llm" if arm == "d" else "rule_based",
        reflection_model=model or None,
    )

    nodes = []
    edges = []
    entry = "draft"
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["a", "b", "c", "d"])
    ap.add_argument("--repeat", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--model",
        default="",
        help="empty (the default) omits --model so the session default answers",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from wordcap import delinearise_scenario

    from aef.harness.corpus import Split, fixed_clock, load_corpus
    from aef.harness.evaluation import score_scenario
    from aef.kernel import GraphExecutor
    from aef.providers.harness_provider import ClaudeCodeProvider
    from aef.reasoning.nodes import LESSON_HEADER
    from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
    from aef.services.memory.in_memory import InMemoryMemoryStore

    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == "summary_agent"]
    assert scenarios, "no summary validation scenarios — did I11 land?"

    calls = {"n": 0}
    answered_by: dict[str, int] = {}
    # Every user turn this scenario sent, so the ADR can show that the lessons
    # actually reached the model rather than asserting it.
    this_scenario_prompts: list[str] = []

    class Counting(ClaudeCodeProvider):
        def complete(self, request):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            this_scenario_prompts.append(
                "\n".join(m.content for m in request.messages if m.role == "user")
            )
            if args.dry_run:
                from aef.providers.base import CompletionResult

                return CompletionResult(
                    content="(dry run)", model="(dry run)", input_tokens=0, output_tokens=0
                )
            result = super().complete(request)
            answered_by[result.model] = answered_by.get(result.model, 0) + 1
            return result

    arm = args.arm
    t0 = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Fresh stores per repeat: each arm must earn its own experience, or arm
    # (c) inherits (b)'s and the comparison is meaningless.
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    provider = Counting(default_model=args.model or None, timeout_s=600)
    per_scenario: dict[str, float] = {}
    summaries: dict[str, str] = {}
    failures: dict[str, str] = {}
    draft_prompts: dict[str, str] = {}
    lessons_seen: dict[str, bool] = {}
    for scenario in scenarios:
        this_scenario_prompts.clear()
        graph, services = build(arm, args.model, memory, knowledge, provider)
        services = services.__class__(**{**services.__dict__, "clock": fixed_clock(scenario)})
        started = time.monotonic()
        try:
            final = GraphExecutor(graph.compile(), services).run(scenario.initial_state).final_state
        except Exception as exc:  # noqa: BLE001 - a failed run scores 0, honestly
            print(f"  {arm}/{scenario.id}: FAILED {type(exc).__name__}: {exc}", flush=True)
            per_scenario[scenario.id] = 0.0
            failures[scenario.id] = f"{type(exc).__name__}: {exc}"
            continue
        elapsed = (time.monotonic() - started) * 1000.0
        # `delinearise_scenario` rewrites the corpus's exponential word-cap
        # regex to a proven-equivalent linear one. WITHOUT IT THIS DOES NOT
        # TERMINATE: the check exists to catch an over-length summary, and it
        # is exactly an over-length summary that makes it backtrack forever
        # (36 words: no answer in 600s). Every other check, and
        # `score_scenario` itself, is untouched. See `wordcap.py` for the
        # equivalence proof and ADR 0155 for the defect report.
        per_scenario[scenario.id] = score_scenario(
            delinearise_scenario(scenario), final, elapsed_ms=elapsed
        ).task_completion
        summaries[scenario.id] = str(final.working_memory.get("summary", ""))
        # The draft node is the FIRST model call of a scenario.
        draft_prompts[scenario.id] = this_scenario_prompts[0] if this_scenario_prompts else ""
        lessons_seen[scenario.id] = LESSON_HEADER in draft_prompts[scenario.id]
        print(
            f"  {arm}/{scenario.id}: {per_scenario[scenario.id]:.4f} "
            f"(retrieved={len(final.retrieved_context)}, "
            f"lessons_in_prompt={lessons_seen[scenario.id]})",
            flush=True,
        )
        # Checkpoint after EVERY scenario: an invocation killed at the tool
        # timeout must not lose the scenarios that already answered.
        out.write_text(
            json.dumps(
                {"partial": True, "arm": arm, "per_scenario": per_scenario, "calls": calls["n"]},
                indent=2,
                sort_keys=True,
            )
        )

    # Did the knowledge layer produce anything at all on this split? The arm
    # (c) claim is unanswerable without this number.
    entries = [
        {"kind": e.kind, "signature": e.signature, "occurrences": e.occurrence_count}
        for kind in ("failure", "success")
        for e in knowledge.query(kind, agent_id="summary_agent", limit=50)  # type: ignore[arg-type]
    ]

    result = {
        "arm": arm,
        "repeat": args.repeat,
        "model_arg": args.model or "(session default; --model omitted)",
        "answered_by": answered_by,
        "mean": round(statistics.fmean(per_scenario.values()), 4),
        "per_scenario": per_scenario,
        "summaries": summaries,
        "failures": failures,
        "draft_prompts": draft_prompts,
        "lessons_in_prompt": lessons_seen,
        "knowledge_entries": entries,
        "calls": calls["n"],
        "secs": round(time.time() - t0, 1),
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    skip = {"summaries", "draft_prompts"}
    print(json.dumps({k: v for k, v in result.items() if k not in skip}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
