#!/bin/sh
# Re-run every lint-fixed script from the committed copy and diff its output
# against the committed artefact. A formatting change must change nothing.
AEFSRC=/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b
ART=$AEFSRC/docs/research/pilot-peptide
W=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7
cd "$W" || exit 9

run() {  # run <script> <artefact-or-empty>
  echo "--- $1"
  PYTHONPATH="$AEFSRC" PATH=/Users/raptor/aef-core/.venv/bin:$PATH \
    /Users/raptor/aef-core/.venv/bin/python "$ART/$1" > "$W/rerun-$1.out" 2>&1
  echo "    exit=$?"
  if [ -n "$2" ]; then
    if diff -q "$W/rerun-$1.out" "$ART/$2" > /dev/null 2>&1; then
      echo "    output IDENTICAL to $2"
    else
      echo "    output DIFFERS from $2:"
      diff "$ART/$2" "$W/rerun-$1.out" | head -12
    fi
  else
    tail -2 "$W/rerun-$1.out"
  fi
}

run resolve_base.py 04c-base-ref-derivation.txt
run redaction_scan.py 08-redaction.txt
run arms_harvest.py ""
run diff_request.py ""
run repro_uuid_harvest.py ""
run scan_artefacts.py 24-artefact-scan.txt
run grounding_chain.py 21-grounding-chain.txt
run inspect_runs.py 06-runs-inspected.txt
run mk_answers.py 05-objectives-and-answers.txt
run repro_digest.py 20-digest-defect.txt
run add_checks.py 10-owner-checks.txt
