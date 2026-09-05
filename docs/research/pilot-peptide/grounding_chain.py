"""N1 clause (b), checked rather than claimed: is the candidate grounded in
evidence that entered the corpus through `harvest`?

Follows the chain the ledger's `grounded_in` names, one link at a time:
    grounded_in record id -> memory record -> its run_id -> a corpus scenario
    -> that scenario's `source`.
"""

from __future__ import annotations

import json
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)

ledger = [json.loads(line) for line in (W / "state" / "ledger.jsonl").read_text().splitlines()]
gated = [e for e in ledger if e["kind"] == "gated"][-1]
grounded = [g.split(" ")[0] for g in gated["detail"]["grounded_in"]]

memory = {}
for line in (W / "state" / "memory.jsonl").read_text().splitlines():
    rec = json.loads(line)
    memory[rec["id"]] = rec

corpus = {}
for f in (W / "peptide" / "corpus" / "train").glob("*.json"):
    s = json.loads(f.read_text())
    corpus[s["id"]] = s

print(f"the gated event cites {len(grounded)} record(s):\n")
all_harvested = True
for rid in grounded:
    rec = memory.get(rid)
    run_id = rec.get("run_id") if rec else None
    scen = corpus.get(run_id or "")
    src = scen.get("source") if scen else None
    all_harvested &= src == "harvest"
    print(f"  {rid}")
    print(f"    memory record kind   : {rec['kind'] if rec else 'NOT FOUND'}")
    print(f"    failed_checks        : {(rec or {}).get('content', {}).get('failed_checks')}")
    print(f"    its run_id           : {run_id}")
    print(f"    a corpus scenario?   : {'yes' if scen else 'NO'}")
    print(f"    that scenario source : {src}")
    print(f"    its objective        : "
          f"{(scen['initial_state']['objective'][:100] + '...') if scen else '-'}")
    print()

print(f"every cited record's run is a corpus scenario whose source is `harvest`: {all_harvested}")
print()
print("the corpus, by source:")
by_src: dict[str, int] = {}
for s in corpus.values():
    by_src[s["source"]] = by_src.get(s["source"], 0) + 1
print(f"  {json.dumps(by_src, sort_keys=True)}  (bootstrap: "
      f"{by_src.get('bootstrap', 0)}, record: {by_src.get('record', 0)})")
