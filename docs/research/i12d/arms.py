"""N2 — S1c's arms (ADR 0184) re-run on the corpus that exists now.

ADR 0184 measured `(c) > (b)` and ADR 0191 **withdrew** the `+2`, not because
anything in the measurement was shown wrong but because ADR 0186 re-recorded
eighteen scenarios on `claude-opus-5[1m]` in the same hour, on a branch S1c
never saw, so S1c's step 0 no longer reproduces on `main`: one entry from
**three** train runs became one entry from **seven**, with different lesson
text, and the validation split went from four owner-check negatives to eight.
*A measurement that cannot be re-run on the current tree is asserted.* This
runner re-runs it, with the equal repeats S1c could not afford — three of (b)
and three of (c) rather than three and two.

Two differences from `docs/research/i12c/arms.py`, both forced by the tree:

1. **`NEGATIVES` is eight, and it is DERIVED and asserted** rather than
   copied forward. The four Fable-era passes ADR 0186 turned into word-cap
   failures (`sum-13`, `sum-14`, `sum-16`, `sum-17`) join S3b's original four.
   `recorded_negatives()` reconstructs each scenario's recorded final state
   from its own trace and evaluates the owner checks, so a corpus edit moves
   this list instead of silently invalidating it — which is the exact failure
   ADR 0191 punished.
2. **The producer stamps EXECUTION time**, `datetime.now(UTC)`, because ADR
   0191's F4 changed the shipped `run_scenario` to do so. S1c copied
   `created_at=scenario.recorded_at` and reported the consequence as its own
   defect 1: eleven of seventeen scored scenarios could not refresh a lesson,
   because a record dated when the scenario was RECORDED sorts before a lesson
   seeded later. The copy tracks the shipped path, so it changes here too.

## Why this still calls `record_check_outcomes` rather than `run_scenario`

`run_scenario(scenario, graph, memory=store)` is the shipped wiring site and
the block below is a copy of it, argument for argument. It still cannot be
called here, and the reason is unchanged by ADR 0191's fix — that fix
corrected the timestamp, not the wiring:

- `run_scenario` builds its own `agent_services` with a throwaway
  `InMemoryMemoryStore()` and **no knowledge store and no retriever**, so the
  arms' one degree of freedom — what the retriever may read — cannot be
  expressed through it at all. Arms (b) and (c) differ only in that argument.
- It serves model calls from `CassetteProvider(live_provider,
  scenario.model_calls, ...)`. Arms (b) and (c) send a CHANGED prompt (a
  lesson block is prepended), so every call is a cassette miss; reaching the
  model through it would mean `cassette_miss="live"`, which is the gates' live
  path and carries `gates.live_model_calls`. Measuring a retrieval arm is not
  gating a candidate.

So what is reproduced here is the producer call, verbatim, on the store the
arm actually reads. ADR 0184's defect 3 stands and is restated in ADR 0193.

## Why it consolidates immediately after recording

The graph's own consolidate node is the LAST node of the current run, so it
executes before this record exists; the record would first be consolidated at
the end of the next run, which is after that run has already retrieved. One
consolidation here — the same call `seed.py` and `make_consolidate_node` make,
recomputed from records every time (ADR 0091) — removes that one-scenario lag
so the refresh is visible to the next scenario's retrieval.

Model: the session default (`claude-opus-5[1m]`). `--model` is deliberately
empty so no `--model` flag reaches `claude -p`; the answering model is read
back from `modelUsage`.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seed import AGENT_ID, REPO, seed_stores

# The owner-check negatives in the validation split: scenarios whose RECORDED
# run failed an owner check. A word-cap lesson has to act here if it acts
# anywhere. Four of these are S3b's (ADR 0171); the other four were Fable
# passes that ADR 0186's Opus re-recording turned into word-cap failures.
# Written out so a reader of the ADR can see them, and CHECKED against
# `recorded_negatives()` on every run so a corpus edit cannot leave the list
# stale — ADR 0191's lesson applied to this file.
NEGATIVES = (
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
)

RENDER_MAX_ITEMS = 5


def recorded_negatives(scenarios: Any) -> tuple[str, ...]:
    """The scenarios whose OWN recording failed an owner check.

    Reconstructed from each scenario's trace — the last node record's
    `input_state` with its `delta` applied is the state the recording ended
    in — and scored with the shipped `evaluate_checks`. Derived rather than
    remembered: ADR 0186 moved this set from four to eight by re-recording the
    corpus, and a hard-coded list is how ADR 0184's numbers came to describe a
    tree that no longer existed.
    """
    from aef.harness.checks import evaluate_checks

    out: list[str] = []
    for scenario in scenarios:
        if not scenario.trace or not scenario.checks:
            continue
        last = scenario.trace[-1]
        final = last.delta.apply(last.input_state)
        if evaluate_checks(scenario.checks, final).failures:
            out.append(scenario.id)
    return tuple(out)


def build(arm: str, boost: float, model: str, memory: Any, knowledge: Any, provider: Any) -> Any:
    """The graph and services for one arm."""
    import agents.summary.graph as summary
    from aef.kernel import END, Edge, Graph
    from aef.reasoning.nodes import make_consolidate_node, make_reflect_node, make_retrieve_node
    from aef.services.context.memory_retriever import MemoryRetriever
    from aef.services.runtime import agent_services

    draft = summary.build_graph().nodes["draft"]

    retriever = None
    if arm in ("b", "c"):
        retriever = MemoryRetriever(
            memory=memory,
            agent_id=AGENT_ID,
            knowledge=knowledge if arm == "c" else None,
            knowledge_boost=boost if arm == "c" else 0.0,
        )

    services = agent_services(
        model_provider=provider,
        memory=memory,
        knowledge=knowledge,
        retriever=retriever,
        agent_id=AGENT_ID,
        reflection="rule_based",
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


def _entry_state(knowledge: Any, signature: str) -> dict[str, Any]:
    """The SEEDED entry as the store holds it right now — occurrence count and
    staleness, read before the scenario runs so the rank it gets is explained
    by numbers rather than inferred from it.

    Keyed on the signature, not "the first failure entry": once the producer
    is on the scored split a second failure signature can consolidate mid-run
    (a `contains` or `regex` cap on another field), and reading whichever
    entry the store returned first would silently retarget every number in
    this column onto a different lesson.
    """
    for kind in ("failure", "success"):
        for e in knowledge.query(kind, agent_id=AGENT_ID, min_occurrences=1, limit=200):
            if e.signature == signature:
                return {
                    "signature": e.signature,
                    "occurrences": e.occurrence_count,
                    "confidence": round(e.confidence, 4),
                    "runs_since_last_seen": e.runs_since_last_seen,
                    "helpful": e.helpful,
                    "harmful": e.harmful,
                    "harmful_elsewhere": e.harmful_elsewhere,
                }
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["a", "b", "c"])
    ap.add_argument("--repeat", type=int, required=True)
    ap.add_argument("--boost", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jsonl", default="", help="append one line per scenario as it lands")
    ap.add_argument(
        "--model", default="", help="empty (the default) omits --model; session default answers"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from aef.harness.check_memory import record_check_outcomes
    from aef.harness.corpus import Split, load_corpus
    from aef.harness.evaluation import score_scenario
    from aef.kernel import GraphExecutor
    from aef.providers.harness_provider import ClaudeCodeProvider
    from aef.reasoning.nodes import LESSON_HEADER
    from aef.services.knowledge.consolidate import RuleBasedConsolidator

    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == AGENT_ID]
    assert scenarios, "no summary validation scenarios"
    derived = recorded_negatives(scenarios)
    assert derived == NEGATIVES, (
        f"the corpus's owner-check negatives have moved: {derived} != {NEGATIVES}. "
        "Update NEGATIVES and re-run every arm — a mean over the wrong subset is "
        "the defect ADR 0191 withdrew a rubric point for."
    )

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
    boost = args.boost if arm == "c" else 0.0
    t0 = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    jsonl = Path(args.jsonl) if args.jsonl else None
    if jsonl is not None:
        jsonl.parent.mkdir(parents=True, exist_ok=True)

    # Identical seed for every arm; (a) and (b) hold the knowledge store but
    # never read it (no retriever / `knowledge=None` on the retriever), so the
    # only thing that varies between arms is what the model is shown.
    memory, knowledge, _, _ = seed_stores()
    seeded_entries = [
        e.signature
        for k in ("failure", "success")
        for e in knowledge.query(k, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    ]
    # The one lesson this experiment is about. Every `entry_rank` /
    # `entry_in_prompt` / `entry_before` number below is about THIS signature,
    # so an entry that forms later on the scored split cannot be mistaken for
    # it (see `_entry_state`).
    assert len(seeded_entries) == 1, f"expected exactly one seeded entry, got {seeded_entries}"
    target = seeded_entries[0]
    consolidator = RuleBasedConsolidator()

    provider = Counting(default_model=args.model or None, timeout_s=600)
    per_scenario: dict[str, float] = {}
    summaries: dict[str, str] = {}
    failures: dict[str, str] = {}
    draft_prompts: dict[str, str] = {}
    lessons_seen: dict[str, bool] = {}
    entry_rank: dict[str, int | None] = {}
    entry_rendered: dict[str, bool] = {}
    entry_before: dict[str, dict[str, Any]] = {}
    recorded_failures: dict[str, list[str]] = {}
    order: list[str] = []

    for position, scenario in enumerate(scenarios, start=1):
        this_scenario_prompts.clear()
        order.append(scenario.id)
        # Read BEFORE the run: the staleness and occurrence count the
        # retriever is about to rank this entry with.
        entry_before[scenario.id] = _entry_state(knowledge, target)
        graph, services = build(arm, boost, args.model, memory, knowledge, provider)
        from aef.harness.corpus import fixed_clock

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
                and str(c.get("source", "")).endswith(target)
            ),
            None,
        )
        entry_rank[scenario.id] = rank
        # Did the consolidated lesson reach the MODEL, not merely the state?
        # `render_retrieved_context` caps at 5 bullets, so a lesson ranked 6th
        # is retrieved and unread — ADR 0174's defect 0.
        entry_rendered[scenario.id] = rank is not None and rank < RENDER_MAX_ITEMS

        # ---- ADR 0180 fix 2: the producer, on the SCORED split. This is
        # `run_scenario`'s block, argument for argument (see the module
        # docstring for why `run_scenario` itself cannot be called here).
        record = record_check_outcomes(
            memory=memory,
            checks=scenario.checks,
            final_state=final,
            critic=services.require_critic(),
            judge=services.require_judge(),
            run_id=scenario.id,
            agent_id=scenario.initial_state.agent_id or AGENT_ID,
            # EXECUTION time, not the scenario's recording time. This is what
            # the shipped `run_scenario` stamps since ADR 0191's F4, and this
            # block tracks it: a record dated when the scenario was RECORDED
            # sorts before every lesson seeded later, so a scored run could
            # never refresh one (ADR 0184's defect 1, 11 of 17 scenarios).
            created_at=datetime.now(UTC),
            graph_version=graph.version,
        )
        recorded_failures[scenario.id] = (
            [] if record is None else list(record.content["failed_checks"])
        )
        # Re-consolidate now so the refresh is visible to the NEXT retrieval.
        consolidator.consolidate(memory, knowledge, agent_id=AGENT_ID)

        print(
            f"  {arm}/{scenario.id} [{position}/{len(scenarios)}]: "
            f"{per_scenario[scenario.id]:.4f} "
            f"(retrieved={len(final.retrieved_context)}, "
            f"lessons_in_prompt={lessons_seen[scenario.id]}, "
            f"entry_rank={rank}, entry_in_prompt={entry_rendered[scenario.id]}, "
            f"since={entry_before[scenario.id].get('runs_since_last_seen')}, "
            f"occ={entry_before[scenario.id].get('occurrences')}, "
            f"wrote_failure={recorded_failures[scenario.id]})",
            flush=True,
        )
        if jsonl is not None:
            with jsonl.open("a") as fh:
                fh.write(
                    json.dumps(
                        {
                            "arm": arm,
                            "repeat": args.repeat,
                            "boost": boost,
                            "position": position,
                            "scenario": scenario.id,
                            "score": per_scenario[scenario.id],
                            "negative": scenario.id in NEGATIVES,
                            "entry_rank": rank,
                            "entry_in_prompt": entry_rendered[scenario.id],
                            "lessons_in_prompt": lessons_seen[scenario.id],
                            "entry_before": entry_before[scenario.id],
                            "wrote_failure": recorded_failures[scenario.id],
                            "calls": calls["n"],
                        },
                        sort_keys=True,
                    )
                    + "\n"
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
        {
            "kind": e.kind,
            "signature": e.signature,
            "occurrences": e.occurrence_count,
            "runs_since_last_seen": e.runs_since_last_seen,
            "helpful": e.helpful,
            "harmful": e.harmful,
            "harmful_elsewhere": e.harmful_elsewhere,
        }
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
        "order": order,
        "negatives": negatives,
        "summaries": summaries,
        "failures": failures,
        "draft_prompts": draft_prompts,
        "draft_prompt_sha256": prompt_hash,
        "lessons_in_prompt": lessons_seen,
        "entry_rank": entry_rank,
        "entry_in_prompt": entry_rendered,
        "entry_before": entry_before,
        "recorded_failures": recorded_failures,
        "seeded_entries": seeded_entries,
        "knowledge_entries": entries,
        "calls": calls["n"],
        "secs": round(time.time() - t0, 1),
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str))
    skip = {"summaries", "draft_prompts", "entry_before"}
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in skip},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
