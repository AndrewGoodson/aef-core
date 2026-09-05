"""S1b — ADR 0155's four arms re-run on a corpus whose failures RECUR.

S1 (ADR 0155) ran (a)/(b)/(c)/(d) over a six-scenario validation split and
found the falsification `(c) <= (b)` fired — but for a reason that made the
number meaningless: **zero knowledge entries formed in any arm**, so (b) and
(c) were the same arm and the −0.0207 between them was sampling noise. ADR 0174
built the producer that makes recurrence reachable (a failed owner check writes
a `kind="failure"` record signed `check:<path>:<op>`), and S3b (ADR 0171) built
a corpus with owner-check negatives in both splits.

This runner differs from `docs/research/i12/i12_ace_arms.py` in exactly four
ways, each because of a finding since:

1. **The knowledge store is SEEDED from the TRAIN split** (`seed.py`), offline,
   from the scenarios' own cassettes — 0 live calls. Three train scenarios fail
   `check:working_memory.summary:max_words`, which consolidates to one entry.
   The arms are scored on VALIDATION, so no arm learns from the split it is
   scored on.
2. **Every arm starts from an identical seed**, re-derived per arm rather than
   shared, so no arm inherits another's validation-run reflections.
3. **Arm (c) takes a `--boost`.** `boost_sweep.py` measures where the single
   entry ranks: at the shipped default 0.0 it is chunk 21–23 of 24 and reaches
   `render_retrieved_context`'s top-5 in **0 of 17** scenarios, which would make
   (c) byte-identical to (b) — ADR 0155's defect, repeated. The value (c) ran at
   is recorded in the result JSON and named in the ADR.
4. **17 validation scenarios, not 6**, and the four owner-check negatives are
   reported separately: a lesson about the word cap should act *there* if it
   acts anywhere.

Model: the session default (`claude-opus-5[1m]`). `--model` is deliberately
empty so no `--model` flag reaches `claude -p`; the answering model is read back
from `modelUsage`.

Usage:
  PYTHONPATH=<worktree>:<here> <venv>/bin/python arms.py --arm c --repeat 0 \
      --boost 3.0 --out results/c_r0.json [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from seed import AGENT_ID, REPO, seed_stores

# The four owner-check negatives S3b put in the validation split (ADR 0171):
# scenarios whose recorded run failed an owner check. A word-cap lesson has to
# act here if it acts anywhere.
NEGATIVES = (
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
)


def build(arm: str, boost: float, model: str, memory: Any, knowledge: Any, provider: Any) -> Any:
    """The graph and services for one arm."""
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
            agent_id=AGENT_ID,
            knowledge=knowledge if arm in ("c", "d") else None,
            knowledge_boost=boost if arm in ("c", "d") else 0.0,
        )

    services = agent_services(
        model_provider=provider,
        memory=memory,
        knowledge=knowledge,
        retriever=retriever,
        agent_id=AGENT_ID,
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
    ap.add_argument("--boost", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--model", default="", help="empty (the default) omits --model; session default answers"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from aef.harness.corpus import Split, fixed_clock, load_corpus
    from aef.harness.evaluation import score_scenario
    from aef.kernel import GraphExecutor
    from aef.providers.harness_provider import ClaudeCodeProvider
    from aef.reasoning.nodes import LESSON_HEADER

    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == AGENT_ID]
    assert scenarios, "no summary validation scenarios"

    calls = {"n": 0}
    answered_by: dict[str, int] = {}
    this_scenario_prompts: list[str] = []

    class Counting(ClaudeCodeProvider):
        def complete(self, request):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            this_scenario_prompts.append(
                "\n".join(m.content for m in request.messages if m.role == "user")
            )
            if args.dry_run:
                from aef.providers.base import CompletionResult

                # Deterministic, and shaped like a summary so the reflect node
                # and the checks behave; never a live call.
                return CompletionResult(
                    content="dry run summary placeholder text one two three four five",
                    model="(dry run)",
                    input_tokens=0,
                    output_tokens=0,
                )
            result = super().complete(request)
            answered_by[result.model] = answered_by.get(result.model, 0) + 1
            return result

    arm = args.arm
    boost = args.boost if arm in ("c", "d") else 0.0
    t0 = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Identical seed for every arm; (a) and (b) hold the knowledge store but
    # never read it (no retriever / `knowledge=None` on the retriever), so the
    # only thing that varies between arms is what the model is shown.
    memory, knowledge, _ = seed_stores()
    seeded_entries = [
        e.signature
        for k in ("failure", "success")
        for e in knowledge.query(k, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    ]

    provider = Counting(default_model=args.model or None, timeout_s=600)
    per_scenario: dict[str, float] = {}
    summaries: dict[str, str] = {}
    failures: dict[str, str] = {}
    draft_prompts: dict[str, str] = {}
    lessons_seen: dict[str, bool] = {}
    entry_rank: dict[str, int | None] = {}
    entry_rendered: dict[str, bool] = {}

    for scenario in scenarios:
        this_scenario_prompts.clear()
        graph, services = build(arm, boost, args.model, memory, knowledge, provider)
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
        per_scenario[scenario.id] = score_scenario(
            scenario, final, elapsed_ms=elapsed
        ).task_completion
        summaries[scenario.id] = str(final.working_memory.get("summary", ""))
        draft_prompts[scenario.id] = this_scenario_prompts[0] if this_scenario_prompts else ""
        lessons_seen[scenario.id] = LESSON_HEADER in draft_prompts[scenario.id]
        rank = next(
            (
                i
                for i, c in enumerate(final.retrieved_context)
                if str(c.get("source", "")).startswith("knowledge:")
            ),
            None,
        )
        entry_rank[scenario.id] = rank
        # Did the consolidated lesson reach the MODEL, not merely the state?
        # `render_retrieved_context` caps at 5 bullets, so a lesson ranked 6th
        # is retrieved and unread — ADR 0174's defect 0.
        entry_rendered[scenario.id] = rank is not None and rank < 5
        print(
            f"  {arm}/{scenario.id}: {per_scenario[scenario.id]:.4f} "
            f"(retrieved={len(final.retrieved_context)}, "
            f"lessons_in_prompt={lessons_seen[scenario.id]}, "
            f"entry_rank={rank}, entry_in_prompt={entry_rendered[scenario.id]})",
            flush=True,
        )
        out.write_text(
            json.dumps(
                {
                    "partial": True,
                    "arm": arm,
                    "boost": boost,
                    "per_scenario": per_scenario,
                    "entry_rank": entry_rank,
                    "entry_in_prompt": entry_rendered,
                    "calls": calls["n"],
                },
                indent=2,
                sort_keys=True,
            )
        )

    entries = [
        {"kind": e.kind, "signature": e.signature, "occurrences": e.occurrence_count}
        for kind in ("failure", "success")
        for e in knowledge.query(kind, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    ]
    negatives = {k: v for k, v in per_scenario.items() if k in NEGATIVES}
    positives = {k: v for k, v in per_scenario.items() if k not in NEGATIVES}
    prompt_hash = hashlib.sha256(
        "\n\x00\n".join(draft_prompts[s.id] for s in scenarios if s.id in draft_prompts).encode()
    ).hexdigest()

    result = {
        "arm": arm,
        "repeat": args.repeat,
        "knowledge_boost": boost,
        "dry_run": args.dry_run,
        "model_arg": args.model or "(session default; --model omitted)",
        "answered_by": answered_by,
        "mean": round(statistics.fmean(per_scenario.values()), 4),
        "mean_negatives": round(statistics.fmean(negatives.values()), 4) if negatives else None,
        "mean_positives": round(statistics.fmean(positives.values()), 4) if positives else None,
        "per_scenario": per_scenario,
        "negatives": negatives,
        "summaries": summaries,
        "failures": failures,
        "draft_prompts": draft_prompts,
        "draft_prompt_sha256": prompt_hash,
        "lessons_in_prompt": lessons_seen,
        "entry_rank": entry_rank,
        "entry_in_prompt": entry_rendered,
        "seeded_entries": seeded_entries,
        "knowledge_entries": entries,
        "calls": calls["n"],
        "secs": round(time.time() - t0, 1),
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    skip = {"summaries", "draft_prompts"}
    print(json.dumps({k: v for k, v in result.items() if k not in skip}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
