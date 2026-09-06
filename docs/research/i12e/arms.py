"""P2 — the four arms, on the first store in this programme that holds more
than one lesson.

`docs/research/i12d/arms.py` (ADR 0193) with three changes, each forced by the
question this increment exists to answer. Everything else — the producer block
copied from `run_scenario` argument for argument, the immediate
re-consolidation, the derived negatives, the per-scenario JSONL, the empty
`--model` — is unchanged, and the docstring reasons for all of it are in ADR
0193 and are not restated here.

1. **Four arms, not three.** ADR 0193 ran (a) no retrieve, (b) raw records,
   (c) records + knowledge at a boost chosen to engage the one entry. Here:

   | arm | retriever | knowledge | boost |
   |---|---|---|---|
   | a | none | – | – |
   | b | `MemoryRetriever` | not attached | – |
   | c | `MemoryRetriever` | attached | **0.0 — the shipped default** |
   | d | `MemoryRetriever` | attached | `--boost` |

   (c) is the arm ADR 0193 could not distinguish from (b) and did not run: on a
   one-entry store `(c)@0.0` sent `(b)`'s prompts byte for byte. Whether that
   identity survives a three-entry store is a question, not an assumption, and
   `dry_identity.py` answers it offline before any quota is spent.

2. **Every entry is tracked, not one.** ADR 0193's runner asserted the store
   held exactly ONE entry and keyed every rank column on it. Its own comment
   said why that was temporary — *"once the producer is on the scored split a
   second failure signature can consolidate mid-run … reading whichever entry
   the store returned first would silently retarget every number"*. The store
   now seeds with three, so `entry_rank` and `entry_in_prompt` are dicts keyed
   by SIGNATURE, and each scenario records `lessons_rendered`: the signatures
   that actually landed inside `render_retrieved_context`'s five bullets. That
   column is the thing ADR 0193 says could never be asked.

3. **`SEEDED` is asserted, not counted.** Three signatures, written out, and
   the run refuses if the seed's set differs — the same discipline `NEGATIVES`
   is under, for the same reason (ADR 0191).

Model: the session default (`claude-opus-5[1m]`). `--model` is deliberately
empty so no `--model` flag reaches `claude -p`; the answering model is read
back from `modelUsage`.

Usage:
  PYTHONPATH=<worktree>:<here> <venv>/bin/python arms.py --arm d --repeat 0 \
      --boost 8.0 --out results/d_r0.json [--dry-run]
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
# run failed an owner check. Eight are ADR 0193's; `sum-46` and `sum-47` are
# new and are the first negatives in this corpus that are not word-cap
# overruns — `sum-46` fails Rule A alone, `sum-47` fails Rule A and the cap.
# Checked against `recorded_negatives()` on every run so a corpus edit cannot
# leave the list stale (ADR 0191's lesson).
NEGATIVES = (
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
    "sum-46-thwaite-lane-bridge",
    "sum-47-eller-beck-hatchery",
)

# The three signatures `seed.py` consolidates out of the TRAIN split. Short
# names are for the tables; the signatures are what the code keys on.
WORD_CAP = "failure:check:working_memory.summary:max_words"
RULE_A = "failure:check:working_memory.summary:regex"
BOTH = "failure:check:working_memory.summary:regex>check:working_memory.summary:max_words"
SEEDED = (RULE_A, BOTH, WORD_CAP)
SHORT = {WORD_CAP: "cap", RULE_A: "ruleA", BOTH: "both"}

RENDER_MAX_ITEMS = 5


def recorded_negatives(scenarios: Any) -> tuple[str, ...]:
    """The scenarios whose OWN recording failed an owner check.

    Reconstructed from each scenario's trace — the last node record's
    `input_state` with its `delta` applied is the state the recording ended in
    — and scored with the shipped `evaluate_checks`. Derived rather than
    remembered.
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
    if arm in ("b", "c", "d"):
        retriever = MemoryRetriever(
            memory=memory,
            agent_id=AGENT_ID,
            knowledge=knowledge if arm in ("c", "d") else None,
            knowledge_boost=boost if arm == "d" else 0.0,
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


def _entry_states(knowledge: Any) -> dict[str, dict[str, Any]]:
    """Every entry the store holds right now, by signature — occurrence count,
    confidence and staleness, read BEFORE the scenario runs so the rank each
    one gets is explained by numbers rather than inferred from it."""
    out: dict[str, dict[str, Any]] = {}
    for kind in ("failure", "success"):
        for e in knowledge.query(kind, agent_id=AGENT_ID, min_occurrences=1, limit=200):
            out[e.signature] = {
                "occurrences": e.occurrence_count,
                "confidence": round(e.confidence, 4),
                "runs_since_last_seen": e.runs_since_last_seen,
                "helpful": e.helpful,
                "harmful": e.harmful,
                "harmful_elsewhere": e.harmful_elsewhere,
            }
    return out


def _ranks(final: Any) -> dict[str, int]:
    """signature -> its position among the retrieved chunks, for every
    knowledge entry that was retrieved at all.

    The signature is read from the chunk's `metadata`, not parsed out of its
    `source`: the source is `knowledge:<kind>:<signature>` and the signature
    itself begins with the kind, so `knowledge:failure:failure:check:…` splits
    two ways and only one of them is right. `retrieved_signatures` in
    `aef/reasoning/nodes.py` reads the metadata for the same reason.
    """
    from aef.reasoning.nodes import KNOWLEDGE_SOURCE_PREFIX

    out: dict[str, int] = {}
    for i, chunk in enumerate(final.retrieved_context):
        source = chunk.get("source")
        if not isinstance(source, str) or not source.startswith(KNOWLEDGE_SOURCE_PREFIX):
            continue
        metadata = chunk.get("metadata")
        signature = metadata.get("signature") if isinstance(metadata, dict) else None
        if isinstance(signature, str) and signature:
            out.setdefault(signature, i)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["a", "b", "c", "d"])
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
    boost = args.boost if arm == "d" else 0.0
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
    seeded = tuple(
        e.signature
        for k in ("failure", "success")
        for e in knowledge.query(k, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    )
    assert set(seeded) == set(SEEDED), f"seeded entries have moved: {seeded} != {SEEDED}"
    consolidator = RuleBasedConsolidator()

    provider = Counting(default_model=args.model or None, timeout_s=600)
    per_scenario: dict[str, float] = {}
    summaries: dict[str, str] = {}
    failures: dict[str, str] = {}
    draft_prompts: dict[str, str] = {}
    lessons_seen: dict[str, bool] = {}
    entry_rank: dict[str, dict[str, int]] = {}
    lessons_rendered: dict[str, list[str]] = {}
    entry_before: dict[str, dict[str, dict[str, Any]]] = {}
    recorded_failures: dict[str, list[str]] = {}
    order: list[str] = []

    for position, scenario in enumerate(scenarios, start=1):
        this_scenario_prompts.clear()
        order.append(scenario.id)
        entry_before[scenario.id] = _entry_states(knowledge)
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

        ranks = _ranks(final)
        entry_rank[scenario.id] = ranks
        # WHICH lesson reached the model. `render_retrieved_context` caps at
        # five bullets, so a lesson ranked sixth is retrieved and unread.
        lessons_rendered[scenario.id] = sorted(
            SHORT.get(sig, sig) for sig, r in ranks.items() if r < RENDER_MAX_ITEMS
        )

        record = record_check_outcomes(
            memory=memory,
            checks=scenario.checks,
            final_state=final,
            critic=services.require_critic(),
            judge=services.require_judge(),
            run_id=scenario.id,
            agent_id=scenario.initial_state.agent_id or AGENT_ID,
            created_at=datetime.now(UTC),
            graph_version=graph.version,
        )
        recorded_failures[scenario.id] = (
            [] if record is None else list(record.content["failed_checks"])
        )
        consolidator.consolidate(memory, knowledge, agent_id=AGENT_ID)

        since = {
            SHORT[s]: entry_before[scenario.id].get(s, {}).get("runs_since_last_seen")
            for s in SEEDED
        }
        print(
            f"  {arm}/{scenario.id} [{position}/{len(scenarios)}]: "
            f"{per_scenario[scenario.id]:.4f} "
            f"(retrieved={len(final.retrieved_context)}, "
            f"in_prompt={lessons_rendered[scenario.id]}, "
            f"ranks={ {SHORT.get(k, k): v for k, v in ranks.items()} }, "
            f"since={since}, "
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
                            "entry_rank": {SHORT.get(k, k): v for k, v in ranks.items()},
                            "lessons_rendered": lessons_rendered[scenario.id],
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
                    "lessons_rendered": lessons_rendered,
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
        "lessons_rendered": lessons_rendered,
        "entry_before": entry_before,
        "recorded_failures": recorded_failures,
        "seeded_entries": list(seeded),
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
