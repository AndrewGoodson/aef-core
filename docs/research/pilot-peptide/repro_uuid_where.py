"""Which field carries the UUID that ADR 0197's pattern refuses?"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from aef.harness.harvest import load_runs  # noqa: E402
from aef.harness.redaction import RedactionPolicy  # noqa: E402

spec = importlib.util.spec_from_file_location("redaction_trunk", W / "redaction_main.py")
assert spec and spec.loader
trunk = importlib.util.module_from_spec(spec)
sys.modules["redaction_trunk"] = trunk
spec.loader.exec_module(trunk)
POLICY = RedactionPolicy(patterns=trunk.DEFAULT_PATTERNS)
uuid_re = re.compile(dict(trunk.DEFAULT_PATTERNS)["uuid"])

run = sorted(load_runs(W / "runs2"), key=lambda r: r.at)[0]
print(f"run_id = {run.run_id}")
print()

state = run.initial_state
print("INITIAL STATE, before redaction — every field carrying a UUID:")
payload = json.loads(state.model_dump_json())
for key, value in payload.items():
    hits = uuid_re.findall(json.dumps(value))
    if hits:
        print(f"   {key}: {hits}")
redacted, n = POLICY.redact_state(state)
print(f"\nredact_state made {n} substitution(s); after it:")
after = json.loads(redacted.model_dump_json())
for key, value in after.items():
    hits = uuid_re.findall(json.dumps(value))
    if hits:
        print(f"   STILL THERE  {key}: {hits}")
print()

print("THE TRACE, which redact_state does not touch and the output scan does read:")
seen: set[str] = set()
for step in run.trace:
    blob = json.dumps(json.loads(json.dumps(step, default=str)), default=str)
    seen |= set(uuid_re.findall(blob))
print(f"   {len(seen)} distinct UUID(s) in the recorded trace: {sorted(seen)}")
print()
print("So the input redaction removes the state's copy and the scenario's own")
print("`id`/`trace` keep theirs — and `harvest` scans the scenario it is about")
print("to write, so the run is refused for carrying its own identifier.")
