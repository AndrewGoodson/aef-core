"""ADR 0119's redaction scan, run over every recorded run of the M6 pilot.

Prints, per run: the objective (post-redaction), the input-side substitution
count, which working-memory keys the policy drops outright, the labels the
OUTPUT scan matches on the scenario harvest would write, and the first line of
the answer AFTER redaction. This output is the artefact; the raw recorded runs
are never committed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a8eaa76f5710a8548")

from aef.harness.corpus import Scenario, Split  # noqa: E402
from aef.harness.harvest import _scannable, load_runs  # noqa: E402
from aef.harness.redaction import DEFAULT_PATTERNS, RedactionPolicy  # noqa: E402

RUNS = Path(sys.argv[1])
policy = RedactionPolicy()

print("redaction policy (ADR 0119) — patterns, in match order:")
for label, pattern in DEFAULT_PATTERNS:
    print(f"  {label:16} {pattern}")
print(f"  working_memory keys dropped outright: {list(policy.drop_working_memory_keys)}")

runs = sorted(load_runs(RUNS), key=lambda r: r.at)
print(f"\n{len(runs)} recorded run(s)\n")

totals = {"input_subs": 0, "output_hits": 0, "wm_dropped": 0}
for run in runs:
    redacted, count = policy.redact_state(run.initial_state)
    wm_keys = set(run.initial_state.working_memory)
    dropped = sorted(wm_keys & set(policy.drop_working_memory_keys))
    scenario = Scenario(
        id=run.run_id,
        split=Split.TRAIN,
        graph_id=run.graph_id,
        graph_version=run.graph_version,
        initial_state=run.initial_state,
        trace=run.trace,
        recorded_at=run.at,
        model_calls=run.model_calls,
    )
    hits = policy.find(_scannable(scenario))
    final = run.initial_state
    for record in run.trace:
        final = record.delta.apply(final)
    answer = str(final.working_memory.get("prompt_agent", ""))
    red_answer, answer_subs = policy.redact_text(answer)
    first = red_answer.splitlines()[0] if red_answer else ""
    print(f"run_id      {run.run_id}")
    print(f"  graph_id    {run.graph_id}")
    print(f"  objective   {policy.redact_text(run.initial_state.objective)[0][:150]}")
    print(
        f"  INPUT scan  {count} substitution(s); working-memory keys dropped: {dropped or 'none'}"
    )
    print(
        f"  OUTPUT scan {list(hits) or 'clean'}   "
        "(labels matching the scenario harvest would write)"
    )
    print(
        f"  answer      {len(answer.split())} words, {len(answer)} chars; "
        f"{answer_subs} substitution(s) inside the answer"
    )
    print(f"  first line  {first[:200]}")
    print(f"  model_calls {len(run.model_calls)}  <-- what `aef run --record-runs` pinned")
    print()
    totals["input_subs"] += count
    totals["output_hits"] += len(hits)
    totals["wm_dropped"] += len(dropped)

print(json.dumps(totals))
