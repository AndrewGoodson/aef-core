"""S1b step 2 — the `knowledge_boost` sweep ADR 0174's defect 0 demands.

ADR 0110 swept 0 / 0.5 / 1 / 3 and recorded that the knob "changed no coverage
number anywhere", so the default is 0.0. ADR 0174 found the first
counter-example: on S3b's split the single check-derived entry ranks 14 of 24
at the default and 3 of 24 at 0.5, so it survives `render_retrieved_context`'s
`max_items=5` only when boosted. 0110's sweep ran on a corpus that could not
produce a check-derived entry at all.

This is the same question asked of THIS rig's seed (train split, ADR 0174's
producer, 20 successes + 3 failures + 1 entry) against every VALIDATION
objective — retrieval ranking only, no model, no live call. It decides one
thing: **the boost arm (c) runs at**. Running (c) at a default that provably
hides the only lesson there is would measure the default, not the layer.

It reports two different survivals, because they are different questions:

- `in_retrieved` — the entry cleared `context_budget_tokens` (8000 here, which
  admits everything, so this is ~always true and is reported to show it);
- `in_top5` — the entry is among the five bullets `render_retrieved_context`
  actually puts in the prompt. **That is the one that decides whether a model
  ever sees the lesson.**

Usage:
  PYTHONPATH=<worktree> <venv>/bin/python boost_sweep.py --out results/boost_sweep.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from seed import AGENT_ID, REPO, seed_stores

BOOSTS = (0.0, 0.5, 1.0, 3.0)
RENDER_MAX_ITEMS = 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from aef.harness.corpus import Split, load_corpus
    from aef.reasoning.nodes import render_retrieved_context
    from aef.services.context.memory_retriever import MemoryRetriever
    from aef.state import AEFState

    memory, knowledge, _ = seed_stores()
    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == AGENT_ID]

    rows: list[dict[str, Any]] = []
    for boost in BOOSTS:
        retriever = MemoryRetriever(
            memory=memory, agent_id=AGENT_ID, knowledge=knowledge, knowledge_boost=boost
        )
        for scenario in scenarios:
            state: AEFState = scenario.initial_state
            chunks = retriever.retrieve(state.objective, token_budget=state.context_budget_tokens)
            rank = next(
                (i for i, c in enumerate(chunks) if c.source.startswith("knowledge:")), None
            )
            rendered = render_retrieved_context(
                state.model_copy(
                    update={
                        "retrieved_context": [
                            {
                                "content": c.content,
                                "source": c.source,
                                "relevance_score": c.relevance_score,
                                "token_estimate": c.token_estimate,
                                "metadata": dict(c.metadata),
                            }
                            for c in chunks
                        ]
                    }
                )
                if hasattr(state, "model_copy")
                else state,
                max_items=RENDER_MAX_ITEMS,
            )
            rows.append(
                {
                    "boost": boost,
                    "scenario": scenario.id,
                    "chunks": len(chunks),
                    "entry_rank": rank,
                    "in_retrieved": rank is not None,
                    "in_top5": rank is not None and rank < RENDER_MAX_ITEMS,
                    "entry_score": None if rank is None else round(chunks[rank].relevance_score, 4),
                    "top_score": round(chunks[0].relevance_score, 4) if chunks else None,
                    "rendered_bullets": rendered.count("\n- "),
                }
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True))

    print(f"{len(scenarios)} validation scenario(s); render max_items={RENDER_MAX_ITEMS}\n")
    print(f"{'boost':>6} {'median rank':>12} {'rank range':>12} {'in top-5':>10} {'chunks':>8}")
    for boost in BOOSTS:
        sub = [r for r in rows if r["boost"] == boost]
        ranks = [r["entry_rank"] for r in sub if r["entry_rank"] is not None]
        ranks.sort()
        med = ranks[len(ranks) // 2] if ranks else None
        top5 = sum(1 for r in sub if r["in_top5"])
        print(
            f"{boost:>6} {str(med):>12} "
            f"{(str(ranks[0]) + '-' + str(ranks[-1]) if ranks else '-'):>12} "
            f"{f'{top5}/{len(sub)}':>10} {sub[0]['chunks']:>8}"
        )
    print("\nper-scenario entry rank (of chunks), by boost:")
    for scenario in scenarios:
        line = [f"  {scenario.id:<24}"]
        for boost in BOOSTS:
            r = next(x for x in rows if x["boost"] == boost and x["scenario"] == scenario.id)
            mark = "*" if r["in_top5"] else " "
            line.append(f"{str(r['entry_rank']):>4}{mark}")
        print("".join(line))
    print("  (* = survives render_retrieved_context's top-5)")


if __name__ == "__main__":
    main()
