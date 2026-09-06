"""P2 step 1a — the STATIC `knowledge_boost` sweep, on a store with three
lessons in it.

`docs/research/i12d/boost_sweep.py` (ADR 0193) generalised from one entry to
three. Retrieval ranking only: no model, no live call. It answers the half of
the knob's A/B that a sequential run cannot — *where does EACH lesson rank at
each boost, on the seed as it stands, against every validation objective* —
and it is the instrument that shows the lessons displacing one another.

Two survivals are reported because they are different questions:

- `in_retrieved` — the entry cleared `context_budget_tokens` (8000 here, which
  admits everything, so this is ~always true and is reported to show it);
- `in_top5` — the entry is among the five bullets `render_retrieved_context`
  actually puts in the prompt. **That is the one that decides whether a model
  ever sees the lesson**, and with three lessons and five bullets it is also
  where they compete.

The static picture is the BEST case: it holds the store at its seeded state,
so no entry ages. `dry_identity.py` runs the whole sequential arm under a stub
and gives the WORST case, in which nothing the stub answers refreshes any
lesson. Arm (d)'s boost is chosen from the worst case, so the arm engages
whatever the live trajectory does.

Usage:
  PYTHONPATH=<worktree>:<here> <venv>/bin/python boost_sweep.py --out results/boost_sweep.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from arms import SEEDED, SHORT
from seed import AGENT_ID, REPO, seed_stores

BOOSTS = (0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0)
RENDER_MAX_ITEMS = 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from aef.harness.corpus import Split, load_corpus
    from aef.services.context.memory_retriever import MemoryRetriever

    memory, knowledge, _, _ = seed_stores()
    corpus = load_corpus(REPO / "corpus")
    scenarios = [s for s in corpus.split(Split.VALIDATION) if s.graph_id == AGENT_ID]

    rows: list[dict[str, Any]] = []
    for boost in BOOSTS:
        retriever = MemoryRetriever(
            memory=memory, agent_id=AGENT_ID, knowledge=knowledge, knowledge_boost=boost
        )
        for scenario in scenarios:
            state = scenario.initial_state
            chunks = retriever.retrieve(state.objective, token_budget=state.context_budget_tokens)
            ranks: dict[str, int] = {}
            for i, chunk in enumerate(chunks):
                signature = chunk.metadata.get("signature")
                if isinstance(signature, str) and signature not in ranks:
                    ranks[signature] = i
            rows.append(
                {
                    "boost": boost,
                    "scenario": scenario.id,
                    "chunks": len(chunks),
                    "ranks": {SHORT.get(k, k): v for k, v in ranks.items()},
                    "in_top5": sorted(
                        SHORT.get(k, k) for k, v in ranks.items() if v < RENDER_MAX_ITEMS
                    ),
                }
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True))

    names = [SHORT[s] for s in SEEDED]
    print(f"{len(scenarios)} validation scenario(s); render max_items={RENDER_MAX_ITEMS}\n")
    header = "".join(f"{n + ' med':>11}{n + ' top5':>12}" for n in names)
    print(f"{'boost':>6}{header}")
    for boost in BOOSTS:
        sub = [r for r in rows if r["boost"] == boost]
        cells = []
        for name in names:
            got = sorted(r["ranks"][name] for r in sub if name in r["ranks"])
            med = got[len(got) // 2] if got else None
            top5 = sum(1 for r in sub if name in r["in_top5"])
            cells.append(f"{str(med):>11}{f'{top5}/{len(sub)}':>12}")
        print(f"{boost:>6}" + "".join(cells))

    print("\nper-scenario: which lessons land in the five bullets, by boost:")
    for scenario in scenarios:
        line = [f"  {scenario.id:<28}"]
        for boost in BOOSTS:
            r = next(x for x in rows if x["boost"] == boost and x["scenario"] == scenario.id)
            line.append(f"{len(r['in_top5']):>3}")
        print("".join(line) + f"   (boosts {', '.join(str(b) for b in BOOSTS)})")


if __name__ == "__main__":
    main()
