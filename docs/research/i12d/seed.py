"""N2 step 0 — seed memory from the TRAIN split, offline, and consolidate.

This is `docs/research/i12c/seed.py` (ADR 0184) run against the corpus that
exists NOW. Not one line of its logic is changed, and that is the point: ADR
0191 withdrew S1c's `+2` because ADR 0186 re-recorded eighteen scenarios on
`claude-opus-5[1m]` on a branch S1c never saw, so S1c's step 0 — one entry
from three train runs — does not reproduce on `main`. The seed below is the
same program; the table it prints is not the same table, and the diff is the
first deliverable of this increment.

What ADR 0186 changed underneath it: `sum-01`…`sum-18` were `claude-fable-5-1`
recordings and are now Opus ones, and Opus writes longer — four more TRAIN
scenarios (`sum-04`, `sum-05`, `sum-08`, `sum-11`) and four more VALIDATION
scenarios (`sum-13`, `sum-14`, `sum-16`, `sum-17`) now fail the owner word cap
that they passed. So the lesson consolidates from more runs and the scored
split carries twice the negatives.

Three properties are unchanged from S1b/S1c, each because a rule of this loop
demands it:

- **Train only.** The arms are scored on VALIDATION. An arm that learned from
  the split it is scored on is not measuring generalisation.
- **Zero live calls.** Every train scenario carries the cassette
  (`Scenario.model_calls`) the recorder wrote, and this replays it with
  `CassetteProvider(..., on_miss="fail")`. The seed graph therefore has NO
  retrieve node: a lesson appended to the draft prompt changes the request and
  every cassette key misses. That is exactly the arm-(a) prompt shape the
  scenarios were recorded under, so `on_miss="fail"` is the proof rather than
  a hope.
- **`seed_stores()` is deterministic and costs nothing**, so `arms.py` calls it
  once per arm rather than sharing a snapshot: each arm starts from an
  identical seed and no arm inherits another's validation-run reflections.

`assert_no_excerpt` (ADR 0180) is kept and still runs: no 12-character window
of any train run's output may appear anywhere in any record derived from it.

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

# ADR 0180's regression property, restated on this corpus. Twelve characters is
# short enough that an excerpt of any useful length trips it — the shipped test
# (`test_no_record_repeats_a_window_of_the_output_it_was_computed_from`) uses
# the same width on two real outputs.
EXCERPT_WINDOW = 12


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


def windows(text: str, width: int = EXCERPT_WINDOW) -> set[str]:
    """Every `width`-character window of `text`, or the empty set if shorter."""
    if len(text) < width:
        return set()
    return {text[i : i + width] for i in range(len(text) - width + 1)}


def assert_no_excerpt(records: list[dict[str, Any]], outputs: dict[str, str]) -> int:
    """ADR 0180's property, checked on this rig's own seed.

    Returns the number of (record, output) pairs checked. Raises if any
    12-character window of a run's own summary survives anywhere in the
    content of a record derived from that run.
    """
    checked = 0
    for record in records:
        blob = json.dumps(record["content"], sort_keys=True, default=str)
        output = outputs.get(str(record.get("run_id") or ""), "")
        if not output:
            continue
        checked += 1
        leaked = sorted(w for w in windows(output) if w in blob)
        if leaked:
            raise AssertionError(
                f"record {record['id']} (run {record['run_id']}) repeats "
                f"{len(leaked)} window(s) of its run's output, e.g. {leaked[0]!r}"
            )
    return checked


def seed_stores(*, verbose: bool = False) -> tuple[Any, Any, list[dict[str, Any]], dict[str, str]]:
    """Replay the TRAIN split from its cassettes and return
    `(memory, knowledge, rows, outputs)`. No live call is possible:
    `on_miss="fail"`. `outputs` maps run id -> the summary that run produced,
    for `assert_no_excerpt`."""
    from aef.harness.check_memory import record_check_outcomes
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
    outputs: dict[str, str] = {}
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
        outputs[scenario.id] = str(final.working_memory.get("summary", ""))
        # ADR 0180's `record_check_outcomes`: `check_failure_record` written to
        # the store at most once per (agent, run, failed check keys).
        record = record_check_outcomes(
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
    return memory, knowledge, rows, outputs


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
            "runs_since_last_seen": e.runs_since_last_seen,
            "helpful": e.helpful,
            "harmful": e.harmful,
            "harmful_elsewhere": e.harmful_elsewhere,
            "content": e.content,
        }
        for k in ("failure", "success")
        for e in knowledge.query(k, agent_id=AGENT_ID, min_occurrences=1, limit=200)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    memory, knowledge, rows, outputs = seed_stores(verbose=True)
    records = dump_records(memory)
    entries = dump_entries(knowledge)
    checked = assert_no_excerpt(records, outputs)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "scenarios": len(rows),
                "rows": rows,
                "records": records,
                "entries": entries,
                "excerpt_check": {"window": EXCERPT_WINDOW, "records_checked": checked},
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )

    fails = sum(1 for r in records if r["kind"] == "failure")
    print(f"\ntrain scenarios: {len(rows)}   live calls: 0 (cassette, on_miss='fail')")
    print(f"memory: {fails} failure record(s), {len(records) - fails} success record(s)")
    print(
        f"EXCERPT PROPERTY (ADR 0180): 0 windows of {EXCERPT_WINDOW} chars of any run's "
        f"output found in any of the {checked} record(s) derived from it"
    )
    print(f"CONSOLIDATED: {len(entries)} knowledge entr(ies)")
    for e in entries:
        print(
            f"  {e['signature']}  kind={e['kind']} runs={e['occurrences']} "
            f"conf={e['confidence']} since={e['runs_since_last_seen']} "
            f"tally=(h={e['helpful']} x={e['harmful']} xe={e['harmful_elsewhere']}) {e['runs']}"
        )
        print(f"    latest_feedback: {str(e['content'].get('latest_feedback', ''))[:300]}")


if __name__ == "__main__":
    main()
