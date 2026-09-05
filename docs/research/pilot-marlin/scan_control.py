"""The control ADR 0119 demands: does the scan actually scan?

A zero from a scanner that never ran and a zero from a clean corpus look the
same. This plants credential-shaped tokens into a REAL recorded run's objective
and working memory and re-runs the same policy, and it checks marlin's own
subscription UUID — the identifier its AGENTS.md boundary rule is written
around — against the default pattern list.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a8eaa76f5710a8548")

from aef.harness.harvest import load_runs  # noqa: E402
from aef.harness.redaction import RedactionPolicy  # noqa: E402
from aef.state import AEFState  # noqa: E402

RUNS = Path(sys.argv[1])
policy = RedactionPolicy()
run = sorted(load_runs(RUNS), key=lambda r: r.at)[0]

PLANTS = {
    "email": "ingest-ops@marlindataco.example.com",
    "api_key": "sk_live_9fJq2LmZ4tRx8Vb1Nc7Hd0Ke",
    "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc",
    "aws_key": "AKIAIOSFODNN7EXAMPLE",
    "opaque_secret": "aG9yaXpvbnRhbGx5U2NhbGVkTWFybGluU2VjcmV0MDEyMzQ1Njc4OQ",
}

print("== control 1: the same policy over the SAME run with tokens planted in the objective")
for label, planted in PLANTS.items():
    state = AEFState.model_validate(run.initial_state.model_dump(mode="json"))
    state = state.model_copy(
        update={"objective": f"{run.initial_state.objective} (contact {planted})"}
    )
    _, count = policy.redact_state(state)
    text, _ = policy.redact_text(state.objective)
    print(f"  {label:15} substitutions={count}  -> ...{text[-46:]}")

print("\n== control 2: secret-shaped working-memory keys are dropped outright")
state = AEFState.model_validate(run.initial_state.model_dump(mode="json"))
state = state.model_copy(
    update={
        "working_memory": {**state.working_memory, "api_key": "x", "token": "y", "keep_me": "z"}
    }
)
redacted, count = policy.redact_state(state)
print(
    f"  before {sorted(state.working_memory)}  ->  "
    f"after {sorted(redacted.working_memory)}  (count={count})"
)

print("\n== control 3: what the default list does NOT catch in THIS repo")
subscription = "7e16b0bb-b75a-4a16-9765-839cf1b96755"
text, count = policy.redact_text(
    f"Marlin subscription {subscription}; resource group rg-marlin-dev"
)
print(f"  marlin's own subscription UUID: substitutions={count}")
print(f"  -> {text}")
print("  reason: `opaque_secret` excludes '-' (ADR 0126 removed it, because a hyphenated")
print("  plain-English objective was being redacted). A UUID is hyphenated, so it survives.")
