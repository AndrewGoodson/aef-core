"""S1b step 0 — seed memory from the TRAIN split, offline, and consolidate.

ADR 0155's four arms compared one configuration against itself because **no
knowledge entry formed in any arm**: every record on the validation split was a
`success` whose signature is `"success:" + objective`, and the objectives are
all distinct, so ADR 0110's two-run threshold was unreachable by construction.
ADR 0174 built the missing producer — a failed owner check now writes a
`kind="failure"` record signed `check:<path>:<op>`, an identity that recurs
across scenarios with different content.

This module produces the experience the arms are then scored *with*. Three
properties, each because a rule of this loop demands it:

1. **Train only.** The arms are scored on VALIDATION. An arm that learned from
   the split it is scored on is not measuring generalisation.
2. **Zero live calls.** Every train scenario carries the cassette
   (`Scenario.model_calls`) the recorder wrote, and this replays it with
   `CassetteProvider(..., on_miss="fail")`. The seed graph therefore has NO
   retrieve node: a lesson appended to the draft prompt changes the request and
   every cassette key misses. That is exactly the arm-(a) prompt shape the
   scenarios were recorded under, so `on_miss="fail"` is the proof rather than
   a hope.
3. **The producer bootstrap uses, called the way bootstrap calls it.** The
   reflect node writes its own record; `write_check_failure_record` adds the
   check-derived one, with the same `None` rules (no checks / all held / the
   run errored).

`seed_stores()` is deterministic and costs nothing, so `arms.py` calls it once
per arm rather than sharing a snapshot: each arm starts from an identical seed
and no arm inherits another's validation-run reflections.

Usage:
  PYTHONPATH=<worktree> <venv>/bin/python seed.py --out results/seed.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

AGENT_ID = "summary_agent"


def build_seed_graph() -> Any:
    """draft -> reflect -> consolidate. No retrieve node — see property 2."""
    import agents.summary.graph as summary
    from aef.kernel import END, Edge, Graph
    from aef.reasoning.nodes import make_consolidate_node, make_reflect_node

    draft = summary.build_graph().nodes["draft"]
    nodes = [draft, make_reflect_node(route="consolidate"), make_consolidate_node(route=END)]
    edges = [
        Edge(from_node="draft", to_node="reflect"),
        Edge(from_node="reflect", to_node="consolidate"),
    ]
    return Graph(
        id="summary",
        version="1.0.0",
        nodes={n.id: n for n in nodes},
        edges=edges,
        entry_node="draft",
    )


def seed_stores(*, verbose: bool = False) -> tuple[Any, Any, list[dict[str, Any]]]:
    """Replay the TRAIN split from its cassettes and return
    `(memory, knowledge, rows)`. No live call is possible: `on_miss="fail"`."""
    from aef.harness.check_memory import write_check_failure_record
    from aef.harness.corpus import Split, fixed_clock, load_corpus
    from aef.harness.evaluation import score_scenario
    from aef.kernel import GraphExecutor
    from aef.providers.cassette_provider import CassetteProvider
    from aef.services.knowledge.consolidate import RuleBasedConsolidator
    from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.services.runtime import agent_services

    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.TRAIN) if s.graph_id == AGENT_ID]
    assert scenarios, "no summary train scenarios"

    memory = InMemoryMemoryStore()
    knowledge = InMemoryKnowledgeStore()
    graph = build_seed_graph()

    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        cassette = CassetteProvider(None, scenario.model_calls, on_miss="fail")
        services = agent_services(
            model_provider=cassette,
            memory=memory,
            knowledge=knowledge,
            agent_id=AGENT_ID,
            reflection="rule_based",
        )
        services = services.__class__(**{**services.__dict__, "clock": fixed_clock(scenario)})
        final = GraphExecutor(graph.compile(), services).run(scenario.initial_state).final_state
        report = score_scenario(scenario, final, elapsed_ms=1.0)
        record = write_check_failure_record(
            memory=memory,
            checks=scenario.checks,
            final_state=final,
            critic=services.require_critic(),
            judge=services.require_judge(),
            run_id=scenario.id,
            agent_id=AGENT_ID,
            created_at=services.clock(),
            graph_version=graph.version,
        )
        rows.append(
            {
                "id": scenario.id,
                "score": round(report.task_completion, 4),
                "failed_checks": None if record is None else list(record.content["failed_checks"]),
                "check_failures": None
                if record is None
                else list(record.content["check_failures"]),
            }
        )
        if verbose:
            failed = f"YES {record.content['failed_checks']}" if record else "no"
            print(
                f"  {scenario.id}: {report.task_completion:.4f} check_failure={failed}", flush=True
            )

    RuleBasedConsolidator().consolidate(memory, knowledge, agent_id=AGENT_ID)
    return memory, knowledge, rows


def dump_records(memory: Any) -> list[dict[str, Any]]:
    return [
        {"kind": k, "id": r.id, "run_id": r.run_id, "content": r.content}
        for k in ("failure", "success")
        for r in memory.query(k, agent_id=AGENT_ID, limit=200)
    ]


def dump_entries(knowledge: Any) -> list[dict[str, Any]]:
    return [
        {
            "kind": e.kind,
            "signature": e.signature,
            "occurrences": e.occurrence_count,
            "confidence": e.confidence,
            "runs": list(e.source_record_ids),
            "content": e.content,
        }
        for k in ("failure", "success")
        for e in knowledge.query(k, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    memory, knowledge, rows = seed_stores(verbose=True)
    records = dump_records(memory)
    entries = dump_entries(knowledge)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"scenarios": len(rows), "rows": rows, "records": records, "entries": entries},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )

    fails = sum(1 for r in records if r["kind"] == "failure")
    print(f"\ntrain scenarios: {len(rows)}   live calls: 0 (cassette, on_miss='fail')")
    print(f"memory: {fails} failure record(s), {len(records) - fails} success record(s)")
    print(f"CONSOLIDATED: {len(entries)} knowledge entr(ies)")
    for e in entries:
        print(f"  {e['signature']}  kind={e['kind']} runs={e['occurrences']} {e['runs']}")
        print(f"    latest_feedback: {str(e['content'].get('latest_feedback', ''))[:200]}")


if __name__ == "__main__":
    main()
