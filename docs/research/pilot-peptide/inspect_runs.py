"""What `aef run --record-runs` actually wrote for the five real objectives."""

from __future__ import annotations

import json
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
RUNS = W / "runs"
OBJ = {o["objective"][:60]: o["id"] for o in json.loads((W / "objectives.json").read_text())}

rows = []
for f in sorted(RUNS.glob("*.json")):
    d = json.loads(f.read_text())
    st = d.get("initial_state", {})
    objective = st.get("objective", "")
    trace = d.get("trace", [])
    wm: dict = {}
    answer = ""
    for step in trace:
        delta = step.get("delta") or {}
        for k, v in (delta.get("working_memory") or {}).items():
            wm[k] = v
    answer = str(wm.get("prompt_agent", ""))
    rows.append(
        {
            "run_id": d.get("run_id", "")[:8],
            "oid": OBJ.get(objective[:60], "?"),
            "graph_id": d.get("graph_id"),
            "model_calls": len(d.get("model_calls") or []),
            "provider_name": d.get("provider_name", ""),
            "provider_isolation": list(d.get("provider_isolation") or []),
            "containment": wm.get("prompt_agent__containment"),
            "answer_chars": len(answer),
            "answer_words": len(answer.split()),
            "first_line": answer.strip().splitlines()[0] if answer.strip() else "",
            "last_line": answer.strip().splitlines()[-1] if answer.strip() else "",
        }
    )

for r in sorted(rows, key=lambda r: r["oid"]):
    print(f"{r['oid']}  run={r['run_id']}  graph={r['graph_id']}")
    print(f"   model_calls={r['model_calls']}  provider_name={r['provider_name']!r}")
    print(f"   provider_isolation={r['provider_isolation']}")
    print(f"   containment={r['containment']}")
    print(f"   answer: {r['answer_words']} words, {r['answer_chars']} chars")
    print(f"   first line: {r['first_line']}")
    print(f"   last  line: {r['last_line']}")
    print()

print(f"runs={len(rows)}  with a cassette={sum(1 for r in rows if r['model_calls'])}"
      f"  with a declaration={sum(1 for r in rows if r['provider_isolation'])}")
