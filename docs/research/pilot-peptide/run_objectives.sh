#!/bin/sh
# Step 4: five real objectives through the real harness, recorded.
# 5 live model calls, one per objective. FOREGROUND, one at a time.
set -e
W=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7
AEFSRC=/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b
cd "$W/peptide"
mkdir -p "$W/runs" "$W/state"

n=$(PATH=/Users/raptor/aef-core/.venv/bin:$PATH python3 -c "import json;print(len(json.load(open('$W/objectives.json'))))")
i=0
while [ "$i" -lt "$n" ]; do
  oid=$(PATH=/Users/raptor/aef-core/.venv/bin:$PATH python3 -c "import json;print(json.load(open('$W/objectives.json'))[$i]['id'])")
  obj=$(PATH=/Users/raptor/aef-core/.venv/bin:$PATH python3 -c "import json;print(json.load(open('$W/objectives.json'))[$i]['objective'])")
  echo "=== $oid"
  PYTHONPATH="$AEFSRC" PATH=/Users/raptor/aef-core/.venv/bin:$PATH \
    /Users/raptor/aef-core/.venv/bin/python -W ignore::RuntimeWarning \
    -m aef.cli.main run agents.migrated.price_freshness_reviewer.graph \
      --objective "$obj" \
      --config aef.yaml \
      --record-runs "$W/runs" \
      --memory "$W/state/memory.jsonl" \
      --observations "$W/state/observations.jsonl" 2>&1 | tail -20
  echo "   rc=$?"
  i=$((i+1))
done
echo "=== runs written:"
ls "$W/runs"
