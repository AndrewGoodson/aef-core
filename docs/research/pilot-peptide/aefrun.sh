#!/bin/sh
# N7 pilot: run the worktree's aef inside the CLONE, with paths scrubbed.
# usage: sh aefrun.sh <outfile> <args...>
W=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7
AEFSRC=/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b
OUT="$1"; shift
cd "$W/peptide" || exit 9
PYTHONPATH="$AEFSRC" PATH=/Users/raptor/aef-core/.venv/bin:$PATH \
  /Users/raptor/aef-core/.venv/bin/python -W ignore::RuntimeWarning \
  -m aef.cli.main "$@" > "$W/raw.tmp" 2>&1
rc=$?
sed -e "s#$W/peptide#<repo>#g" -e "s#$W#<W>#g" -e "s#$AEFSRC#<aefsrc>#g" "$W/raw.tmp" > "$W/$OUT"
echo "EXIT=$rc"
cat "$W/$OUT"
exit 0
