"""The step-4 artefact: five real objectives, the answers' shape, and the
verdict line each produced. Redacted (0 substitutions on every one, see
08-redaction.txt) — the objective and the two boundary lines are reproduced;
the answer bodies are not committed, per ADR 0163's rule that the scan's
output is what goes in git.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from aef.harness.harvest import DEFAULT_REDACTION, load_runs  # noqa: E402

OBJ = {o["objective"]: o["id"] for o in json.loads((W / "objectives.json").read_text())}
POLICY = DEFAULT_REDACTION

for label, runs_dir in (("A — with --memory (the 5 of step 4)", "runs"),
                        ("B — without --memory (the 4 re-recorded for step 5, plus O1)", "runs2")):
    print("=" * 78)
    print(f"RUN SET {label}   [{runs_dir}/]")
    print("=" * 78)
    for r in sorted(load_runs(W / runs_dir), key=lambda r: r.at):
        wm: dict = {}
        for step in r.trace:
            for k, v in (getattr(step.delta, "working_memory", None) or {}).items():
                wm[k] = v
        answer = str(wm.get("prompt_agent", ""))
        red_obj, n_obj = POLICY.redact_text(r.initial_state.objective)
        red_ans, n_ans = POLICY.redact_text(answer)
        lines = [ln for ln in red_ans.strip().splitlines() if ln.strip()]
        print()
        print(f"{OBJ.get(r.initial_state.objective, '?')}   run_id={r.run_id}")
        print(f"  at            {r.at.isoformat()}")
        print(f"  model_calls   {len(r.model_calls)}   provider={r.provider_name!r}")
        print(f"  isolation     {list(r.provider_isolation)}")
        print(f"  containment   {wm.get('prompt_agent__containment')}")
        print(f"  answer        {len(answer.split())} words, {len(answer)} chars")
        print(f"  redaction     objective subs={n_obj}, answer subs={n_ans}")
        print(f"  OBJECTIVE     {red_obj}")
        print(f"  FIRST LINE    {lines[0] if lines else ''}")
        print(f"  VERDICT LINE  {lines[-1] if lines else ''}")
    print()
