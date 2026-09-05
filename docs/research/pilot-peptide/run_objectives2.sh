#!/bin/sh
# The four objectives F-N7-1 made unharvestable, re-recorded WITHOUT --memory
# so each one's retrieve node reads an empty store — which is the operator
# workaround for F-N7-1, and its cost. 4 live model calls.
set -e
W=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7
AEFSRC=/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b
cd "$W/peptide"
mkdir -p "$W/runs2"
cp "$W/runs/7961a9cf-8ade-4ec1-83c9-2cb22f026426.json" "$W/runs2/" 2>/dev/null || true

for i in 1 2 3 4; do
  oid=$(PATH=/Users/raptor/aef-core/.venv/bin:$PATH python3 -c "import json;print(json.load(open('$W/objectives.json'))[$i]['id'])")
  obj=$(PATH=/Users/raptor/aef-core/.venv/bin:$PATH python3 -c "import json;print(json.load(open('$W/objectives.json'))[$i]['objective'])")
  echo "=== $oid"
  PYTHONPATH="$AEFSRC" PATH=/Users/raptor/aef-core/.venv/bin:$PATH \
    /Users/raptor/aef-core/.venv/bin/python -W ignore::RuntimeWarning \
    -m aef.cli.main run agents.migrated.price_freshness_reviewer.graph \
      --objective "$obj" \
      --config aef.yaml \
      --record-runs "$W/runs2" \
      --observations "$W/state/observations.jsonl" > /dev/null 2>&1
  echo "   rc=$?"
done
echo "=== runs2:"
ls "$W/runs2"
